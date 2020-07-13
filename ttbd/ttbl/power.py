#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""Control power to targets
------------------------

This interface provides means to power on/off targets and the invidual
components that compose the power rail of a target.

The interface is implemented by :class:`ttbl.power.interface` needs to
be attached to a target with :meth:`ttbl.test_target.interface_add`::

>>> ttbl.test_target.get(NAME).interface_add(
>>>     "INTERFACENAME",
>>>     ttbl.power.interface(
>>>         component0,
>>>         component1,
>>>         ...
>>>     )

each component is an instance of a subclass of
:class:`ttbl.power.impl_c`, which implements the actual control over
the power unit, such as:

- PDU socket: :class:`Digital Logger's Web Power Switch
  7<ttbl.pc.dlwps7>`, :class:`YKush <ttbl.pc_ykush.ykush>` power
  switch hub, raritan EMX
- relays: :class:`USB-RLY08b <ttbl.usbrly08b.pc>`
- control over IPMI: :class:`ttbl.ipmi.pci`

Also power components are able to:

- start / stop daemons in the server (*socat*, *rsync*, *qemu*,
  *openocd*...)

- :class:`delay <ttbl.pc.delay>` the power on/off sequence

- wait for some particular conditions to happen: a file
  :class:`dissapearing <ttbl.pc.delay_til_file_gone>` or
  :class:`appearing <ttbl.pc.delay_til_file_appears>`,
  :class:`a shell command running and returning a value
  <ttbl.power.delay_til_shell_cmd_c>` or a USB device is
  :class:`detected <ttbl.pc.delay_til_usb_device>` in the system

.. _ttbd_power_explicit:

Explicit vs normal power components
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Power components can be declared as:

  - **normal** (default): upon running whole rail power **on** or
    **off** sequences, they are always acted upon.

  - **explicit**: upon running a whole rail power **on** or **off**
    sequence, they will be skipped, unless the *explicit* option is
    given.

  - **explicit/on**: upon running a whole rail power **on** sequence,
    they will be skipped unless the *explicit* option is given.

  - **explicit/off**: upon running a whole rail power **off**
    sequence, they will be skipped unless the *explicit* option is
    given.

Thus, an *explicit* power components will be only acted upon when we
explicitly power them on/off.

Use models for the *explicit* tagging:

- a target is powered by components A and B. Component A takes a
  long time to power up and can be left on, since the actual power
  control to the target depends on also on B being on and B is more
  responsive.

  Component A would be declared as *explicit off*.

  This can be applied for example to servers powered via a PDU for AC
  power but whose actual state can be governed via a BMC using the
  IPMI protocol.

- Invasive instrumentation C connected to a target that is to be used
  only in certain ocassions but has to be powered off for normal use.

  Component C would be declared as *explicit on*.

To configure a component at the configuration level, the :attr:impl_cexplicit
attribute can be set to:

- *None* for normal behaviour

- *both* explicit for both powering on and off

- *on* explicit for powering on

- *off* explicit for powering off

this can be used either in the intialization sequence or afterwards:

>>> pc = ttbl.power.socat_pc(ADDR1, ADDR2)
>>> pc.explicit = 'both'

.. _ttbd_power_states:

Overall power state and explicit power components
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Deciding what is the overall power state has a few nuances to take
into account, especially when explicit power components are taken into
account.

The target is:

- **fully on**: when **all** the power components (including those
  tagged as *explicit* and *explicit/on*) are reporting *on* or *n/a*

- *partial on*: when **all** the power components (excluding those
  tagged as *explicit* and *explicit/on*) reports *on* and some (but
  not all) of those tagged as *explict* and *explicit/on* are
  on.

  This might be an inconsistent state, since some of the explicit
  components might not allow the target to operate normally.

- **on**: when **all** the power components (except those tagged as
   **explicit** and **explicit/on**) are reporting *on* or *n/a*

- *partial off*: when **any** (but not all) power components
  (excluding those tagged as *explicit* and *explicit/on*) reports
  *off*

- *off*: when **all** power components (excluding those tagged as
  *explicit* and *explicit/off*) report *off*

- **fully off**: when **all** the power components (including those
  tagged as *explicit* and *explicit/off*) report *off*.

Note the computation of *is the target* off depends on the context:

- for a remote user:

  - *fully on* might be impossible to reach for operation of the
    target, as some explicit/on power components might not allow the
    target to work normally (eg: invasive instrumentation that disallows
    normal operation).

  - *partial on* like *fully on*, this might be an inconsistent state,
    since some of the explicit components might not allow the target
    to operate normally.

    This might be used for non-common circumnstances to administer,
    diagnose or do non typical work on the targets.

  - *on* means the target should operate as it'd be normally

  - *partial off* likely means the not everything the target needs to
    work is operative; to bring it to operation most likely it shall
    be power cycled (take to off, then power on).

  - *off* means the target is powered off as it'd be normally

  - *partial off* likely means the not everything the target needs to
    work is operative; to bring it to operation most likely it shall
    be power cycled (take to off, then power on).

- for a daemon powering off unused infrastructure, it should take to
  *off* anything on *partially off*, *on* and *fully on* and after a
  longer count, maybe bring to *fully off*.

As a convenience, the system publishes in the inventory the data
*interfaces.power.state* as *true* if *on*. Otherwise, the state is
not published and must be assumed as *off* or *fully off*.

"""
import collections
import errno
import json
import numbers
import os
import time
import traceback
import types
import subprocess
import logging

import commonl
import ttbl

class impl_c(ttbl.tt_interface_impl_c):
    """Implementation interface to drive a  power component

    A power component is an individual entity that provides one of the
    pieces of a power rail needed to power up a target.

    It can be powered on, off and it's state can be acquired.

    A driver is made by subclassing this object, implementing the
    :meth:`on`, :meth:`off` and :meth:`get` methods and then adding
    it to a power interface :class:`ttbl.power.interface` which is
    then attached to a target.

    Drivers implement the specifics to run the switches PDUs, relays,
    etc

    Note these are designed to be as stateless as possible; in most
    cases all the state needed can be derived from the *target* and
    *component* parameters passed to the methods.

    Remember no information can be stored *self* or *target* as the
    next call can come in another daemon implementing the same
    target. For storage, use the target's *fsdb* interface.

    **ALL** the methods have to be blocking, so the operation is
    supposed to be completed and the status has to have been changed
    by the time the call returns. If the operation cannot be trusted
    to be blocking, set the *paranoid* parameter to *True* so the
    power interface will confirm the change has re-happened and
    enforce it again.

    :param bool paranoid: don't trust the operation is really
      blocking, as it should, so double check the state changed happen
      and retry if not.

    :param str explicit: (optional, default *None*) declare if this power
      component shall be only turned on or off when explicitly named in
      a power rail. See :ref:ttbd_power_explicit.

      - *None*: for normal behaviour

      - *both*: explicit for both powering on and off

      - *on*: explicit for powering on

      - *off*: explicit for powering off

    """
    def __init__(self, paranoid = False, explicit = None):
        assert isinstance(paranoid, bool)
        assert explicit in ( None, 'on', 'off', 'both' )
        #: If the power on fails, automatically retry it by powering
        #: first off, then on again
        self.power_on_recovery = False
        self.paranoid = paranoid
        self.timeout = 10	# used for paranoid checks
        self.wait = 0.5
        self.explicit = explicit
        #: for paranoid power getting, now many samples we need to get
        #: that are the same for the value to be considered stable
        self.paranoid_get_samples = 6
        ttbl.tt_interface_impl_c.__init__(self)

    class retry_all_e(Exception):
        """
        Exception raised when a power control implementation operation
        wants the whole power-rail reinitialized
        """
        def __init__(self, wait = None):
            assert wait == None or wait > 0
            Exception.__init__(self)
            self.wait = wait

    class error_e(Exception):
        "generic power implementation error"
        pass

    class power_on_e(error_e):
        "generic power-on implementation error"
        pass

    def on(self, target, component):
        """
        Power on the component

        :param ttbl.test_target target: target on which to act
        :param str component: name of the power controller we are modifying
        """
        raise NotImplementedError("%s/%s: power-on not implemented"
                                  % (target.id, component))

    def off(self, target, component):
        """
        Power off the component

        Same parameters as :meth:`on`
        """
        raise NotImplementedError("%s/%s: power-off not implemented"
                                  % (target.id, component))

    def get(self, target, component):
        """
        Return the component's power state

        Same parameters as :meth:`on`

        :returns: power state:

          - *True*: powered on

          - *False*: powered off

          - *None*: this is a *fake* power unit, so it has no actual
            power state
        """
        raise NotImplementedError("%s/%s: getting power state not implemented"
                                  % (target.id, component))


class interface(ttbl.tt_interface):
    """
    Power control interface

    Implements an interface that allows to control the power to a
    target, which can be a single switch or a whole power rail of
    components that have to be powered on and off in an specific
    sequence.
    """

    def __init__(self, *impls, **kwimpls):
        # in Python 3.6, kwargs are sorted; but for now, they are not.
        ttbl.tt_interface.__init__(self)
        # we need an ordered dictionary because we need to iterate in
        # the same order as the components were declared--as that is
        # what the user dictates. Because the power on/off order of
        # each rail component matters.
        self.impls_set(impls, kwimpls, impl_c)

    def _target_setup(self, target, iface_name):
        # Called when the interface is added to a target to initialize
        # the needed target aspect (such as adding tags/metadata)
        for name, impl in self.impls.items():
            assert name not in ( 'all', 'full' ), \
                "power component '%s': cannot be called '%s'; name reserved" \
                % (name, name)
            assert impl.explicit in ( None, 'on', 'off', 'both' ), \
                "power component '%s': impls' explicit value is %s;" \
                " expected None, 'on', 'off' or 'both'" % (name, impl.implicit)

    def _release_hook(self, target, _force):
        # nothing to do on target release
        # we don't power off on release so we can pass the target to
        # someone else in the same state it was
        pass

    def _impl_on(self, impl, target, component):
        # calls the implementation function to do the ON operation,
        # being sure to check if it has actually accomplished it if
        # the paranoid flag is set
        if not impl.paranoid:
            impl.on(target, component)
            return

        ts0 = ts = time.time()
        while ts - ts0 < impl.timeout:
            try:
                impl.on(target, component)
            except impl.error_e as e:
                target.log.error("%s: impl failed powering on +%.1f;"
                                 " powering off and retrying: %s",
                                 component, ts - ts0, e)
                try:
                    self._impl_off(impl, target, component)
                except impl.error_e as e:
                    target.log.exception(
                        "%s: impl failed recovery power off +%.1f;"
                        " ignoring for retry: %s",
                        component, ts - ts0, e)
            else:
                target.log.info("%s: impl powered on +%.1fs",
                                component, ts - ts0)
            # let's check the status, because sometimes with
            # transitions on its own
            new_state = self._impl_get(impl, target, component)
            if new_state == None or new_state == True: # check
                return
            target.log.info("%s: impl didn't power on +%.1f retrying",
                            component, ts - ts0)
            time.sleep(impl.wait)
            ts = time.time()
        raise RuntimeError("%s: impl power-on timed out after %.1fs"
                           % (component, ts - ts0))

    def _impl_off(self, impl, target, component):
        # calls the implementation function to do the OFF operation,
        # being sure to check if it has actually accomplished it if
        # the paranoid flag is set
        if not impl.paranoid:
            impl.off(target, component)
            return

        ts0 = ts = time.time()
        while ts - ts0 < impl.timeout:
            try:
                impl.off(target, component)
            except impl.error_e as e:
                target.log.error("%s: impl failed powering off +%.1f;"
                                 " retrying: %s", component, ts - ts0, e)
            else:
                target.log.info("%s: impl powered off +%.1fs",
                                component, ts - ts0)
            # maybe it worked, let's checked
            new_state = self._impl_get(impl, target, component)
            if new_state == None or new_state == False: # check
                return
            target.log.info("%s: ipmi didn't power off +%.1f retrying",
                                component, ts - ts0)
            time.sleep(impl.wait)
            ts = time.time()
        raise RuntimeError("%s: impl power-off timed out after %.1fs"
                           % (component, ts - ts0))

    @staticmethod
    def _impl_get(impl, target, component):
        # calls the implementation function to do the GET operation,
        # being sure to collection multiple samples and only return
        # once we have N results that are stable if the paranoid flag
        # is set.
        if not impl.paranoid:
            return impl.get(target, component)

        results = []
        ts0 = ts = time.time()
        stable_count = 0
        _states = {
            False: 'off',
            True: 'on',
            None: 'n/a'
        }
        while ts - ts0 < impl.timeout:
            result = impl.get(target, component)
            target.log.info("%s: impl power get #%d +%.2fs returned %s",
                            component, stable_count, ts - ts0, _states[result])
            results.append(result)
            stable_count += 1
            if stable_count >= impl.paranoid_get_samples:
                # we have enough samples, take the last stabe_top and
                # see if they are all the same:
                cs = set(results[-impl.paranoid_get_samples:])
                if len(cs) == 1:
                    # stable result; return it
                    return cs.pop()
            time.sleep(impl.wait)
            ts = time.time()
        raise RuntimeError(
            "%s: power-get timed out for an stable result (+%.2fs): %s"
            % (component, impl.timeout, " ".join(str(r) for r in results)))


    def _get(self, target, impls = None):
        # get the power state for the target's given power components,
        # keep data ordered, makes more sense
        data = collections.OrderedDict()
        if impls == None:	# none give, do the whole power rail
            impls = iter(self.impls.items())
        normal = {}
        explicit = {}
        explicit_on = {}
        explicit_off = {}
        for component, impl in impls:
            # need to get state for the real one!
            if component in self.aliases:
                component_real = self.aliases[component]
            else:
                component_real = component
            state = self._impl_get(impl, target, component_real)
            self.assert_return_type(state, bool, target,
                                    component, "power.get", none_ok = True)
            data[component] = {
                "state": state
            }
            if impl.explicit:
                data[component]['explicit'] = impl.explicit
            if impl.explicit == None:
                normal[component] = state
            elif impl.explicit == 'both':
                explicit[component] = state
            elif impl.explicit == 'on':
                explicit_on[component] = state
            elif impl.explicit == 'off':
                explicit_off[component] = state
            else:
                raise AssertionError(
                    "BUG! component %s: unknown explicit tag '%s'" %
                    (component, impl.explicit))

        # What state are we in?
        #
        # See 'Overall power state and explicit power components'
        # above, but basically we need to report:
        #
        #  state: True (on) or False (off)
        #  substate: 'normal', 'full', 'partial'
        #
        if all(i == True for i in list(normal.values()) + list(explicit_off.values())):
            state = True
            if all(i['state'] in (True, None) for i in list(data.values())):
                substate = 'full'
            elif all(i == False
                     for i in list(explicit.values()) + list(explicit_on.values())):
                substate = 'normal'
            else:
                substate = 'partial'
        elif any(i == False
                 for i in list(normal.values()) + list(explicit_on.values())):
            state = False
            if all(i['state'] in (False, None) for i in list(data.values())):
                substate = 'full'
            elif all(i == True
                     for i in list(explicit_off.values())):
                substate = 'normal'
            else:
                substate = 'partial'
        else:
            # something is really off
            state = False
            substate = 'partial'

        target.fsdb.set('interfaces.power.state', state)
        target.fsdb.set('interfaces.power.substate', substate)
        return state, data, substate


    def _off(self, target, impls, why, whole_rail = True, explicit = False):
        #
        # Power off everything
        #
        # We only power off whatever is on, hence why we ask what is
        # on first.
        #
        # If the user asked for the whole rail, then we'll also run
        # the pre/post hooks.
        _state, data, _substate = self._get(target, impls)

        target.log.info("powering off%s" % why)
        if whole_rail:
            target.log.debug(
                "power pre-off%s; fns %s"
                % (why, " ".join(str(f) for f in target.power_off_pre_fns)))
            for f in target.power_off_pre_fns:
                f(target)
            target.log.debug("power pre-off%s done" % why)

        for component, impl in reversed(impls):
            if component in self.aliases:
                if whole_rail:
                    # operate only on real ones when going over the whole rail
                    target.log.debug("%s: power off%s: skipping (alias)"
                                     % (component, why))
                    continue
                component_real = self.aliases[component]
            else:
                component_real = component
            if data[component]['state'] == False:
                target.log.debug("%s: powering off%s: skipping (already off)"
                                 % (component, why))
                continue            	# it says it is off, so we skip it
            if whole_rail \
               and impl.explicit in ( "off", "both" ) and not explicit:
                target.log.debug("%s: powering off%s: skipping (explicit/%s)"
                                 % (component, why, impl.explicit))
                continue            	# it says it is off, so we skip it

            target.log.debug("%s: powering off%s" % (component, why))
            try:			# we retry power off twice
                self._impl_off(impl, target, component_real)
                continue
            except Exception as e:	# pylint: disable = broad-except
                target.log.error("%s: power off%s: failed; retrying: %s"
                                 % (component, why, e))
            try:
                self._impl_off(impl, target, component_real)
                continue
            except Exception as e:	# pylint: disable = broad-except
                target.log.error(
                    "%s: power off%s: failed twice; skipping: %s\n%s"
                    % (component, why, e, traceback.format_exc()))
                # we don't raise no more, we want to be able to
                # cleanup state and continue with the rest
                target.log.debug("%s: powered off%s" % (component, why))
        if whole_rail:
            target.log.debug(
                "power post-off%s; fns %s"
                % (why, " ".join(str(f) for f in target.power_off_post_fns)))
            for f in target.power_off_post_fns:
                f(target)
            target.log.debug("power post-off%s done" % why)
        target.fsdb.set('powered', None)
        target.log.info("powered off%s" % why)


    def _on(self, target, impls, why, whole_rail = True, explicit = False):
        #
        # Power on
        #
        # We only power on whatever is off, hence why we ask what is
        # off first. Power rails have to always be powered on in the
        # same sequence, so if it is half off half on, it should be
        # powered off first. But that's the user's call (use cycle())
        #
        # If the user asked for the whole rail, then we'll also run
        # the pre/post hooks.
        #
        # Recovery can be quite painful, since we might have to retry
        # (a single component) or the whole rail. Code gets ugly.
        _state, data, _substate = self._get(target, impls)

        target.log.info("powering on%s" % why)
        if whole_rail:
            # since we are powering on, let's have whoever does this
            # select the right default console, but we wipe whatver
            # was set before
            target.property_set('interfaces.console.default', None)
            target.log.debug(
                "power pre-on%s; fns %s"
                % (why, " ".join(str(f) for f in target.power_on_pre_fns)))
            for f in target.power_on_pre_fns:
                f(target)
            target.log.debug("power pre-on%s done" % why)

        # Power on in the specified order, off in the reverse
        # We use impl_index instead of iterating so we can reset
        # the index easily without having to deal with
        # StopIteration exceptions and try statements everywhere.
        index = 0
        impls_items = impls
        retries = 0
        retries_max = 3
        recovery_wait = 0.5
        while index < len(impls):
            impl_item = impls_items[index]
            component = impl_item[0]
            impl = impl_item[1]
            index += 1
            if component in self.aliases:
                if whole_rail:
                    # operate only on real ones when going over the whole rail
                    target.log.debug("%s: power off%s: skipping (alias)"
                                     % (component, why))
                    continue
                component_real = self.aliases[component]
            else:
                component_real = component
            if whole_rail \
               and impl.explicit in ( "on", "both" ) and not explicit:
                target.log.debug("%s: powering on%s: skipping (explicit/%s)"
                                 % (component, why, impl.explicit))
                continue            	# it says it is off, so we skip it
            if data[component]['state'] == True:
                target.log.debug("%s: powering on%s: skipping (already on)"
                                 % (component, why))
                continue            	# it says it is off, so we skip it
            target.log.debug("%s: powering on%s" % (component, why))
            try:
                self._impl_on(impl, target, component_real)	# ok, power ir on
                continue		# fallthrough is error recovery

            except impl_c.retry_all_e as e:
                # This power component has errored when powering on.
                # It has requested for the rail to be powered off
                # and retried--note that when we have specified only
                # specific components of the power rail, it only
                # affects them
                retries += 1
                if retries >= retries_max:
                    raise RuntimeError(
                        "power on%s: failed too many retries (%d)"
                        % (why, retries))
                target.log.error("%s: power-on%s failed: retrying (%d/%d) "
                                 "the whole power rail: %s",
                                 component, why, retries, retries_max, e)
                try:
                    # power off the whole given rail, but no pre/post
                    # execution, since we are just dealing with the components
                    self._off(target, impls,
                              " (retrying because %s failed)" % component,
                              False)
                except:			# pylint: disable = bare-except
                    pass		# yeah, we ignore errors here
                index = 0		# start again
                if e.wait:
                    time.sleep(e.wait)
                continue		# fallthrough is error recovery!

            except Exception as e:	# pylint: disable = broad-except
                # This power component has errored when powering on.
                # We'll retry by powering it off, then on again
                if impl.power_on_recovery:
                    target.log.error(
                        "%s: power-on%s failed: retrying after power-off: %s"
                        % (component, why, e))
                else:
                    target.log.error(
                        "%s: power-on%s failed: not retrying: %s"
                        % (component, why, e))
                    raise
                # fall through!
            if impl.power_on_recovery:
                try:
                    # power off to recover
                    self._impl_off(impl, target, component_real)
                except Exception as e:	# pylint: disable = broad-except
                    target.log.error("%s: power off%s for recovery "
                                     "failed (ignoring): %s"
                                     % (component, why, e))
                time.sleep(recovery_wait)
                try:			# Let's retry
                    self._impl_on(impl, target, component_real)
                    continue		# good, it worked
                except Exception as e:
                    target.log.error(
                        "%s: power-on%s failed (again): aborting: %s"
                        % (component, why, e))
                    try:		# ok, not good, giving up
		        # power off just in case, to avoid electrical
                        # issues, etc.
                        self._impl_off(impl, target, component_real)
                    except Exception as e:	# pylint: disable = broad-except
                        # is not much we can do if it fails
                        target.log.error(
                            "%s: power-off%s due to failed power-on failed: %s"
                            % (component, why, e))
                        # don't raise this, raise the original one
                    raise

            target.log.debug("%s: powered on%s" % (component, why))
        if whole_rail:
            target.log.debug(
                "power post-on%s; fns: %s"
                % (why, " ".join(str(f) for f in target.power_on_post_fns)))
            for f in target.power_on_post_fns:
                f(target)
            target.log.debug("power post-on%s: done" % why)
        target.log.info("powered on%s" % why)
        target.fsdb.set('powered', 'On')


    # called by the daemon when a METHOD request comes to the HTTP path
    # /ttb-vVERSION/targets/TARGET/interface/console/CALL

    def _explicit_get(self, args):
        # return the value of the 'explicit' argument, if given
        explicit = self.arg_get(args, 'explicit', None, True, False)
        # support that it might come as bool already
        if not isinstance(explicit, bool):
            explicit = json.loads(explicit)
            assert isinstance(explicit, bool), \
                "'explicit' argument must be a boolean"
        return explicit

    def get_list(self, target, _who, _args, _files, _user_path):
        # return a dictionary indicating the individual state of
        # each power component
        state, data, substate = self._get(target)
        # return a sorted list, so the order is maintained
        return dict(state = state, substate = substate, components = data)

    def put_on(self, target, who, args, _files, _user_path):
        impls, _all = self.args_impls_get(args)
        explicit = self._explicit_get(args)
        with target.target_owned_and_locked(who):
            target.timestamp()
            self._on(target, impls, "", _all, explicit)
            return {}

    def put_off(self, target, who, args, _files, _user_path):
        impls, _all = self.args_impls_get(args)
        explicit = self._explicit_get(args)
        with target.target_owned_and_locked(who):
            target.timestamp()
            self._off(target, impls, "", _all, explicit)
            return {}

    def put_cycle(self, target, who, args, _files, _user_path):
        impls, _all = self.args_impls_get(args)
        # default wait is two seconds
        wait = self.arg_get(args, 'wait', (type(None), numbers.Real),
                            allow_missing = True, default = None)
        if wait == None:
            wait = float(target.tags.get('power_cycle_wait', 2))
        explicit = self._explicit_get(args)
        with target.target_owned_and_locked(who):
            target.timestamp()
            self._off(target, impls, " (because power-cycle)", _all, explicit)
            if wait:
                time.sleep(wait)
            self._on(target, impls, " (because power-cycle)", _all, explicit)
            return {}

    def put_reset(self, target, who, args, _files, _user_path):
        self.put_cycle(target, who, args, _files, _user_path)


    def sequence(self, target, sequence):
        """
        Execute a sequence of actions on a target

        The sequence argument has to be a list of pairs:

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
        """
        target.timestamp()
        count = 0
        for s in sequence:
            # we verify for correctness on the run, which means if the
            # sequence is wrong it might be left in a weird
            # state. ok. that's the caller's problem.
            if not isinstance(s, (list, tuple)):
                raise ValueError("%s: sequence #%d: invalid type:"
                                 " expected list; got %s"
                                 % (target.id, count, type(s)))
            if len(s) != 2:
                raise ValueError("%s: sequence #%d: invalid list length; "
                                 " expected 2; got %s"
                                 % (target.id, count, len(s)))
            action = s[0]
            if action == 'wait':
                time_to_wait = s[1]
                assert isinstance(time_to_wait, numbers.Real), \
                    "%s: sequence #%d: invalid time length; " \
                    "expected float, got %s" \
                    % (target.id, count, type(time_to_wait))
                time.sleep(s[1])
                continue

            if action not in [ 'on', 'off', 'cycle' ]:
                raise ValueError("%s: sequence #%d: invalid action spec; "
                                 " expected on|off|cycle; got %s"
                                 % (target.id, count, action))

            component = s[1]
            if not isinstance(component, str):
                raise ValueError("%s: sequence #%d: invalid component spec; "
                                 " expected str; got %s"
                                 % (target.id, count, type(component)))
            # We have an action and a component to act on; None/[]
            # means act on all components in an explicit/non-explicit
            # way, so decode the component list
            explicit = False
            if component == 'full':
                impls, _all = self.args_impls_get(dict())
                explicit = True
            elif component == 'all':
                impls, _all = self.args_impls_get(dict())
            else:
                impls, _all = self.args_impls_get(dict(component = component))
            # and now act
            if action == 'on':
                self._on(target, impls, " (because sequenced on)",
                         _all, explicit)
            elif action == 'off':
                self._off(target, impls, " (because sequenced off)",
                          _all, explicit)
            elif action == 'cycle':
                wait = float(target.tags.get('power_cycle_wait', 2))
                self._off(target, impls, " (because sequenced cycle)",
                          _all, explicit)
                if wait:
                    time.sleep(wait)
                self._on(target, impls, " (because sequneced cycle)",
                         _all, explicit)
            else:
                raise RuntimeError(
                    "%s: unknown action (expected on|off|cycle)" % action)



    def sequence_verify(self, target, sequence, qualifier = ""):
        """
        Verify a sequence is correct

        See :meth:sequence for parameters

        :returns: nothing if ok, raises an exceptin on error
        """
        count = 0
        for s in sequence:
            # we verify for correctness on the run, which means if the
            # sequence is wrong it might be left in a weird
            # state. ok. that's the caller's problem.
            if not isinstance(s, (list, tuple)):
                raise ValueError("%s%s: sequence #%d: invalid type:"
                                 " expected list; got %s"
                                 % (target.id, qualifier, count, type(s)))
            if len(s) != 2:
                raise ValueError("%s%s: sequence #%d: invalid list length; "
                                 " expected 2; got %s"
                                 % (target.id, qualifier, count, len(s)))
            action = s[0]
            if action == 'wait':
                time_to_wait = s[1]
                assert isinstance(time_to_wait, numbers.Real), \
                    "%s: sequence #%d: invalid time length; " \
                    "expected float, got %s" \
                    % (target.id, qualifier, count, type(time_to_wait))
                continue

            if action not in [ 'on', 'off', 'cycle' ]:
                raise ValueError("%s%s: sequence #%d: invalid action spec; "
                                 " expected on|off|cycle; got %s"
                                 % (target.id, qualifier, count, action))

            component = s[1]
            if not isinstance(component, str):
                raise ValueError("%s%s: sequence #%d: invalid component spec; "
                                 " expected str; got %s"
                                 % (target.id, qualifier, count, type(component)))
            # We have an action and a component to act on; None/[]
            # means act on all components in an explicit/non-explicit
            # way, so decode the component list
            explicit = False
            if component == 'full':
                impls, _all = self.args_impls_get(dict())
                explicit = True
            elif component == 'all':
                impls, _all = self.args_impls_get(dict())
            else:
                impls, _all = self.args_impls_get(dict(component = component))


    def put_sequence(self, target, who, args, _files, _user_path):
        sequence = self.arg_get(args, 'sequence', list)
        with target.target_owned_and_locked(who):
            self.sequence(target, sequence)
            return {}


class fake_c(impl_c):
    """Fake power component which stores state in disk

    Note this object doesn't have to know much parameters on
    initialization, which allows us to share implementations.

    It can rely on the *target* and *component* parameters to
    each method to derive where to act.

    Parameters are the same as for :class:impl_c.
    """
    def __init__(self, **kwargs):
        impl_c.__init__(self, **kwargs)

    def on(self, target, component):
        target.log.info("power-fake-%s on" % component)
        target.fsdb.set('power-fake-%s' % component, 'True')

    def off(self, target, component):
        target.log.info("power-fake-%s off" % component)
        target.fsdb.set('power-fake-%s' % component, None)

    def get(self, target, component):
        state = target.fsdb.get('power-fake-%s' % component) == 'True'
        target.log.info("power-fake-%s get: %s" % (component, state))
        return state


class inverter_c(impl_c):
    """
    A power controller that wraps another power controller and does
    the opposite.

    When turned on, the wrapped controlled is turned off

    When turned off, the wrapped controlled is turned on

    When querying power, it returns *off* if the wrapped controller is
      *on*, *on* if *off*.

    :param ttbl.power.impl_c pc: power controller to wrap

    Other parameters as to :class:ttbl.power.impl_c.
    """
    def __init__(self, pc, when_on = True, when_off = True, when_get = True,
                 **kwargs):
        assert isinstance(pc, impl_c)
        assert isinstance(when_on, bool)
        assert isinstance(when_off, bool)
        assert isinstance(when_get, bool)

        impl_c.__init__(self, **kwargs)
        self.pc = pc
        # These have to be the same set of default properties in
        # ttbl.power.impl_c
        self.power_on_recovery = pc.power_on_recovery
        self.paranoid = pc.paranoid
        self.timeout = pc.timeout
        self.wait = pc.wait
        self.paranoid_get_samples = pc.paranoid_get_samples
        self.when_on = when_on
        self.when_off = when_off
        self.when_get = when_get

    def on(self, target, component):
        if self.when_on:
            self.pc.off(target, component)

    def off(self, target, component):
        if self.when_off:
            self.pc.on(target, component)

    def get(self, target, component):
        if not self.when_get:
            return None
        state = self.pc.get(target, component)
        if state == None:
            return state
        return not state


class daemon_c(impl_c):
    """
    Generic power controller to start daemons in the server machine

    FIXME: document

    :param list(str) cmdline: command line arguments to pass to
      :func:`subprocess.check_output`; this is a list of
      strings, first being the path to the command, the rest being the
      arguments.

      All the entries in the list are templated with *%(FIELD)s*
      expansion, where each field comes either from the *kws*
      dictionary or the target's metadata.

    Other parameters as to :class:ttbl.power.impl_c.
    """
    #: KEY=VALUE to add to the environment
    #: Keywords to add for templating the arguments
    def __init__(self, cmdline,
                 precheck_wait = 0, env_add = None, kws = None,
                 path = None, name = None,
                 pidfile = None, mkpidfile = True, paranoid = False,
                 **kwargs):
        assert isinstance(cmdline, list), \
            "cmdline has to be a list of strings; got %s" \
            % type(cmdline).__name__
        assert precheck_wait >= 0
        impl_c.__init__(self, paranoid = paranoid, **kwargs)
        self.cmdline = cmdline
        #: extra command line elements that can be added by anybody
        #: subclassing this; note an *on()* method that adds to this
        #: needs to reset it each time (otherwise it'll keep
        #: appending):
        #:
        #: >>> class something(daemon_c):
        #: >>>
        #: >>>     def on(target, component):
        #: >>>         self.cmdline_extra = [ "-v", "--login", "JOHN" ]
        #: >>>         daemon_c.on(self, target, component)
        #:
        #: vs using *self.cmdline_extra.append()*

        self.cmdline_extra = []
        self.precheck_wait = precheck_wait
        if env_add:
            assert isinstance(env_add, dict)
            self.env_add = env_add
        else:
            self.env_add = {}
        #: dictionary of keywords that can be use to template the
        #: command line with *%(FIELD)S*
        self.kws = {}
        if kws:
            assert isinstance(kws, dict)
            self.kws = kws
        if path == None:
            self.path = cmdline[0]
        else:
            assert isinstance(path, str)
            self.path = path
        if name == None:
            self.name = os.path.basename(self.path)
        else:
            assert isinstance(name, str)
            self.name = name
        self.kws.setdefault('name', self.name)
        if pidfile:
            assert isinstance(pidfile, str)
            self.pidfile = pidfile
        else:
            self.pidfile = "%(path)s/%(component)s-%(name)s.pid"
        assert isinstance(mkpidfile, bool)
        self.mkpidfile = mkpidfile


    def verify(self, target, component, cmdline_expanded):
        """
        Function that verifies if the daemon has started or not

        For example, checking if a file has been created, etc

        **THIS MUST BE DEFINED**

        Examples:

        >>> return os.path.exists(cmdline_expanded[0])

        or

        >>> return os.path.exists(self.pidfile % kws)

        or to verify a pid file exists and the prcoess exists:

        >>> return commonl.process_alive(PATH-TO-PIDFILE, PATH-TO-BINARY)


        :returns: *True* if the daemon started, *False* otherwise
        """
        raise NotImplementedError

    def _stderr_stream(self, target, component, stderrf):
        count = 0
        for line in stderrf:
            target.log.error("%s stderr: %s" % (component, line.rstrip()))
            count += 1
        if count == 0:
            target.log.error("%s: stderr not available" % component)

    def log_stderr(self, target, component, stderrf = None):
        if stderrf:
            stderrf.flush()
            stderrf.seek(0, 0)
            self._stderr_stream(target, component, stderrf)
        else:
            name = os.path.join(target.state_dir,
                                component + "-" + self.name + ".stderr")
            try:
                with open(name) as stderrf:
                    self._stderr_stream(target, component, stderrf)
            except IOError as e:
                if e.errno == errno.ENOENT:
                    target.log.error("%s: stderr not available" % component)
                else:
                    target.log.error("%s: can't open stderr file: %s"
                                     % (component, e))

    def on(self, target, component):
        stderrf_name = os.path.join(target.state_dir,
                                    component + "-" + self.name + ".stderr")

        kws = dict(target.kws)
        kws.update(self.kws)
        # bring in runtime properties (override the rest)
        kws.update(target.fsdb.get_as_dict())
        kws['component'] = component
        # render the real commandline against kws
        _cmdline = []
        count = 0
        try:
            for i in self.cmdline + self.cmdline_extra:
                # some older Linux distros complain if this string is unicode
                _cmdline.append(str(i % kws))
            count += 1
        except KeyError as e:
            message = "configuration error? can't template command line #%d," \
                " missing field or target property: %s" % (count, e)
            target.log.error(message)
            raise self.power_on_e(message)
        target.log.info("%s: command line: %s"
                        % (component, " ".join(_cmdline)))
        if self.env_add:
            env = dict(os.environ)
            env.update(self.env_add)
        else:
            env = os.environ
        pidfile = self.pidfile % kws
        commonl.rm_f(pidfile)
        stderrf = open(stderrf_name, "w+")
        try:
            p = subprocess.Popen(_cmdline, env = env, cwd = target.state_dir,
                                 stderr = stderrf, bufsize = 0, shell = False,
                                 universal_newlines = False)
            if self.mkpidfile:
                with open(pidfile, "w+") as pidf:
                    pidf.write("%s" % p.pid)
        except TypeError as e:
            # This happens on misconfiguration
            ## TypeError: execve() arg 3 contains a non-string value
            if 'execve() arg 3' in str(e):
                target.log.exception(
                    "Ensure environment settings are not set to None", e)
            if 'execve()' in str(e):
                target.log.exception(
                    "Possible target misconfiguration: %s", e)
                count = 0
                for i in _cmdline:
                    target.log.error(
                        "cmdline %d: [%s] %s", count, type(i).__name__, i)
                    count += 1
                for key, val in env.items():
                    target.log.error(
                        "env %s: [%s] %s", key, type(val).__name__, val)
            raise
        except OSError as e:
            raise self.power_on_e("%s: %s failed to start [cmdline %s]: %s" % (
                component, self.name, " ".join(_cmdline), e))

        if self.precheck_wait:
            time.sleep(self.precheck_wait)
        pid = commonl.process_started(pidfile, self.path,
                                      component + "-" + self.name, target.log,
                                      self.verify,
                                      ( target, component, _cmdline, ))
        if pid == None:
            self.log_stderr(target, component, stderrf)
            raise self.power_on_e("%s: %s failed to start"
                                  % (component, self.name))
        ttbl.daemon_pid_add(pid)


    def off(self, target, component):
        kws = dict(target.kws)
        kws.update(self.kws)
        # bring in runtime properties (override the rest)
        kws.update(target.fsdb.get_as_dict())
        kws['component'] = component
        pidfile = self.pidfile % kws
        try:
            commonl.process_terminate(pidfile, path = self.path,
                                      tag = component + "-" + self.name)
        except OSError as e:
            if e != errno.ESRCH:
                raise


    def get(self, target, component):		# power interface
        kws = dict(target.kws)
        kws.update(self.kws)
        # bring in runtime properties (override the rest)
        kws.update(target.fsdb.get_as_dict())
        kws['component'] = component
        return commonl.process_alive(self.pidfile % kws, self.path) != None


class delay_til_shell_cmd_c(impl_c):
    """
    Delay until a shell commands returns an specific value

    This is meant to be used in a power rail to delay until a certain
    shell command evaluates as succesful (return 0).

    Usage models:

    - look for USB devices whose serial number has to be dug from a
      deeper protocol than USB

    Other parameters as to :class:ttbl.power.impl_c.

    """
    def __init__(self, cmdline,
                 condition_msg = None,
                 cwd = "/tmp", env = None,
                 expected_retval = 0, when_on = True, when_off = False,
                 poll_period = 0.25, timeout = 25, **kwargs):
        commonl.assert_list_of_strings(cmdline, "cmdline",
                                       "command line components")
        assert condition_msg == None or isinstance(condition_msg, str)
        assert isinstance(cwd, str)
        commonl.assert_none_or_dict_of_strings(env, "env")
        assert isinstance(expected_retval, int)
        assert isinstance(when_on, bool)
        assert isinstance(when_off, bool)
        assert isinstance(poll_period, numbers.Real)
        assert isinstance(timeout, numbers.Real)

        impl_c.__init__(self, **kwargs)
        self.cmdline = cmdline
        if condition_msg == None:
            self.condition_msg = "'%s' returns %d" % (
                " ".join(self.cmdline), expected_retval)
        else:
            self.condition_msg = condition_msg
        self.cwd = cwd
        self.env = env
        self.expected_retval = expected_retval
        self.when_on = when_on
        self.when_off = when_off
        self.poll_period = poll_period
        self.timeout = timeout

    def _cmdline_format(self, target, component):
        kws = dict(target.kws)
        cmdline = []
        count = 0
        try:
            for i in self.cmdline:
                # some older Linux distros complain if this string is unicode
                cmdline.append(str(i % kws))
            count += 1
        except KeyError as e:
            message = "%s: configuration error?" \
                " can't template command line #%d," \
                " missing field or target property: %s" % (
                    component, count, e)
            target.log.error(message)
            raise self.power_on_e(message)
        return cmdline, kws

    def _test(self, _target, _component, cmdline):
        r = subprocess.call(cmdline,
                            env = self.env, cwd = self.cwd,
                            stdin = None, stderr = subprocess.STDOUT)
        return r == self.expected_retval


    def on(self, target, component):
        if self.when_on == False:
            return
        cmdline, kws = self._cmdline_format(target, component)
        condition_msg = self.condition_msg % kws
        ts0 = time.time()
        ts = ts0
        while ts - ts0 < self.timeout:
            if self._test(target, component, cmdline):
                break
            target.log.debug(
                "%s: delaying power-on %.fs until %s" % (
                    component, self.poll_period, condition_msg,
                ))
            time.sleep(self.poll_period)
        else:
            raise RuntimeError(
                "%s: timeout (%.1fs) on power-on delay "
                "waiting for %s" % (
                    component, self.timeout, condition_msg
                ))
        target.log.info(
            "%s: delayed power-on %.1fs (max %.1fs) until %s"
            % (
                component, ts - ts0, self.timeout, condition_msg
            ))


    def off(self, target, component):
        if self.when_off == False:
            return
        cmdline, kws = self._cmdline_format(target, component)
        condition_msg = self.condition_msg % kws
        ts0 = time.time()
        ts = ts0
        while ts - ts0 < self.timeout:
            if not self._test(target, component, cmdline):
                break
            target.log.debug(
                "%s: delaying power-off %.fs until (not) %s" % (
                    component, self.poll_period, condition_msg
                ))
            time.sleep(self.poll_period)
        else:
            raise RuntimeError(
                "%s: timeout (%.1fs) on power-off delay waiting"
                " until (not) %s" % (
                    component, self.timeout, condition_msg
                ))
        target.log.info(
            "%s: delayed power-off %.1fs (max %.1fs)"
            " until (not) %s" % (
                component, ts - ts0, self.timeout, condition_msg
            ))


    def get(self, target, component):
        cmdline, _kws = self._cmdline_format(target, component)
        return self._test(target, component, cmdline)


class socat_pc(daemon_c):
    """
    Generic power component that starts/stops socat as daemon

    This class is meant to be subclassed for an implementation passing
    the actual addresses to use.

    :param str address1: first address for socat; will be templated
      with *%(FIELD)s* to the target's keywords and anything added in
      :data:`daemon_c.kws`.
    :param str address2: second address for socat; templated as
      *address1*
    :param dict env_add: variables to add to the environment when
      running socat
    :param float precheck_wait: seconds to wait once starting before
      checking if the daemon is running; sometimes it dies after we
      check, so it is good to give it a wait.

    Other arguments as to :class:ttbl.power.impl_c.

    This object (or what is derived from it) can be passed to a power
    interface for implementation, eg:

    >>> ttbl.test_target.get('TARGETNAME').interface_add(
    >>>     "power",
    >>>     ttbl.power.interface(
    >>>         ttbl.power.socat_pc(ADDR1, ADDR2)
    >>>     )
    >>> )

    Upon power up, the *socat* daemon will be started, with it's
    current directory set to the target's state directory and a log
    file called after the component (*NAME-socat.log*). When powering
    off, the daemon is stopped.

    Anything coming of the *ipmitool's* *stderr* is sent to a file
    called *NAME-socat.stderr*.

    Specifying addresses is very specific to the usage that it is to
    be done of it, but for example:

    - ``PTY,link=console-%(component)s.write,rawer!!CREATE:console-%(component)s.read``

      creates a PTY which will pass whatever is written to
      ``console-COMPONENT.write`` to the second address and whatever
      is read from it to ``console-COMPONENT.read`` (!! serves like a
      bifurcator).

      Note you need to use *rawer* to ensure a clean pipe, otherwise
      the PTY later might add \\rs.

    - ``/dev/ttyS0,creat=0,rawer,b115200,parenb=0,cs8,bs1``

      opens a serial port and writes to it whatever is written to
      ``console-COMPONENT.write`` and anything that is read from the
      serial port will be appended to file ``console-COMPONENT.read``.

    - ``EXEC:'/usr/bin/ipmitool -H HOSTNAME -U USERNAME -E -I lanplus sol activate',sighup,sigint,sigquit``

      runs the program *ipmitool*, writes to *stdin* whatever is
      written to *console-COMPONENT.write* and whatever comes out of
      *stdout* is written to *console-COMPONENT.read*.

    Be wary of adding options such *crnl* to remove extra CRs (\\r)
    before the newline (\\n) when using to implement consoles. The
    console channels are meant to be completely transparent.

    For examples, look at :class:`ttbl.console.serial_pc` and
    :class:`ttbl.ipmi.sol_console_pc`.

    ** Catchas and Tricks for debugging **

    Sometimes it just dies and we are left wondering

    - prepend to *EXEC* *strace -fo /tmp/strace.log*, as in::

        EXEC:'strace -fo /tmp/strace.log COMMANDTHATDIES'

      find information in server's ``/tmp/strace.log`` when power
      cycling or enable top level calling under strace; it gets
      helpful.

    """

    def __init__(self, address1, address2, env_add = None,
                 precheck_wait = 0.2, extra_cmdline = None,
                 **kwargs):
        assert isinstance(address1, str)
        assert isinstance(address2, str)
        if extra_cmdline == None:
            extra_cmdline = []
        # extra_cmdline has to be before the address pair otherwise
        # it'll fail
        daemon_c.__init__(
            self,
            cmdline = [
                "/usr/bin/socat",
                "-lf", "%(path)s/%(component)s-%(name)s.log"
            ] + extra_cmdline + [
                # more than three -d's is a lot of verbosity, will
                # fill up the drive soon
                # FIXME: allow individual control/configure strace debug
                #  "-v", "-x", prints the data as it goes back and forth
                "-d", "-d",
                address1,		# will be formatted against kws
                address2,		# will be formatted against kws
            ],
            precheck_wait = precheck_wait,
            env_add = env_add,
            **kwargs)

    def verify(self, target, component, cmdline_expanded):
        # this is the log file name, that has been expanded already by
        # the daemon_c class calling start
        return os.path.exists(cmdline_expanded[2])
