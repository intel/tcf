#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""

"""
import bisect
import collections
import getpass
import json
import logging
import os
import pprint
import sys
import socket
import time
import uuid

import requests
import requests.exceptions
import tabulate

import commonl
import tcfl.tc
import tcfl.ttb_client
from . import msgid_c
    

def _delete(rtb, allocid):
    try:
        rtb.send_request(
            "DELETE", "allocation/%s" % allocid,
            timeout_extra = None
        )
    except requests.ConnectionError as e:
        # this server is out
        logging.warning("%s: %s", rtb, e)
        return
    except requests.HTTPError as e:
        logging.warning("%s: %s", rtb, e)
        # FIXME: HACK: this means invalid allocation,
        # already wiped


# FIXME: what happens if the target is disabled / removed while we wait
# FIXME: what happens if the conn
def _alloc_targets(rtb, groups, obo = None, keepalive_period = 4,
                   queue_timeout = None, priority = 700, preempt = False,
                   queue = True, reason = None, wait_in_queue = True,
                   register_at = None, extra_data = None, endtime = None):
    """:param set register_at: (optional) if given, this is a set where
      we will add the allocation ID created only if ACTIVE or QUEUED
      inmediately as we get it before doing any waiting.

      This is used for being able to cleanup on the exit path if the
      client is cancelled.

    :param dict extra_data: dict of scalars with extra data, for
      implementation use; this extra data is client specifc, the
      server will record it in the allocation and some drivers might
      use it.

      Known fields:

      - *uuid*: an RFC4122 v4 UUID for this allocation, used to
        coordinate across-server resources (eg: network tunneling)

        >>> import uuid
        >>> alloc_uuid = str(uuid.uuid4())
        >>> alloc_uuid = "a5e000a8-25ed-42a2-96c2-d9e361465367"

    :param str endtime: (optional, default *None*) at what time the
      allocation shall expire (in UTC) formatted as a string:

      - *None* (default): the allocation expires when it is deemed
        idle by the server or when deleted/destroyed by API call.

      - *static*: the allocation never expires, until manually
        deleted/destroyed by API call.

      - *YYYYmmddHHMMSS*: date and time when the allocation has to
        expire, in the same format as timestamps, ie:

        >>> ts = time.strftime("%Y%m%d%H%M%S")

        If hours/minutes/seconds are not needed, set to zero, eg:

        >>> "20230930000000"
    """
    assert isinstance(groups, dict)
    assert register_at == None or isinstance(register_at, set)

    data = dict(
        priority = priority,
        preempt = preempt,
        queue = queue,
        groups = {},
        reason = reason,
        endtime = endtime,
    )
    if obo:
        data['obo_user'] = obo
    if extra_data != None:
        commonl.assert_dict_of_types(extra_data, "extra_data",
                                     (bool, int, float, str))
        data['extra_data'] = extra_data
    data['groups'] = groups
    r = rtb.send_request("PUT", "allocation", json = data)

    ts0 = time.time()
    state = r['state']
    if state not in ( 'queued', 'active'):
        raise RuntimeError(
            "allocation failed: %s: %s"
            % (state, r.get('_message', 'message n/a')))
    allocid = r['allocid']
    if register_at != None:	# if empty, it is ok
        register_at.add(allocid)
    data = { allocid: state }
    if state == 'active':			# got it
        return allocid, state, r['group_allocated'].split(',')
    if queue_timeout == 0:
        return allocid, state, {}
    ts = time.time()
    group_allocated = []
    commonl.progress(
        "allocation ID %s: [+%.1fs] keeping alive during state '%s'" % (
            allocid, ts - ts0, state))
    new_state = state		# in case we don't wait
    retry_ts = None
    retry_timeout = 40
    while wait_in_queue:
        try:
            if queue_timeout and ts - ts0 > queue_timeout:
                raise tcfl.tc.blocked_e(
                    "can't acquire targets, still busy after %ds"
                    % queue_timeout, dict(targets = groups))
            time.sleep(keepalive_period)
            ts = time.time()
            state = data[allocid]
            try:
                #print(f"DEBUG: alloc/keepalive", file = sys.stderr)
                r = rtb.send_request("PUT", "keepalive", json = data)
            except requests.exceptions.RequestException as e:
                ts = time.time()
                if retry_ts == None:
                    retry_ts = ts
                else:
                    if ts - retry_ts > retry_timeout:
                        raise RuntimeError(
                            f"alloc/keepalive giving up after {retry_timeout}s"
                            f" retrying connection errors") from e
                logging.warning(
                    f"retrying for {retry_timeout - (ts - retry_ts):.0f}s"
                    f" alloc/keepalive after connection error {type(e)}: {e}")
                continue
        except KeyboardInterrupt:
            # HACK: if we are interrupted, cancel this allocation so
            # it is not left hanging and makes it all confusing
            ts0 = ts
            ts = time.time()
            if allocid:
                print("\nallocation ID %s: [+%.1fs] releasing due to user interruption" % (
                    allocid, ts - ts0))
                _delete(rtb, allocid)
            raise

        # COMPAT: old version packed the info in the 'result' field,
        # newer have it in the first level dictionary
        if 'result' in r:
            result = r.pop('result')
            r.update(result)
        # COMPAT: end
        commonl.progress(
            "allocation ID %s: [+%.1fs] alloc/keeping alive during state '%s': %s"
            % (allocid, ts - ts0, state, r))

        if allocid not in r:
            continue # no news
        if 'state' not in r[allocid]:
            logging.error(f"WARNING: {allocid}: CORRECTING: invalid server response? no 'state' in: {r}")
            new_state = r[allocid]
        else:
            new_state = r[allocid]['state']
        if new_state == 'active':
            r = rtb.send_request("GET", "allocation/%s" % allocid)
            group_allocated = r['group_allocated'].split(',')
            break
        elif new_state == 'invalid':
            print("\nallocation ID %s: [+%.1fs] now invalid" % (
                allocid, ts - ts0))
            break
        print("\nallocation ID %s: [+%.1fs] state transition %s -> %s" % (
            allocid, ts - ts0, state, new_state))
        data[allocid] = new_state
    return allocid, new_state, group_allocated


def _alloc_hold(rtb, allocid, state, ts0, max_hold_time, keep_alive_period):
    retry_ts = None
    retry_timeout = 40
    while True:
        time.sleep(keep_alive_period)
        ts = time.time()
        if max_hold_time > 0 and ts - ts0 > max_hold_time:
            # maximum hold time reached, release it
            break
        data = { allocid: state }
        try:
            #print(f"DEBUG: holding/keepalive ", file = sys.stderr)
            r = rtb.send_request("PUT", "keepalive", json = data)
        except requests.exceptions.RequestException as e:
            ts = time.time()
            if retry_ts == None:
                retry_ts = ts
            else:
                if ts - retry_ts > retry_timeout:
                    raise RuntimeError(
                        f"alloc/keepalive giving up after {retry_timeout}s"
                        f" retrying connection errors") from e
            logging.warning(
                f"retrying for {retry_timeout - (ts - retry_ts):.0f}s"
                f" hold/keepalive after connection error {type(e)} {e}")
            continue

        # COMPAT: old version packed the info in the 'result' field,
        # newer have it in the first level dictionary
        if 'result' in r:
            result = r.pop('result')
            r.update(result)
        # COMPAT: end
        commonl.progress(
            "allocation ID %s: [+%.1fs] hold/keeping alive during state '%s': %s"
            % (allocid, ts - ts0, state, r))
        # r is a dict, allocids that changed state of the ones
        # we told it in 'data'
        ## { ALLOCID1: STATE1, ALLOCID2: STATE2 .. }
        new_data = r.get(allocid, None)
        if new_data == None:
            continue			# no new info

        if 'state' not in r[allocid]:
            logging.error(f"WARNING: {allocid}: CORRECTING: invalid server response? no 'state' in: {r}")
            new_state = r[allocid]
        else:
            new_state = r[allocid]['state']

        if new_state not in ( 'active', 'queued', 'restart-needed' ):
            print()	# to get a newline in
            break
        if new_state != data[allocid]:
            print("\nallocation ID %s: [+%.1fs] state transition %s -> %s" % (
                allocid, ts - ts0, state, new_state))
        state = new_state

def _cmdline_alloc_targets(args):
    with msgid_c("cmdline"):
        targetl = tcfl.ttb_client.cmdline_list(args.target, args.all)
        if not targetl:
            logging.error("No targets could be used (missing? disabled?)")
            return
        targets = set()
        rtbs = set()

        # to use fullid, need to tweak the refresh code to add the aka part
        tl = []
        for rt in sorted(targetl, key = lambda x: x['fullid']):
            targets.add(rt['id'])
            rtbs.add(rt['rtb'])
            tl.append(f"{rt['rtb'].aka}/{rt['id']}")
        if len(rtbs) > 1:
            raise tcfl.error_e(
                f"Targets span more than one server: {' '.join(tl)}",
                { "targets": tl })
        rtb = list(rtbs)[0]
        allocid = args.allocid
        try:
            groups = { "group": list(targets) }
            ts0 = time.time()
            if allocid == None:
                extra_data = dict()
                if args.uuid:
                    extra_data['uuid'] = str(uuid.uuid4())
                for extra_spec in args.extra_data:
                    # specified as FIELD:VALUE, with VALUE encoded as
                    # i:NN f:FF s:STR..
                    key, value = extra_spec.split(":", 1)
                    extra_data[key] = commonl.cmdline_str_to_value(value)
                if not extra_data:
                    extra_data = None
                allocid, state, group_allocated = \
                    _alloc_targets(rtb, groups, obo = args.obo,
                                   preempt = args.preempt,
                                   queue = args.queue, priority = args.priority,
                                   reason = args.reason,
                                   extra_data = extra_data,
                                   wait_in_queue = args.wait_in_queue,
                                   endtime = args.endtime)
                ts = time.time()
                if args.wait_in_queue:
                    print("allocation ID %s: [+%.1fs] allocated: %s" % (
                        allocid, ts - ts0, " ".join(group_allocated)))
                else:
                    print("allocation ID %s: [+%.1fs] registered" % (
                        allocid, ts - ts0))
            else:
                print("%s: NOT ALLOCATED! Holdin allocation ID given with -a" \
                    % allocid)
                state = 'unknown'	# wild guess
                ts = time.time()
            if args.hold == None:	# user doesn't want us to ...
                return			# ... keepalive while active
            _alloc_hold(rtb, allocid, state, ts0, args.hold, args.keepalive_period)
        except KeyboardInterrupt:
            ts = time.time()
            if allocid:
                print("\nallocation ID %s: [+%.1fs] releasing due to user interruption" % (
                    allocid, ts - ts0))
                _delete(rtb, allocid)



def _rtb_allocid_extract(allocid):
    rtb = None
    if '/' in allocid:
        server_aka, allocid = allocid.split('/', 1)
        for rtb in tcfl.ttb_client.rest_target_brokers.values():
            if rtb.aka == server_aka:
                return rtb, allocid
        logging.error("%s: unknown server name", server_aka)
        return None, allocid
    return None, allocid

def _guests_add(rtb, allocid, guests):
    for guest in guests:
        try:
            rtb.send_request("PATCH", "allocation/%s/%s"
                             % (allocid, guest))
        except requests.HTTPError as e:
            logging.warning("%s: can't add guest %s: %s",
                            allocid, guest, e)


def _guests_remove(rtb, allocid, guests):
    if not guests:
        # no guests given, remove'em all -- so list them first
        r = rtb.send_request("GET", "allocation/%s" % allocid)
        guests = r.get('guests', [])
    for guest in guests:
        try:
            r = rtb.send_request("DELETE", "allocation/%s/%s"
                                 % (allocid, guest))
        except requests.HTTPError as e:
            logging.error("%s: can't remove guest %s: %s",
                          allocid, guest, e)


def _cmdline_guest_add(args):
    with msgid_c("cmdline"):
        rtb, allocid = _rtb_allocid_extract(args.allocid)
        if rtb == None:
            # Unknown server, so let's try them all ... yeah,
            # collateral damage might happen--but then, you can
            # only delete yours
            for rtb in tcfl.ttb_client.rest_target_brokers.values():
                _guests_add(rtb, allocid, args.guests)
        else:
            _guests_add(rtb, allocid, args.guests)




def _cmdline_guest_remove(args):
    with msgid_c("cmdline"):
        rtb, allocid = _rtb_allocid_extract(args.allocid)
        if rtb == None:
            # Unknown server, so let's try them all ... yeah,
            # collateral damage might happen--but then, you can
            # only delete yours
            for rtb in tcfl.ttb_client.rest_target_brokers.values():
                _guests_remove(rtb, allocid, args.guests)
        else:
            _guests_remove(rtb, allocid, args.guests)


try:
    username = getpass.getuser() + "@"
except KeyError:
    # inside containers with a user with no name to the ID it'll raise
    ## KeyError: 'getpwuid(): uid not found: 121'
    username = ""


def _cmdline_setup(arg_subparsers):
    ap = arg_subparsers.add_parser(
        "acquire",
        help = "Allocate targets for exclusive use")
    commonl.argparser_add_aka(arg_subparsers, "acquire", "alloc-targets")
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "Consider also disabled targets")
    ap.add_argument(
        "-r", "--reason", action = "store",
        # use instead of getfqdn(), since it does a DNS lookup and can
        # slow things a lot
        default = "cmdline %s@%s:%d" % (
            username, socket.gethostname(), os.getppid()),
        help = "Reason to pass to the server (default: %(default)s)"
        " [LOGNAME:HOSTNAME:PARENTPID]")
    ap.add_argument(
        "--hold", action = "store_const",
        const = 0, dest = "hold", default = None,
        help = "Keep the reservation alive until cancelled with Ctrl-C")
    ap.add_argument(
        "-d", "--hold-for", dest = "hold", action = "store",
        nargs = "?", type = int, default = None,
        help = "Keep the reservation alive for this many seconds, "
        "then release it")
    ap.add_argument(
        "--keepalive-period", action = "store", metavar = "SECONDS",
        type = int, default = 5,
        help = "Send keepalives every SECONDS seconds (default: %(default)ds)")
    ap.add_argument(
        "-w", "--wait", action = "store_true", dest = 'queue', default = True,
        help = "(default) Wait until targets are assigned")
    ap.add_argument(
        "--dont-wait", action = "store_false", dest = 'wait_in_queue',
        default = True,
        help = "Do not wait until targets are assigned")
    ap.add_argument(
        "-i", "--inmediate", action = "store_false", dest = 'queue',
        help = "Fail if target's can't be allocated inmediately")
    ap.add_argument(
        "-p", "--priority", action = "store", type = int, default = 500,
        help = "Priority (0 highest, 999 lowest)")
    ap.add_argument(
        "-o", "--obo", action = "store", default = None,
        help = "User to alloc on behalf of")
    ap.add_argument(
        "--preempt", action = "store_true", default = False,
        help = "Enable preemption (disabled by default)")
    ap.add_argument("--extra-data", metavar = "FIELD:VALUE", action = "append",
                    default = [],
                    help = "add extra data values to the allocation; VALUE "
                    "can be casted with i:NUMBER f:FLOAT s:STRING b:BOOL")
    ap.add_argument("--uuid", action = "store_true", default = False,
                    help = "set a UUID in the allocation")
    ap.add_argument(
        "--endtime",
        metavar = "YYYYmmddHHMMSS", action = "store", default = None,
        help = "This allocation shall finish at the given UTC time;"
        " otherwise it will expire when idle or removed with alloc-rm"
        " or an equivalent API call (see also --static)")
    ap.add_argument(
        "--static",
        action = "store_const", const = "static", dest = "endtime",
        help = "This allocation shall not expire and will last until manually"
        " removed with alloc-rm or equivalent API call")
    ap.add_argument(
        "target", metavar = "TARGETSPEC", nargs = "+",
        action = "store", default = None,
        help = "Target's names, all in the same server")
    ap.set_defaults(func = _cmdline_alloc_targets)


def _cmdline_setup_intermediate(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "guest-add",
        help = "Add a guest to an allocation")
    ap.add_argument(
        "allocid", metavar = "[SERVER/]ALLOCATIONID",
        action = "store", default = None,
        help = "Allocation IDs to which to add guest to")
    ap.add_argument(
        "guests", metavar = "USERNAME", nargs = "+",
        action = "store", default = None,
        help = "Name of guest to add")
    ap.set_defaults(func = _cmdline_guest_add)

    ap = arg_subparsers.add_parser(
        "guest-rm",
        help = "Remove a guest from an allocation")
    commonl.argparser_add_aka(arg_subparsers, "guest-rm", "guest-remove")
    ap.add_argument(
        "allocid", metavar = "[SERVER/]ALLOCATIONID",
        action = "store", default = None,
        help = "Allocation IDs to which to add guest to")
    ap.add_argument(
        "guests", metavar = "USERNAME", nargs = "*",
        action = "store", default = None,
        help = "Name of guest to remove (all if none given)")
    ap.set_defaults(func = _cmdline_guest_remove)
