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
        message = str(e)
        if 'invalid allocation' not in message:
            raise tcfl.error_e(f"{rtb}: {message}") from e
        # FIXME: HACK: this means invalid allocation,
        # already wiped


# FIXME: what happens if the target is disabled / removed while we wait
# FIXME: what happens if the conn
def _alloc_targets(rtb, groups, obo = None, keepalive_period = 4,
                   queue_timeout = None, priority = 700, preempt = False,
                   queue = True, reason = None, wait_in_queue = True,
                   register_at = None):
    """
    :param set register_at: (optional) if given, this is a set where
      we will add the allocation ID created only if ACTIVE or QUEUED
      inmediately as we get it before doing any waiting.

      This is used for being able to cleanup on the exit path if the
      client is cancelled.
    """
    assert isinstance(groups, dict)
    assert register_at == None or isinstance(register_at, set)

    data = dict(
        priority = priority,
        preempt = preempt,
        queue = queue,
        groups = {},
        reason = reason,
    )
    if obo:
        data['obo_user'] = obo
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
                allocid, state, group_allocated = \
                    _alloc_targets(rtb, groups, obo = args.obo,
                                   preempt = args.preempt,
                                   queue = args.queue, priority = args.priority,
                                   reason = args.reason,
                                   wait_in_queue = args.wait_in_queue)
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


def _allocs_get(rtb, username):
    try:
        r = rtb.send_request("GET", "allocation/")
    except (Exception, tcfl.ttb_client.requests.HTTPError) as e:
        logging.error("%s", e)
        return {}
    if username:
        # filter here, as we can translate the username 'self' to the
        # user we are logged in as in the server
        _r = {}
        if username == "self":
            username = rtb.logged_in_username()

        def _alloc_filter(allocdata, username):
            if username != None \
               and username != allocdata.get('creator', None) \
               and username != allocdata.get('user', None):
                return False
            return True

        for allocid, allocdata in r.items():
            if _alloc_filter(allocdata, username):
                _r[allocid] = allocdata
            else:
                logging.info(f"filtered out {rtb._url} {allocdata}")

        return _r
    else:
        return r


def _alloc_ls(verbosity, username = None):
    allocs = {}
    tp = tcfl.ttb_client._multiprocessing_pool_c(
        processes = len(tcfl.ttb_client.rest_target_brokers))
    threads = {}
    for rtb in sorted(tcfl.ttb_client.rest_target_brokers.values(), key = str):
        threads[rtb] = tp.apply_async(_allocs_get, (rtb, username))
    tp.close()
    tp.join()
    for rtb, thread in threads.items():
        allocs[rtb] = thread.get()

    if verbosity < 0:
        # just print the list of alloc ids for each server, one per line
        for _, data in allocs.items():
            if data:
                print("\n".join(data.keys()))
        return
    elif verbosity == 3:
        pprint.pprint(allocs)
        return
    elif verbosity == 4:
        print(json.dumps(allocs, skipkeys = True, indent = 4))
        return

    table = []
    for rtb, r in allocs.items():
        for allocid, data in r.items():
            userl = []
            user = data.get('user', None)
            creator = data['creator']
            guests = data.get('guests', [])
            if 'priority' in data:
                prio = str(data['priority'])
                if data['preempt']:
                    prio += ":P"
            else:
                prio = "n/a"
            userl = [ user ]
            if user != creator:
                userl.append(creator + " (creator)")
            for guest in guests:
                userl.append(guest + " (guest)")
            if verbosity == 0:
                table.append([
                    allocid,
                    # put state/prio/preempt together
                    data['state'] + " " + prio,
                    "\n".join(userl),
                    len(data.get('target_group', [])),
                    data.get('reason', "n/a"),
                ])
            elif verbosity == 1:
                tgs = []
                for name, group in data.get('target_group', {}).items():
                    tgs.append( name + ": " + ",".join(group))
                table.append([
                    allocid,
                    rtb.aka,
                    data['state'],
                    prio,
                    data.get('timestamp', 'n/a'),
                    "\n".join(userl),
                    "\n".join(tgs),
                    data.get('reason', "n/a"),
                ])
            elif verbosity == 2:
                commonl.data_dump_recursive(data, allocid,)
    if verbosity == 0:
        headers0 = [
            "AllocID",
            "State",
            "Users",
            "#Groups",
            "Reason"
        ]
        print(tabulate.tabulate(table, headers = headers0))
    if verbosity == 1:
        headers1 = [
            "AllocID",
            "Server",
            "State",
            "Priority",
            "Timestamp",
            "Users",
            "Groups",
            "Reason",
        ]
        print(tabulate.tabulate(table, headers = headers1))

