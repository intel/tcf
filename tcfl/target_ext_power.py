#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Power on or off the target or any its power rail components
-----------------------------------------------------------

This module implements the client side API for controlling the power's
target as well as the hooks to access these interfaces from the
command line.
"""

import tc
from . import msgid_c


class extension(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to interact with the
    server's power control interface.

    Use as:

    >>> target.power.on()
    >>> target.power.off()
    >>> target.power.cycle()
    >>> target.power.get()
    >>> target.power.list()
    """

    def __init__(self, target):
        if 'power' in target.rt.get('interfaces', []):
            return
        raise self.unneeded

    def get(self):
        """
        Return a target's power status, *True* if powered, *False*
        otherwise.

        A target is considered *on* when all of its power rail
        components are on; fake power components report power state as
        *None* and those are not taken into account.
        """
        r = self.target.ttbd_iface_call(
            "power", "get", method = "GET",
            # extra time, since power ops can take long
            timeout = 60)
        return r['result']

    def list(self):
        """
        Return a list of a target's power rail components and their status

        :returns: dictionary keyed by component number and their state
          (*True* if powered, *False* if not, *None* if not
          applicable, for fake power controls)
        """
        self.target.report_info("listing", dlevel = 1)
        r = self.target.ttbd_iface_call(
            "power", "list", method = "GET",
            # extra time, since power ops can take long
            timeout = 60)
        self.target.report_info("listed")
        return r.get('power', [])

    def off(self, component = None):
        """
        Power off a target or parts of its power rail

        :param str component: (optional) name of component to
          power off, defaults to whole target's power rail
        """
        assert component == None or isinstance(component, basestring)
        self.target.report_info("powering off", dlevel = 1)
        self.target.ttbd_iface_call(
            "power", "off", component = component,
            # extra time, since power ops can take long
            timeout = 60)
        self.target.report_info("powered off")

    def on(self, component = None):
        """
        Power on a target or parts of its power rail

        :param str component: (optional) name of component to
          power on, defaults to whole target's power rail
        """
        assert component == None or isinstance(component, basestring)
        self.target.report_info("powering on", dlevel = 1)
        self.target.ttbd_iface_call(
            "power", "on", component = component,
            # extra time, since power ops can take long
            timeout = 60)
        self.target.report_info("powered on")
        if hasattr(self.target, "console"):
            self.target.console._set_default()

    def cycle(self, wait = None, component = None):
        """
        Power cycle a target or one of its components

        :param float wait: (optional) seconds to wait before powering on
        :param str component: (optional) name of component to
          power-cycle, defaults to whole target's power rail
        """
        assert wait == None or wait >= 0
        assert component == None or isinstance(component, basestring)
        self.target.report_info("power cycling", dlevel = 1)
        self.target.ttbd_iface_call(
            "power", "cycle",
            component = component, wait = wait,
            # extra time, since power ops can take long
            timeout = 60)
        self.target.report_info("power cycled")
        if hasattr(self.target, "console"):
            self.target.console._set_default()

    def reset(self):
        """
        Reset a target

        This interface is **deprecated**.
        """
        self.target.report_info("resetting", dlevel = 1)
        self.target.report_info("DEPRECATED: reset()", level = 0)
        # reset is deprecated at the server level
        self.target.ttbd_iface_call(
            "power", "cycle",
            # extra time, since power ops can take long
            timeout = 60)
        self.target.report_info("reset")
        if hasattr(self.target, "console"):
            self.target.console._set_default()

    def _healthcheck(self):
        target = self.target
        print "Powering off"
        target.power.off()
        print "Powered off"

        print "Querying power status"
        power = target.power.get()
        if power != False:
            msg = "Power should be False, reported %s" % power
            raise Exception(msg)
        print "Power is reported correctly as %s" % power

        print "Powering on"
        target.power.on()
        print "Powered on"

        print "Querying power status"
        power = target.power.get()
        if power != True:
            msg = "Power should be True, reported %s" % power
            raise Exception(msg)
        print "Power is reported correctly as %s" % power

        print "Power cycling"
        target.power.cycle()
        print "Power cycled"

        print "Power conmponents: listing"
        try:
            components = target.power.list()
        except RuntimeError as e:
            print "Power components: not supported"
        else:
            print "Power components: listed %s" \
                % " ".join("%s:%s" % (k, v) for k, v in components)

        print "Querying power status"
        power = target.power.get()
        if power != True:
            msg = "Power should be True, reported %s" % power
            raise Exception(msg)
        print "Power is reported correctly as %s" % power

        print "Powering off"
        target.power.off()
        print "Powered off"

        print "Querying power status"
        power = target.power.get()
        if power != False:
            msg = "Power should be False, reported %s" % power
            raise Exception(msg)
        print "Power is reported correctly as %s" % power
        print "Power test passed"


