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

    Currently this interface supportd the legacy server interface
    (declared as *tt_power_control_mixin* in the target's *interface*
    tag and the new *power* interface).
    """

    def __init__(self, target):
        if 'power' in target.rt.get('interfaces', []):
            self.compat = False
            return
        if 'tt_power_control_mixin' in target.rt.get('interfaces', []):
            self.compat = True
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
        if self.compat:
            self.target.report_info("Getting power", dlevel = 1)
            r = self.target.rtb.rest_tb_target_power_get(self.target.rt)
            self.target.report_info("Got power")
            return r
        r = self.target.ttbd_iface_call("power", "get", method = "GET")
        return r['result']

    def list(self):
        """
        Return a list of a target's power rail components and their status

        :returns: dictionary keyed by component number and their state
          (*True* if powered, *False* if not, *None* if not
          applicable, for fake power controls)
        """
        if self.compat:
            raise RuntimeError("target does not support new power interface")
        self.target.report_info("listing", dlevel = 1)
        r = self.target.ttbd_iface_call("power", "list", method = "GET")
        self.target.report_info("listed")
        return r.get('power', [])

    def off(self, component = None):
        """
        Power off a target or parts of its power rail

        :param str component: (optional) name of component to
          power off, defaults to whole target's power rail
        """
        assert component == None or isinstance(component, basestring)
        if self.compat and component:
            raise RuntimeError("target does not support new power interface")
        self.target.report_info("powering off", dlevel = 1)
        if self.compat:
            self.target.rtb.rest_tb_target_power_off(
                self.target.rt, ticket = self.target.ticket)
        else:
            self.target.ttbd_iface_call("power", "off", component = component)
        self.target.report_info("powered off")

    def on(self, component = None):
        """
        Power on a target or parts of its power rail

        :param str component: (optional) name of component to
          power on, defaults to whole target's power rail
        """
        assert component == None or isinstance(component, basestring)
        if self.compat and component:
            raise RuntimeError("target does not support new power interface")
        self.target.report_info("powering on", dlevel = 1)
        if self.compat:
            self.target.rtb.rest_tb_target_power_on(
                self.target.rt, ticket = self.target.ticket)
        else:
            self.target.ttbd_iface_call("power", "on", component = component)
        if component == None and hasattr(self.target, 'console'):
            self.target.console._power_on_post()
            self.target.testcase.tls.expecter.power_on_post(self.target)
        self.target.report_info("powered on")

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
        if self.compat:
            self.target.rtb.rest_tb_target_power_cycle(
                self.target.rt, ticket = self.target.ticket, wait = wait)
        else:
            self.target.ttbd_iface_call("power", "cycle",
                                        component = component, wait = wait)
        if component == None and hasattr(self.target, 'console'):
            self.target.console._power_on_post()
            self.target.testcase.tls.expecter.power_on_post(self.target)
        self.target.report_info("power cycled")

    def reset(self):
        """
        Reset a target

        This interface is **deprecated**.
        """
        self.target.report_info("resetting", dlevel = 1)
        if self.compat:
            self.target.rtb.rest_tb_target_reset(
                self.target.rt, ticket = self.target.ticket)
            self.target.testcase.tls.expecter.power_on_post(self.target)
        else:
            self.target.report_info("DEPRECATED: reset()", level = 0)
            # reset is deprecated at the server level
            self.target.ttbd_iface_call("power", "cycle")
        self.target.report_info("reset")


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

    ap = arg_subparser.add_parser("power-list",
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
