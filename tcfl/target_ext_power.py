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

import collections
import json

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

        A more detailed picture of the target's power state can be
        obtained with :meth:list.
        """
        state, _, _ = self.list()
        return state

    def list(self):
        """
        Return a list of a target's power rail components and their status

        :returns tuple(state, substate, data):

          - state: *True* on, *False* off, *None* not available
          - substate: "normal", "full", "inconsistent"; if
            inconsistent, it would be a good idea to power cycle
          - data: dictionary keyed by
            component name listing their state and other flags about
            them:

            .. code-block:: python

               {
                   "NAME1": {
                       "state": STATE1,
                       ["explicit": "on|off|both" ]
                   },
                   "NAME2": {
                       "state": STATE2,
                       ["explicit": "on|off|both" ]
                   },
                   ...
               }

            - *state*: *True* if powered, *False* if not, *None* if not
               applicable, for fake power controls

            - *explicit*: (see :ref:`ttbd_power_explicit`) if missing,
               not explicit, will be turned on/off normally:

              - *on*: only powered on if explicitly named

              - *off*: only powered off if explicitly named

              - *both*: only powered on/off if explicitly named

        """
        self.target.report_info("listing", dlevel = 1)
        r = self.target.ttbd_iface_call(
            "power", "list", method = "GET",
            # extra time, since power ops can take long
            timeout = 60)
        if 'power' in r:
            data = collections.OrderedDict()
            # backwards compat
            #
            ## [
            ##   [ NAME1, STATE2 ],
            ##   [ NAME2, STATE2 ],
            ##   ...
            ## ]
            #
            for i in r.get('power', []):
                data[i[0]] = dict(state = i[1])
            substate = 'normal' # older doesn't support substates
            state = all(i['state'] in (True, None) for i in data.values())
        elif isinstance(r, collections.Mapping):
            # proper response format
            #
            ## {
            ##   NAME1: { state: STATE1, [explicit: "on|off|both" ] },
            ##   NAME2: { state: STATE2, [explicit: "on|off|both" ] },
            ##   ...
            ## }
            #
            # FIXME: verify the format
            state = r['state']
            substate = r['substate']
            data = r['components']
        else:
            raise AssertionError("can't parse response")
        self.target.report_info("listed")
        return state, substate, data

    def off(self, component = None, explicit = False):
        """
        Power off a target or parts of its power rail

        :param str component: (optional) name of component to
          power off, defaults to whole target's power rail
        """
        assert component == None or isinstance(component, basestring)
        assert isinstance(explicit, bool)
        self.target.report_info("powering off", dlevel = 1)
        self.target.ttbd_iface_call(
            "power", "off", component = component, explicit = explicit,
            # extra time, since power ops can take long
            timeout = 60)
        self.target.report_info("powered off")

    def on(self, component = None, explicit = False):
        """
        Power on a target or parts of its power rail

        :param str component: (optional) name of component to
          power on, defaults to whole target's power rail
        """
        assert component == None or isinstance(component, basestring)
        assert isinstance(explicit, bool)
        self.target.report_info("powering on", dlevel = 1)
        self.target.ttbd_iface_call(
            "power", "on", component = component, explicit = explicit,
            # extra time, since power ops can take long
            timeout = 60)
        self.target.report_info("powered on")
        if hasattr(self.target, "console"):
            self.target.console._set_default()

    def cycle(self, wait = None, component = None, explicit = False):
        """
        Power cycle a target or one of its components

        :param float wait: (optional) seconds to wait before powering on
        :param str component: (optional) name of component to
          power-cycle, defaults to whole target's power rail
        """
        assert wait == None or wait >= 0
        assert component == None or isinstance(component, basestring)
        assert isinstance(explicit, bool)
        self.target.report_info("power cycling", dlevel = 1)
        self.target.ttbd_iface_call(
            "power", "cycle",
            component = component, wait = wait, explicit = explicit,
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
            target.power.off(args.component, explicit = args.explicit)

def _cmdline_power_on(args):
    with msgid_c("cmdline"):
        for target_name in args.targets:
            target = tc.target_c.create_from_cmdline_args(args, target_name)
            target.power.on(args.component, explicit = args.explicit)

def _cmdline_power_cycle(args):
    with msgid_c("cmdline"):
        for target_name in args.targets:
            target = tc.target_c.create_from_cmdline_args(args, target_name)
            target.power.cycle(
                wait = float(args.wait),
                component = args.component, explicit = args.explicit)

def _cmdline_power_reset(args):
    with msgid_c("cmdline"):
        for target_name in args.targets:
            target = tc.target_c.create_from_cmdline_args(args, target_name)
            target.power.reset()

def _cmdline_power_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        state, substate, components = target.power.list()

        def _state_to_str(state):
            if state == True:
                return 'on'
            if state == False:
                return 'off'
            if state == None:
                return "n/a"
            return "BUG:unknown-state"

        if args.verbosity < 2:
            _state = _state_to_str(state)
            print "overall: %s (%s)" % (_state, substate)
            for component, data in components.iteritems():
                state = data['state']
                explicit = data.get('explicit', None)
                _state = _state_to_str(state)
                if explicit and args.verbosity == 0:
                    continue
                if not explicit:
                    explicit = ""
                else:
                    explicit = " (explicit/" + explicit + ")"
                print "  %s: %s%s" % (component, _state, explicit)

        else:  # args.verbosity >= 2:
            print json.dumps(r, skipkeys = True, indent = 4)

def _cmdline_power_get(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        r = target.power.get()
        print "%s: %s" % (target.id, 'on' if r == True else 'off')



def _cmdline_setup(arg_subparser):
    ap = arg_subparser.add_parser(
        "power-on",
        help = "Power on target's power rail (or individual components)")
    ap.add_argument(
        "--component", "-c",
        metavar = "COMPONENT", action = "store", default = None,
        help = "Operate only on the given component of the power rail")
    ap.add_argument(
        "--explicit", "-e",
        action = "store_true", default = False,
        help = "Operate also on all the explicit components; "
        " explicit components are only powered on if"
        " --explicit is given or if they are explicitly selected"
        " with --component")
    ap.add_argument(
        "targets",
        metavar = "TARGET", action = "store", nargs = "+", default = None,
        help = "Names of targets to power on")
    ap.set_defaults(func = _cmdline_power_on)

    ap = arg_subparser.add_parser(
        "power-off",
        help = "Power off target's power rail (or individual components)")
    ap.add_argument(
        "--component", "-c", metavar = "COMPONENT",
        action = "store", default = None,
        help = "Operate only on the given component of the power rail")
    ap.add_argument(
        "--explicit", "-e",
        action = "store_true", default = False,
        help = "Operate also on all the explicit components; "
        " explicit components are only powered off if"
        " --explicit is given or if they are explicitly selected"
        " with --component")
    ap.add_argument(
        "targets",
        metavar = "TARGET", action = "store", nargs = "+", default = None,
        help = "Names of targets to power off")
    ap.set_defaults(func = _cmdline_power_off)

    ap = arg_subparser.add_parser(
        "power-cycle",
        help = "Power cycle target's power rail (or individual components)")
    ap.add_argument(
        "--explicit", "-e",
        action = "store_true", default = False,
        help = "Operate also on all the explicit components;  explicit"
        " components are only power cycled if --explicit is given or"
        " if they are explicitly selected with --component")
    ap.add_argument(
        "-w", "--wait",
        metavar = "SECONDS", action = "store", default = 0,
        help = "How long to wait between power off and power on")
    ap.add_argument(
        "--component", "-c", metavar = "COMPONENT",
        action = "store", default = None,
        help = "Operate only on the given component of the power rail")
    ap.add_argument(
        "targets",
        metavar = "TARGET", action = "store", nargs = "+", default = None,
        help = "Names of targets to power cycle")
    ap.set_defaults(func = _cmdline_power_cycle)

    ap = arg_subparser.add_parser(
        "power-ls",
        help = "List power rail components and their state")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Increase verbosity of information to display "
        "(default displays state of non-explicit components,"
        " -v adds component flags and lists explicit components,"
        " -vv python dictionary, -vvv JSON format)")
    ap.add_argument(
        "target", metavar = "TARGET", action = "store", default = None,
        help = "Name of target")
    ap.set_defaults(func = _cmdline_power_list)

    ap = arg_subparser.add_parser(
        "power-get",
        help = "Print target's power state."
        "A target is considered *on* when all of its power rail"
        "components are on; fake power components report power state as"
        "*n/a* and those are not taken into account.")
    ap.add_argument(
        "target",
        metavar = "TARGET", action = "store", default = None,
        help = "Target")
    ap.set_defaults(func = _cmdline_power_get)
