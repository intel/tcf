#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""

"""
import bisect
import collections
import json
import logging
import pprint
import sys
import time

import requests
import requests.exceptions
import tabulate

import commonl
import tc
import ttb_client
from . import msgid_c

import asciimatics.widgets
import asciimatics.event
import asciimatics.scene


def _delete(rtb, allocationid):
    try:
        rtb.send_request("DELETE", "allocation/%s" % allocationid)
    except requests.HTTPError as e:
        if 'invalid allocation' not in str(e):
            raise
        # FIXME: HACK: this means invalid allocation,
        # already wiped



def _cmdline_alloc_targets(args):
    with msgid_c("cmdline"):
        targetl = ttb_client.cmdline_list(args.target, args.all)
        targets = set()
        rtbs = set()

        # to use fullid, need to tweak the refresh code to add the aka part
        for rt in sorted(targetl, key = lambda x: x['fullid']):
            targets.add(rt['id'])
            rtbs.add(rt['rtb'])

        if len(rtbs) > 1:
            logging.error("Targets span more than one server")
            sys.exit(1)
        rtb = list(rtbs)[0]

        data = dict(
            priority = args.priority,
            preempt = args.preempt,
            queue = args.queue,
            groups = {},
        )
        if args.obo:
            data['obo_user'] = args.obo
        data['groups']['group'] = list(targets)
        r = rtb.send_request("PUT", "allocation", json = data)

        ts0 = time.time()
        state = r['state']
        if state not in ( 'queued', 'active'):
            raise RuntimeError(
                "allocation failed: %s: %s"
                % (state, r.get('message', 'message n/a')))
        allocid = r['allocationid']
        data = { allocid: state }
        if state == 'active':			# got it
            print "allocation ID %s: allocated: %s" % (
                allocid, r['allocated_group'])
        else:					# queue, keepalive in there
            while True:
                time.sleep(5)
                ts = time.time()
                r = rtb.send_request("PUT", "keepalive", json = data)
                print "allocation ID %s: [+%.1fs] keepalive while waiting: %s\r" % (
                    allocid, ts - ts0, r),
                sys.stdout.flush()
                if allocid not in r['result']:
                    continue # no news
                alloc = r['result'][allocid]
                new_state = alloc['state']
                if new_state == 'active':
                    print "\nallocation ID %s: [+%.1fs] allocated: %s" % (
                        allocid, ts - ts0, alloc['allocated_group'])
                    break
                elif new_state == 'invalid':
                    print "\nallocation ID %s: [+%.1fs] now invalid" % (
                        allocid, ts - ts0)
                    break
                print "\nallocation ID %s: [+%.1fs] state transition %s -> %s" % (
                    allocid, ts - ts0, state, new_state)
                data[allocid] = new_state

        if args.hold != None:
            try:
                ts_active = time.time()
                while True:
                    time.sleep(5)
                    ts = time.time()
                    if args.hold > 0 and ts - ts_active > args.hold:
                        # maximum hold time reached, release it
                        break
                    r = rtb.send_request("PUT", "keepalive", json = data)
                    print "allocation ID %s: [+%.1fs] keepalive while owned: %s\r" % (
                        allocid, ts - ts0, r),
                    sys.stdout.flush()
                    alloc = r['result'].get(allocid, None)
                    if alloc == None:
                        continue			# no new info
                    new_state = alloc['state']
                    if new_state not in ( 'active', 'queued', 'restart-needed' ):
                        print
                        break
                    if new_state != data[allocid]:
                        print "\nallocation ID %s: [+%.1fs] state transition %s -> %s" % (
                            allocid, ts - ts0, state, new_state)
                        data[allocid] = new_state
            except KeyboardInterrupt:
                print "\nallocation ID %s: [+%.1fs] releasing due to user interruption" % (
                    allocid, ts - ts0)
            finally:
                _delete(rtb, allocid)

class _model_c(object):

    def __init__(self, servers, targets):
        self.targets = targets
        self.servers = servers
        self.max_waiters = 30

    def get_content(self):

        for rtb in self.servers:
            try:
                # FIXME: list only for a given set of targets
                r = rtb.send_request(
                    "GET", "targets/",
                    data = {
                        'projection': json.dumps([ "_alloc*" ])
                    })
                #print >> sys.stderr, "DEBUG refreshed", rtb, pprint.pformat(r)
                # update our knowledge of the target
                for rt in r.get('targets', []):
                    target_name = rt.get('id', None)
                    if target_name == None:
                        continue
                    if target_name not in self.targets:
                        # FIXME: use fullid instead
                        # FIXME: use rtb to compare too
                        continue
                    #print >> sys.stderr, "DEBUG", target_name, rt
                    self.targets[target_name].rt = rt
            except requests.exceptions.RequestException as e:
                print >> sys.stderr, "Error %s" % type(e)
                continue

        # return the content per rows
        l = []
        count = 0
        for target in self.targets.values():
            ## "_alloc_queue": [
            ##     {
            ##         "allocationid": "PMAbeM",
            ##         "exclusive": true,
            ##         "preempt": false,
            ##         "priority": 50000,
            ##         "timestamp": 20200305204652
            ##     },
            ##     {
            ##         "allocationid": "1KeyqK",
            ##         "exclusive": true,
            ##         "preempt": false,
            ##         "priority": 50000,
            ##         "timestamp": 20200305204654
            ##     }
            ## ],
            waiter_count = 0
            #print >> sys.stderr, "DEBUG target %s" % target.id, target.rt
            # ( prio, timestamp, allocationid, preempt, exclusive)
            waiterl = []
            queue = target.rt.get('_alloc', {}).get('queue', {})
            for allocid, waiter in queue.iteritems():
                if waiter_count > self.max_waiters:
                    break
                waiter_count += 1
                bisect.insort(waiterl, (
                    waiter['priority'],
                    waiter['timestamp'],
                    allocid,
                    waiter['preempt'],
                    waiter['exclusive'],
                ))
            row = [ target.id ]
            for waiter in waiterl:
                row.append("%06d:%s" % (waiter[0], waiter[2]))
            l.append(( row, count ))
            count += 1
        return l

    def get_column_widths(self):
        return [ 14 ] * self.max_waiters


class _view_c(asciimatics.widgets.Frame):
    # cannibalized top.py and contact_list.py from asciimatics's
    # samples to make this -- very helpful
    def __init__(self, screen, model):
        asciimatics.widgets.Frame.__init__(
            self, screen, screen.height, screen.width,
            hover_focus = True, has_border = True,
            can_scroll = True)
        self.model = model
        self.last_frame = 0

        layout = asciimatics.widgets.Layout([100], fill_frame=True)
        self.add_layout(layout)
        # Create the form for displaying the list of contacts.
        self.list_box = asciimatics.widgets.MultiColumnListBox(
            asciimatics.widgets.Widget.FILL_FRAME,
            model.get_column_widths(),
            model.get_content(),
            name = "Targets",
            add_scroll_bar = True)        
        layout.add_widget(self.list_box)
        self.fix()

    def process_event(self, event):
        if isinstance(event, asciimatics.event.KeyboardEvent):
            # key handling for this: Ctrl-C, q/Q to quit, r refresh
            if event.key_code in [
                    ord('q'),
                    ord('Q'),
                    asciimatics.screen.Screen.KEY_ESCAPE,
                    asciimatics.screen.Screen.ctrl("c")
            ]:
                raise asciimatics.exceptions.StopApplication("User quit")
            elif event.key_code in [ ord("r"), ord("R") ]:
                pass
            self.last_frame = 0	# force a refresh
        return asciimatics.widgets.Frame.process_event(self, event)
        
    @property
    def frame_update_count(self):
        return 10	        # Refresh once every .5 seconds by default.

    def _update(self, frame_no):
        if self.last_frame == 0 \
           or frame_no - self.last_frame >= self.frame_update_count:
            self.list_box.options = self.model.get_content()
            self.list_box.value = frame_no
            self.last_frame = frame_no
        asciimatics.widgets.Frame._update(self, frame_no)



def _cmdline_alloc_monitor(args):
    with msgid_c("cmdline"):
        servers = set()
        targetl = ttb_client.cmdline_list(args.target, args.all)
        targets = collections.OrderedDict()

        # to use fullid, need to tweak the refresh code to add the aka part
        for rt in sorted(targetl, key = lambda x: x['id']):
            target_name = rt['id']
            targets[target_name] = \
                tc.target_c.create_from_cmdline_args(args, target_name)
            servers.add(targets[target_name].rtb)
        model = _model_c(servers, targets)

        def _run_alloc_monitor(screen, scene):
            scenes = [
                asciimatics.scene.Scene([ _view_c(screen, model) ],
                                        -1, name = "Main"),
            ]
            
            screen.play(scenes,
                        stop_on_resize = True, start_scene = scene,
                        allow_int = True)

        last_scene = None
        while True:
            try:
                asciimatics.screen.Screen.wrapper(_run_alloc_monitor,
                                                  catch_interrupt = True,
                                                  arguments = [ last_scene ])
                sys.exit(0)
            except asciimatics.exceptions.ResizeScreenError as e:
                last_scene = e.scene



def _cmdline_alloc_ls(args):
    with msgid_c("cmdline"):
        targetl = ttb_client.cmdline_list(args.target, args.all)
        targets = collections.OrderedDict()

        # to use fullid, need to tweak the refresh code to add the aka part
        for rt in sorted(targetl, key = lambda x: x['fullid']):
            target_name = rt['fullid']
            targets[target_name] = \
                tc.target_c.create_from_cmdline_args(args, target_name)

        def _allocs_get(rtb):
            return rtb.send_request("GET", "allocation/")

        allocs = {}
        tp = ttb_client._multiprocessing_pool_c(
            processes = len(ttb_client.rest_target_brokers))
        threads = {}
        for rtb in sorted(ttb_client.rest_target_brokers.itervalues()):
            threads[rtb] = tp.apply_async(_allocs_get, (rtb,))
        tp.close()
        tp.join()
        for rtb, thread in threads.iteritems():
            allocs[rtb.aka] = thread.get()
        if args.verbosity == 3:
            pprint.pprint(allocs)
            return
        elif args.verbosity == 4:
            print json.dumps(allocs, skipkeys = True, indent = 4)
            return

        table = []
        for rtb, r in allocs.iteritems():
            for allocationid, data in r.iteritems():
                if args.verbosity == 0:
                    table.append([
                        allocationid,
                        data['state'],
                        data['creator'],
                        data['user'],
                        len(data.get('guests', [])),
                        len(data.get('target_group', []))
                    ])
                elif args.verbosity == 1:
                    tgs = []
                    for name, group in data.get('target_group', {}).iteritems():
                        tgs.append( name + ": " + ",".join(group))
                    table.append([
                        allocationid,
                        rtb,
                        data['state'],
                        data['timestamp'],
                        data['creator'],
                        data['user'],
                        "\n".join(data.get('guests', [])),
                        "\n".join(tgs),
                    ])
                elif args.verbosity == 2:
                    commonl.data_dump_recursive(data, allocationid,)
        if args.verbosity == 0:
            headers0 = [
                "AllocationID",
                "State",
                "Creator",
                "User",
                "#Guests",
                "#Groups"
            ]
            print(tabulate.tabulate(table, headers = headers0))
        if args.verbosity == 1:
            headers1 = [
                "AllocationID",
                "Server",
                "State",
                "Timestamp",
                "Creator",
                "User",
                "Guests",
                "Groups"
            ]
            print(tabulate.tabulate(table, headers = headers1))


def _cmdline_alloc_delete(args):
    with msgid_c("cmdline"):

        # we don't know which request is on which server, so we send
        # it to all the servers
        def _allocationid_delete(allocationid):

            try:
                rtb = None
                if '/' in allocationid:
                    server_aka, allocationid = allocationid.split('/', 1)
                    for rtb in ttb_client.rest_target_brokers.values():
                        if rtb.aka == server_aka:
                            rtb = rtb
                            _delete(rtb, allocationid)
                            return
                    else:
                        logging.error("%s: unknown server name", server_aka)
                        return
                # Unknown server, so let's try them all ... yeah,
                # collateral damage might happen--but then, you can
                # only delete yours
                for rtb in ttb_client.rest_target_brokers.values():
                    _delete(rtb, allocationid)
            except Exception as e:
                logging.exception("Exception: %s", e)

        tp = ttb_client._multiprocessing_pool_c(
            processes = len(args.allocationid))
        threads = {}
        for allocationid in args.allocationid:
            threads[allocationid] = tp.apply_async(_allocationid_delete,
                                                   (allocationid,))
        tp.close()
        tp.join()

def _rtb_allocationid_extract(allocationid):
    rtb = None
    if '/' in allocationid:
        server_aka, allocationid = allocationid.split('/', 1)
        for rtb in ttb_client.rest_target_brokers.values():
            if rtb.aka == server_aka:
                return rtb, allocationid
        logging.error("%s: unknown server name", server_aka)
        return None, allocationid
    return None, allocationid

def _guests_add(rtb, allocationid, guests):
    for guest in guests:
        try:
            rtb.send_request("PATCH", "allocation/%s/%s"
                             % (allocationid, guest))
        except requests.HTTPError as e:
            logging.warning("%s: can't add guest %s: %s",
                            allocationid, guest, e)


def _guests_list(rtb, allocationid):
    r = rtb.send_request("GET", "allocation/%s" % allocationid)
    print "\n".join(r.get('guests', []))

def _guests_remove(rtb, allocationid, guests):
    if not guests:
        # no guests given, remove'em all -- so list them first
        r = rtb.send_request("GET", "allocation/%s" % allocationid)
        guests = r.get('guests', [])
    for guest in guests:
        try:
            r = rtb.send_request("DELETE", "allocation/%s/%s"
                                 % (allocationid, guest))
        except requests.HTTPError as e:
            logging.error("%s: can't remove guest %s: %s",
                          allocationid, guest, e)


def _cmdline_guest_add(args):
    with msgid_c("cmdline"):
        rtb, allocationid = _rtb_allocationid_extract(args.allocationid)
        if rtb == None:
            # Unknown server, so let's try them all ... yeah,
            # collateral damage might happen--but then, you can
            # only delete yours
            for rtb in ttb_client.rest_target_brokers.values():
                _guests_add(rtb, allocationid, args.guests)
        else:
            _guests_add(rtb, allocationid, args.guests)



def _cmdline_guest_list(args):
    with msgid_c("cmdline"):
        rtb, allocationid = _rtb_allocationid_extract(args.allocationid)
        if rtb == None:
            # Unknown server, so let's try them all ... yeah,
            # collateral damage might happen--but then, you can
            # only delete yours
            for rtb in ttb_client.rest_target_brokers.values():
                _guests_list(rtb, allocationid)
        else:
            _guests_list(rtb, allocationid)



def _cmdline_guest_remove(args):
    with msgid_c("cmdline"):
        rtb, allocationid = _rtb_allocationid_extract(args.allocationid)
        if rtb == None:
            # Unknown server, so let's try them all ... yeah,
            # collateral damage might happen--but then, you can
            # only delete yours
            for rtb in ttb_client.rest_target_brokers.values():
                _guests_remove(rtb, allocationid, args.guests)
        else:
            _guests_remove(rtb, allocationid, args.guests)


def _cmdline_setup(arg_subparsers):
    ap = arg_subparsers.add_parser(
        "alloc-targets",
        help = "FIXME")
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "Consider also disabled targets")
    ap.add_argument(
        "-d", "--hold", action = "store",
        nargs = "?", type = int, const = 0, default = None,
        help = "Keep the reservation alive for this many seconds"
        " (default for ever)")
    ap.add_argument(
        "-u", "--duration", action = "store", type = int, default = 0,
        help = "Keep the reservation alive for this seconds,"
        " then release it")
    ap.add_argument(
        "-w", "--wait", action = "store_true", dest = 'queue', default = True,
        help = "(default) Wait until targets are assigned")
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
        "alloc-monitor",
        help = "FIXME")
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "Consider also disabled targets")
    ap.add_argument(
        "target", metavar = "TARGETSPEC", nargs = "*",
        action = "store", default = None,
        help = "Target's names or a general target specification "
        "which might include values of tags, etc, in single quotes (eg: "
        "'zephyr_board and not type:\"^qemu.*\"'")
    ap.set_defaults(func = _cmdline_alloc_monitor)

    ap = arg_subparsers.add_parser(
        "alloc-ls",
        help = "List information about current allocations "
        "in all the servers or the servers where the named "
        "targets are")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Increase verbosity of information to display "
        "(none is a table, -v table with more details, "
        "-vv hierarchical, -vvv Python format, -vvvv JSON format)")
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "Consider also disabled targets")
    ap.add_argument(
        "target", metavar = "TARGETSPEC", nargs = "*",
        action = "store", default = None,
        help = "Target's names or a general target specification "
        "which might include values of tags, etc, in single quotes (eg: "
        "'zephyr_board and not type:\"^qemu.*\"'")
    ap.set_defaults(func = _cmdline_alloc_ls)

    ap = arg_subparsers.add_parser(
        "alloc-delete",
        help = "Delete an existing allocation (which might be "
        "in any state; any targets allocated to said allocation "
        "will be released")
    ap.add_argument(
        "allocationid", metavar = "[SERVER/]ALLOCATIONID", nargs = "+",
        action = "store", default = None,
        help = "Allocation IDs to remove")
    ap.set_defaults(func = _cmdline_alloc_delete)

    ap = arg_subparsers.add_parser(
        "guest-add",
        help = "Add a guest to an allocation")
    ap.add_argument(
        "allocationid", metavar = "[SERVER/]ALLOCATIONID",
        action = "store", default = None,
        help = "Allocation IDs to which to add guest to")
    ap.add_argument(
        "guests", metavar = "USERNAME", nargs = "+",
        action = "store", default = None,
        help = "Name of guest to add")
    ap.set_defaults(func = _cmdline_guest_add)

    ap = arg_subparsers.add_parser(
        "guest-list",
        help = "list guests in an allocation")
    ap.add_argument(
        "allocationid", metavar = "[SERVER/]ALLOCATIONID",
        action = "store", default = None,
        help = "Allocation IDs to which to add guest to")
    ap.set_defaults(func = _cmdline_guest_list)

    ap = arg_subparsers.add_parser(
        "guest-remove",
        help = "Remove a guest from an allocation")
    ap.add_argument(
        "allocationid", metavar = "[SERVER/]ALLOCATIONID",
        action = "store", default = None,
        help = "Allocation IDs to which to add guest to")
    ap.add_argument(
        "guests", metavar = "USERNAME", nargs = "*",
        action = "store", default = None,
        help = "Name of guest to remove (all if none given)")
    ap.set_defaults(func = _cmdline_guest_remove)