def _cmdline_alloc_ls(args):
    with msgid_c("cmdline"):
        targetl = tcfl.ttb_client.cmdline_list(args.target, args.all)
        targets = collections.OrderedDict()

        if not tcfl.ttb_client.rest_target_brokers:
            logging.error("E: no servers available, did you configure?")
            return

        # to use fullid, need to tweak the refresh code to add the aka part
        for rt in sorted(targetl, key = lambda x: x['fullid']):
            target_name = rt['fullid']
            targets[target_name] = \
                tcfl.tc.target_c.create_from_cmdline_args(
                    # load no extensions, not needed, plus faster
                    args, target_name, extensions_only = [])

        if args.refresh:
            print("\x1b[2J")	# clear whole screen
            print("\x1b[1;1H")	# move to column 1,1
            sys.stdout.flush()
            clear = True
            ts0 = time.time()
            while True:
                try:
                    if clear:
                        print("\x1b[2J")	# clear whole screen
                        clear = False
                    _alloc_ls(args.verbosity - args.quietosity, args.username)
                    ts0 = time.time()
                except requests.exceptions.RequestException as e:
                    ts = time.time()
                    print("[LOST CONNECTION +%ds]: %s" % (ts - ts0, e))
                    clear = True

                print("\x1b[0J")	# clean what is left
                print("\x1b[1;1H")	# move to column 1,1
                sys.stdout.flush()
                time.sleep(args.refresh)
        else:
            _alloc_ls(args.verbosity - args.quietosity, args.username)

def _cmdline_alloc_delete(args):
    with msgid_c("cmdline"):

        # we don't know which request is on which server, so we send
        # it to all the servers
        def _allocid_delete(allocid):

            try:
                rtb = None
                if '/' in allocid:
                    server_aka, allocid = allocid.split('/', 1)
                    for rtb in tcfl.ttb_client.rest_target_brokers.values():
                        if rtb.aka == server_aka:
                            rtb = rtb
                            _delete(rtb, allocid)
                            return
                    else:
                        logging.error("%s: unknown server name", server_aka)
                        return
                # Unknown server, so let's try them all ... yeah,
                # collateral damage might happen--but then, you can
                # only delete yours
                for rtb in tcfl.ttb_client.rest_target_brokers.values():
                    _delete(rtb, allocid)
            except Exception as e:
                logging.exception("Exception: %s", e)

        def _allocid_delete_by_user(rtb, username):

            try:
                # translates username == 'self' on its own
                if username == "self":
                    username = rtb.logged_in_username()
                allocs = _allocs_get(rtb, username)
                for allocid in allocs:
                    print(f"removed {allocid} @{rtb}")
                    _delete(rtb, allocid)
                return
            except Exception as e:
                logging.exception("Exception: %s", e)

        threads = {}
        if args.allocid:
            tp = tcfl.ttb_client._multiprocessing_pool_c(
                processes = len(args.allocid))
            for allocid in args.allocid:
                threads[allocid] = tp.apply_async(_allocid_delete,
                                                  (allocid,))
        elif args.username:
            tp = tcfl.ttb_client._multiprocessing_pool_c(
                processes = len(tcfl.ttb_client.rest_target_brokers))
            for rtb in tcfl.ttb_client.rest_target_brokers.values():
                threads[rtb] = tp.apply_async(_allocid_delete_by_user,
                                                  (rtb, args.username,))
        else:
            raise RuntimeError(
                "Need to specify ALLOCIDs or --user USERNAME or --self;"
                " see --help")
        tp.close()
        tp.join()

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