def _cmdline_power_off(args):
    with msgid_c("cmdline"):
        for target_name in args.targets:
            target = tc.target_c.create_from_cmdline_args(args, target_name)
            target.power.off(args.component)

def _cmdline_power_on(args):
    with msgid_c("cmdline"):
        for target_name in args.targets:
            target = tc.target_c.create_from_cmdline_args(args, target_name)
            target.power.on(args.component)

def _cmdline_power_cycle(args):
    with msgid_c("cmdline"):
        for target_name in args.targets:
            target = tc.target_c.create_from_cmdline_args(args, target_name)
            target.power.cycle(wait = float(args.wait),
                               component = args.component)

def _cmdline_power_reset(args):
    with msgid_c("cmdline"):
        for target_name in args.targets:
            target = tc.target_c.create_from_cmdline_args(args, target_name)
            target.power.reset()

def _cmdline_power_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        r = target.power.list()
        for component, state in r:
            if state == True:
                _state = 'on'
            elif state == False:
                _state = 'off'
            elif state == None:
                _state = "n/a"
            else:
                _state = "BUG:unknown-state"
            print "%s: %s" % (component, _state)

def _cmdline_power_get(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        r = target.power.get()
        print "%s: %s" % (target.id, 'on' if r == True else 'off')



def _cmdline_setup(arg_subparser):
    ap = arg_subparser.add_parser("power-on", help = "Power target on")
    ap.add_argument("--component", "-c", metavar = "COMPONENT",
                    action = "store", default = None,
                    help = "Operate only on the given component of the "
                    "power rail")
    ap.add_argument("targets", metavar = "TARGET", action = "store",
                    nargs = "+", default = None,
                    help = "Target names")
    ap.set_defaults(func = _cmdline_power_on)

    ap = arg_subparser.add_parser("power-off", help = "Power target off")
    ap.add_argument("--component", "-c", metavar = "COMPONENT",
                    action = "store", default = None,
                    help = "Operate only on the given component of the "
                    "power rail")
    ap.add_argument("targets", metavar = "TARGET", action = "store",
                    nargs = "+", default = None,
                    help = "Target names")
    ap.set_defaults(func = _cmdline_power_off)

    ap = arg_subparser.add_parser("power-cycle",
                                  help = "Power cycle target (off, then on)")
    ap.add_argument(
        "-w", "--wait", metavar = "SECONDS", action = "store",
        default = 0, help = "How long to wait between power "
        "off and power on")
    ap.add_argument("--component", "-c", metavar = "COMPONENT",
                    action = "store", default = None,
                    help = "Operate only on the given component of the "
                    "power rail")
    ap.add_argument("targets", metavar = "TARGET", action = "store",
                    nargs = "+", default = None,
                    help = "Target names")
    ap.set_defaults(func = _cmdline_power_cycle)

    ap = arg_subparser.add_parser("power-ls",
                                  help = "List power rail components and "
                                  "their state")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's")
    ap.set_defaults(func = _cmdline_power_list)

    ap = arg_subparser.add_parser(
        "power-get",
        help = "print target's power state."
        " A target is considered *on* when all of its power rail"
        " components are on; fake power components report power state as"
        " *n/a* and those are not taken into account."
    )
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target")
    ap.set_defaults(func = _cmdline_power_get)
