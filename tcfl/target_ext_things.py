#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""Plug or unplug things to/from a target
--------------------------------------

This module implements the client side API for controlling the things
that can be plugged/unplugged to/from a target.
"""

from . import tc
from . import msgid_c

class extension(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to interact with the
    server's thing conrol interface

    Use as:

    >>> target.things.plug()
    >>> target.things.unplug()
    >>> target.things.get()
    >>> target.things.list()

    """

    def __init__(self, target):
        if 'things' not in target.rt.get('interfaces', []):
            raise self.unneeded
        tc.target_extension_c.__init__(self, target)

    def get(self, thing):
        """
        :returns: *True* if *thing* is connected, *False* otherwise
        """
        r = self.target.ttbd_iface_call("things", "get", method = "GET",
                                        thing = thing)
        return r['result']

    def list(self):
        """
        Return a list of a target's things and their state

        :returns: dictionary keyed by thing name number and their state
          (*True* if plugged, *False* if not, *None* if the
          target/thing are not acquired and thus state information is
          not available.
        """
        self.target.report_info("listing", dlevel = 1)
        r = self.target.ttbd_iface_call("things", "list", method = "GET")
        self.target.report_info("listed")
        return r

    def plug(self, thing):
        """
        Plug a thing into the target

        :param str thing: name of the thing to plug
        """
        assert isinstance(thing, str)
        self.target.report_info("plugging", dlevel = 1)
        self.target.ttbd_iface_call("things", "plug", thing = thing)
        self.target.report_info("plugged")

    def unplug(self, thing):
        """
        Unplug a thing from the target

        :param str thing: name of the thing to unplug
        """
        assert isinstance(thing, str)
        self.target.report_info("unplugging", dlevel = 1)
        self.target.ttbd_iface_call("things", "unplug", thing = thing)
        self.target.report_info("unplugged")


def _cmdline_things_plug(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "things")
        target.things.plug(args.thing)

def _cmdline_things_unplug(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "things")
        target.things.unplug(args.thing)

def _cmdline_things_get(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "things")
        r = target.things.get(args.thing)
        print("%s: %s" % (target.id, 'plugged' if r == True else 'unplugged'))

def _cmdline_things_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "things")
        r = target.things.list()
        for thing, state in r['result'].items():
            if state == True:
                _state = 'plugged'
            elif state == False:
                _state = 'unplugged'
            elif state == None:
                _state = "n/a (need to acquire targets)"
            else:
                _state = "BUG:unknown-state"
            print("%s: %s" % (thing, _state))


def _cmdline_setup(arg_subparsers):
    ap = arg_subparsers.add_parser("thing-plug",
                                   help = "Plug a thing to the target")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name")
    ap.add_argument("thing", metavar = "THING", action = "store",
                    default = None, help = "Name of thing to plug")
    ap.set_defaults(func = _cmdline_things_plug)

    ap = arg_subparsers.add_parser("thing-unplug",
                                   help = "Unplug a thing from the target")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name")
    ap.add_argument("thing", metavar = "THING", action = "store",
                    default = None, help = "Name of thing to unplug")
    ap.set_defaults(func = _cmdline_things_unplug)

    ap = arg_subparsers.add_parser("thing-get",
                                   help = "Return current thing's state")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name")
    ap.add_argument("thing", metavar = "THING", action = "store",
                    default = None,
                    help = "Name of thing to query state about")
    ap.set_defaults(func = _cmdline_things_unplug)

    ap = arg_subparsers.add_parser("thing-list",
                                   help = "List plugged and unplugged things")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name")
    ap.set_defaults(func = _cmdline_things_list)
