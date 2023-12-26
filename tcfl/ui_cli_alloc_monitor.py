#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Alloc utilities that are UI specific and need extra dependencies, we
only import if we use
"""
import argparse
import bisect
import collections
import logging
import json
import sys

import requests
import requests.exceptions

import tcfl.tc
import tcfl.ttb_client
import tcfl.ui_cli
from . import msgid_c

logger = logging.getLogger("alloc-monitor")

def _cmdline_alloc_monitor(cli_args: argparse.Namespace):

    try:
        # yup, import here so we only do it if we need it. Lots of
        # stuff we don't need otherwise
        import asciimatics.widgets
        import asciimatics.event
        import asciimatics.scene
    except ImportError as e:
        raise RuntimeError(
            "asciimatics package needs to be installed for this feature; "
            "run 'pip install --user asciimatics' or equivalent") from e
    
    class _view_c(asciimatics.widgets.Frame):
        # cannibalized top.py and contact_list.py from asciimatics's
        # samples to make this -- very helpful
        # DEFINED inside the function (ugly) because it depends on
        # things we import only if we decide we have to do it
        def __init__(self, screen, model):
            asciimatics.widgets.Frame.__init__(
                self, screen, screen.height, screen.width,
                hover_focus = True, has_border = True,
                can_scroll = True)
            self.model = model
            self.last_frame = 0

            layout = asciimatics.widgets.Layout([100], fill_frame = True)
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


    class _model_c:

        def __init__(self, targets):
            self.targets = targets
            self.max_waiters = 30

        def get_content(self):

            for server_url, server in tcfl.server_c.servers.items():
                try:
                    # FIXME: list only for a given set of targets
                    r = server.send_request(
                        "GET", "targets/",
                        data = {
                            'projection': json.dumps([ "_alloc*" ])
                        })
                    #print >> sys.stderr, "DEBUG refreshed", server, pprint.pformat(r)
                    # update our knowledge of the target
                    for rt in r.get('targets', []):
                        target_name = rt.get('id', None)
                        if target_name == None:
                            continue
                        if target_name not in self.targets:
                            # FIXME: use fullid instead
                            # FIXME: use server to compare too
                            continue
                        #print >> sys.stderr, "DEBUG", target_name, rt
                        self.targets[target_name].rt = rt
                except requests.exceptions.RequestException as _e:
                    # FIXME: set status bar "LOST CONNECTION"
                    continue

            # return the content per rows
            l = []
            count = 0
            for target in self.targets.values():
                ## "_alloc_queue": [
                ##     {
                ##         "allocid": "PMAbeM",
                ##         "exclusive": true,
                ##         "preempt": false,
                ##         "priority": 50000,
                ##         "timestamp": 20200305204652
                ##     },
                ##     {
                ##         "allocid": "1KeyqK",
                ##         "exclusive": true,
                ##         "preempt": false,
                ##         "priority": 50000,
                ##         "timestamp": 20200305204654
                ##     }
                ## ],
                waiter_count = 0
                #print >> sys.stderr, "DEBUG target %s" % target.id, target.rt
                # ( prio, timestamp, allocid, preempt, exclusive)
                waiterl = []
                queue = target.rt.get('_alloc', {}).get('queue', {})
                for allocid, waiter in queue.items():
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


    with msgid_c("cmdline"):
        import tcfl.targets
        tcfl.targets.setup_by_spec(
            cli_args.target,
            verbosity = tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args),
            targets_all = cli_args.all)

        # to use fullid, need to tweak the refresh code to add the aka part
        targets = collections.OrderedDict()
        for targetid in tcfl.targets.discovery_agent.rts:
            targets[targetid] = tcfl.tc.target_c.create(
                targetid,
                target_discovery_agent = tcfl.targets.discovery_agent)

        # tcfl.server_c.servers is a dict keyed by URL
        model = _model_c(targets)

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


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser(
        "alloc-monitor",
        help = "Monitor the allocations current in the system")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_alloc_monitor)
