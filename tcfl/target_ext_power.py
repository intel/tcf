#! /usr/bin/python3
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
import re

import commonl
import tcfl.ui_cli
from . import tc
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
        # FIXME: add component to make it faster when we only need one component
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
        self.target.report_info("listing", dlevel = 2)
        r = self.target.ttbd_iface_call(
            "power", "list", method = "GET",
            # extra time, since power ops can take long when having
            # complex power rails
            timeout = 90)
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
            state = all(i['state'] in (True, None) for i in list(data.values()))
        elif isinstance(r, collections.abc.Mapping):
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
        self.target.report_info("listed", dlevel = 2)
        return state, substate, data

    @staticmethod
    def _estimated_duration_get(data, operation):
        return data.get(
            'estimated_duration_%s' % operation,
            data.get('estimated_duration', 0))

    @staticmethod
    def _compute_duration(target, component, operation):
        timeout = 0
        if component:
            data = target.rt.get('interfaces', {})\
                            .get('power', {})\
                            .get(component, None)
            if data:
                timeout += extension._estimated_duration_get(data, operation)
        else:
            # collect all the timeouts from the different components
            # to get an estimate on what to wait
            for name, data in target.rt.get('interfaces', {})\
                                            .get('power', {})\
                                            .items():
                if isinstance(data, dict):
                    # components are dictionaries, the rest are not components
                    timeout += extension._estimated_duration_get(data, operation)
        return timeout

    def off(self, component = None, explicit = False):
        """
        Power off a target or parts of its power rail

        :param str component: (optional) name of component to
          power off, defaults to whole target's power rail
        """
        if component != None:
            assert isinstance(component, str)
            component_s = f" component {component}"
        else:
            component_s = ""
        assert isinstance(explicit, bool)
        target = self.target
        target.report_info("powering off" + component_s, dlevel = 1)
        # extra base time, since power ops can take long when having
        # complex power rails
        timeout = 90 + self._compute_duration(target, component, "off")
        if timeout > 120:            
            target.report_info(
                "WARNING: long power-off--estimated duration %s seconds"
                % timeout)
        target.ttbd_iface_call(
            "power", "off", component = component, explicit = explicit,
            timeout = timeout)
        target.report_info("powered off" + component_s)


    def on(self, component = None, explicit = False,
           console_default_reset: bool = True):
        """
        Power on a target or parts of its power rail

        :param str component: (optional) name of component to
          power on, defaults to whole target's power rail

        :param bool console_default_reset: (optional, default *True*)
          after powering on, reset the default console to it's default
          value (which is normally a serial port).
        """
        assert isinstance(console_default_reset, bool), \
            f"console_default_reset: expected bool, got {type(console_default_reset)}"
        if component != None:
            assert isinstance(component, str)
            component_s = f" component {component}"
        else:
            component_s = ""
        assert isinstance(explicit, bool)
        target = self.target
        target.report_info("powering on" + component_s, dlevel = 1)
        # extra base time, since power ops can take long when having
        # complex power rails
        timeout = 90 + self._compute_duration(target, component, "on")
        if timeout > 120:            
            target.report_info(
                "WARNING: long power-on--estimated duration %s seconds"
                % timeout)

        target.ttbd_iface_call(
            "power", "on", component = component, explicit = explicit,
            # extra time, since power ops can take long
            timeout = timeout)
        target.report_info("powered on" + component_s)
        if hasattr(target, "console") and console_default_reset:
            # reset the default console -- when we boot, any preferred
            # console will most likely be non-operative and this
            # causes a lot of grief
            target.console.default = None


    def cycle(self, component = None, wait = None, explicit = False):
        """
        Power cycle a target or one of its components

        :param float wait: (optional) seconds to wait before powering on
        :param str component: (optional) name of component to
          power-cycle, defaults to whole target's power rail
        """
        assert wait == None or wait >= 0
        if component != None:
            assert isinstance(component, str)
            component_s = f" component {component}"
        else:
            component_s = ""
        assert isinstance(explicit, bool)
        target = self.target
        target.report_info("power cycling" + component_s, dlevel = 1)
        # extra base time, since power ops can take long when having
        # complex power rails
        timeout = 90 \
            + self._compute_duration(target, component, "on") \
            + self._compute_duration(target, component, "off")
        if timeout > 120:            
            target.report_info(
                "WARNING: long power-cycle--estimated duration %s seconds"
                % timeout)
        target.ttbd_iface_call(
            "power", "cycle",
            component = component, wait = wait, explicit = explicit,
            timeout = timeout)
        target.report_info("power cycled" + component_s)
        if hasattr(target, "console"):
            target.console._set_default()


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

    def sequence(self, sequence, timeout = None):
        """
        Execute a sequence of power actions on a target

        :param str sequence: a list of pairs:

          >>> ( OPERATION, ARGUMENT )

          *OPERATION* is a string that can be:

          - *on*, *off* or *cycle*; *ARGUMENT* is a string being:

            - *all*: do the operation on all the components except
              :ref:`explicit <ttbd_power_explicit>` ones

            - *full*: perform the operation on all the components
              including the :ref:`explicit <ttbd_power_explicit>` ones

            - *COMPONENT NAME*: perform the operation only on the given
              component

          - *wait*: *ARGUMENT* is a number describing how many seconds
            to wait

          For example:

          >>> [ ( 'off', 'full' ), ( 'wait', 2 ), ( 'on', 'all' ) ]

          powers off every single component of the power rail, waits
          two seconds and then powers on all the components needed for
          normal system's power on.

        :param float timeout: (optional) maximum seconds to wait
          before giving up; default is whatever calculated based on
          how many *wait* operations are given or if none, whatever
          the default is set in
          :meth:`tcfl.tc.target_c.ttbd_iface_call`.
        """
        kwargs = {}
        if timeout != None:
            kwargs['timeout'] = timeout
        # FIXME: compute length for timeout
        self.target.report_info("running sequence: %s" % (sequence, ), dlevel = 1)
        self.target.ttbd_iface_call("power", "sequence", method = "PUT",
                                    sequence = sequence, **kwargs)
        self.target.report_info("ran sequence: %s" % (sequence, ))


    def _healthcheck(self):
        target = self.target
        target.power.off()
        power = target.power.get()
        if power != False:
            raise tc.failed_e("power should be False, reported %s" % power)

        target.report_pass("power is reported correctly as %s" % power)

        target.power.on()
        power = target.power.get()
        state, substate, components = target.power.list()
        if power != True:
            raise tc.failed_e("power should be True, reported %s" % power,
                              dict(state = state, substate = substate,
                                   components = components, power = power))
        target.report_pass("power is reported correctly as %s" % power)

        target.power.cycle()
        components = target.power.list()
        target.report_pass("power components listed",
                           dict(components = components))

        target.power.off()
        power = target.power.get()
        if power != False:
            raise tc.failed_e("power should be False, reported %s" % power)
        target.report_pass("power is reported correctly as %s" % power)