def _guests_list(rtb, allocid):
    r = rtb.send_request("GET", "allocation/%s" % allocid)
    print("\n".join(r.get('guests', [])))

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



def _cmdline_guest_list(args):
    with msgid_c("cmdline"):
        rtb, allocid = _rtb_allocid_extract(args.allocid)
        if rtb == None:
            # Unknown server, so let's try them all ... yeah,
            # collateral damage might happen--but then, you can
            # only delete yours
            for rtb in tcfl.ttb_client.rest_target_brokers.values():
                _guests_list(rtb, allocid)
        else:
            _guests_list(rtb, allocid)



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
        "alloc-targets",
        help = "Allocate targets for exclusive use")
    commonl.argparser_add_aka(arg_subparsers, "alloc-targets", "acquire")
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
    ap.add_argument(
        "target", metavar = "TARGETSPEC", nargs = "+",
        action = "store", default = None,
        help = "Target's names, all in the same server")
    ap.set_defaults(func = _cmdline_alloc_targets)

    ap = arg_subparsers.add_parser(
        "alloc-ls",
        help = "List information about current allocations "
        "in all the servers or the servers where the named "
        "targets are")
    commonl.argparser_add_aka(arg_subparsers, "alloc-ls", "alloc-list")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Decrease verbosity of information to display "
        "(none is a table, -q or more just the list of allocations,"
        " one per line")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Increase verbosity of information to display "
        "(none is a table, -v table with more details, "
        "-vv hierarchical, -vvv Python format, -vvvv JSON format)")
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "Consider also disabled targets")
    ap.add_argument(
        "-u", "--username", action = "store", default = None,
        help = "ID of user whose allocs are to be displayed"
        " (optional, defaults to anyone visible)")
    ap.add_argument(
        "-r", "--refresh", action = "store",
        type = float, nargs = "?", const = 1, default = 0,
        help = "Repeat every int seconds (by default, only once)")
    ap.add_argument(
        "target", metavar = "TARGETSPEC", nargs = "*",
        action = "store", default = None,
        help = "Target's names or a general target specification "
        "which might include values of tags, etc, in single quotes (eg: "
        "'zephyr_board and not type:\"^qemu.*\"'")
    ap.set_defaults(func = _cmdline_alloc_ls)

    ap = arg_subparsers.add_parser(
        "alloc-rm",
        help = "Delete an existing allocation (which might be "
        "in any state; any targets allocated to said allocation "
        "will be released")
    commonl.argparser_add_aka(arg_subparsers, "alloc-rm", "alloc-del")
    commonl.argparser_add_aka(arg_subparsers, "alloc-rm", "alloc-delete")
    ap.add_argument(
        "-u", "--username", action = "store", default = None,
        help = "Remove allocations by user")
    ap.add_argument(
        "-s", "--self", action = "store_const", dest = "username",
        const = "self",
        help = "Remove allocations by the logged in user")
    ap.add_argument(
        "allocid", metavar = "[SERVER/]ALLOCATIONID", nargs = "*",
        action = "store", default = [],
        help = "Allocation IDs to remove")
    ap.set_defaults(func = _cmdline_alloc_delete)

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
        "guest-ls",
        help = "list guests in an allocation")
    ap.add_argument(
        "allocid", metavar = "[SERVER/]ALLOCATIONID",
        action = "store", default = None,
        help = "Allocation IDs to which to add guest to")
    ap.set_defaults(func = _cmdline_guest_list)

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
