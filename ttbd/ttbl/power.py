#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Control power to targets and general control for relays, buttons and jumpers
----------------------------------------------------------------------------

This interface provides means to power on/off targets and the invidual
components that compose the power rail of a target.

The interface is implemented by :class:`ttbl.power.interface` needs to
be attached to a target with :meth:`ttbl.test_target.interface_add`::

>>> ttbl.test_target.get(NAME).interface_add(
>>>     "power",
>>>     ttbl.power.interface(
>>>         component0,
>>>         component1,
>>>         ...
>>>     )

Generally, this interface can also be used to control any
instrumentation that has binary states (on/off, true/false,
connected/disconnected, pressed/released, etc..) such as:

- relays
- buttons
- jumpers (controlled by a relay)

by convention, the *buttons* and *jumpers* interfaces are exposed with
those names; thus, in a configuration :ref:`configuration file
<ttbd_configuration>`::

>>> ttbl.test_target.get(NAME).interface_add(
>>>     "buttons",
>>>     ttbl.power.interface(
>>>         power = ttbl.usbrly08b.pc("24234", 3),
>>>         reset = ttbl.usbrly08b.pc("24234", 4),
>>>         ...
>>>     )

would add two buttons, power and reset, controlled by a
:class:`USBRLY08B <ttbl.usbrly08b.pc>` relay bank (by wiring the NO and
NC lines through the button so that turning on/closing the relay
effectively presses the button).

Any other mechanism (and driver) to act on jumpers or buttons can be
implemented to provide the on/off operation that translates into
button press/release or jumper close/open.

Each component is an instance of a subclass of
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
import concurrent.futures
import errno
import json
import multiprocessing.process
import numbers
import os
import re
import time
import traceback
import types
import shutil
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

    :param bool ignore_get: when reading the state, ignore it
      and return *None* (not available)--this is normally used for
      power components which we want to manipulate but not care for
      the state.

    :param bool ignore_get_errors: if reading the state causes an
      error, ignore and return *None* (not available)

    :param str explicit: (optional, default *None*) declare if this power
      component shall be only turned on or off when explicitly named in
      a power rail. See :ref:ttbd_power_explicit.

      - *None*: for normal behaviour; component will be
         powered-on/started with the whole power rail

      - *both*: explicit for both powering on and off: only
        power-on/start and power-off/stop if explicity called by
        name

      - *on*: explicit for powering on: only power-on/start if explicity
        powered on by name, power off normally

      - *off*: explicit for powering off: only power-off/stop if explicity
        powered off by name, power on normally

    :param bool off_on_release: (optional; default *False*) turn off
      when the target is released; this is normally use for components
      that implement some kind of access control that should not be
      used once a machine is released.

    """
    def __init__(self, paranoid = False, explicit = None,
                 ignore_get = False, ignore_get_errors = False,
                 off_on_release = False):
        assert isinstance(paranoid, bool)
        assert isinstance(ignore_get, bool)
        assert isinstance(ignore_get_errors, bool)
        assert isinstance(off_on_release, bool)
        assert explicit in ( None, 'on', 'off', 'both' )
        #: If the power on fails, automatically retry it by powering
        #: first off, then on again
        self.power_on_recovery = False
        self.paranoid = paranoid
        self.timeout = 10	# used for paranoid checks
        self.wait = 0.5
        self.explicit = explicit
        self.ignore_get = ignore_get
        self.ignore_get_errors = ignore_get_errors
        self.off_on_release = off_on_release
        #: for paranoid power getting, now many samples we need to get
        #: that are the same for the value to be considered stable
        self.paranoid_get_samples = 6
        ttbl.tt_interface_impl_c.__init__(self)


    def target_setup(self, target, iface_name, component):
        assert component not in ( 'all', 'full' ), \
            f"{component}: invalid power component name, reserved"
        assert self.explicit in ( None, 'on', 'off', 'both' ), \
            f"{component}: invalid 'explicit' value '{self.explicit}';" \
            " expected None, 'on', 'off' or 'both'"


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
        """Return the component's power state

        Same parameters as :meth:`on`

        WARNING! This function can be called fro multiple *processes*
        (not threads, we never do threads) at the same time, so if
        there is common resource access, you might have to protect it,
        eg: to access a serial port

        >>> tty_dev_base = os.path.basename(tty_dev)
        >>> try:
        >>>     with ttbl.process_posix_file_lock_c(
        >>>              f"/var/lock/LCK..{tty_dev_base}", timeout = 2), \
        >>>          serial.Serial(tty_dev, baudrate = 9600,
        >>>                        bytesize = serial.EIGHTBITS,
        >>>                        parity = serial.PARITY_NONE,
        >>>                        stopbits = serial.STOPBITS_ONE,
        >>>                        # .5s for timeout to avoid getting stuck,
        >>>                        # which will trigger the watchdog
        >>>                        timeout = 0.5) as s:
        >>>         # do something with s
        >>>         ...
        >>>         return response
        >>>
        >>> except ttbl.process_posix_file_lock_c.timeout_e:
        >>>     target.log.error(
        >>>         f"{tty_dev_base}: timed out acquiring lock for blahbla")
        >>>     return no state or re-raise, etc

        Retrying is ok, but don't take more than two seconds.

        :returns: power state:

          - *True*: powered on

          - *False*: powered off

          - *None*: this is a *fake* power unit, so it has no actual
            power state

        """
        raise NotImplementedError("%s/%s: getting power state not implemented"
                                  % (target.id, component))



def _impl_get_trampoline(fn_impl_get: callable, impl: impl_c,
                         target: ttbl.test_target, component: str) -> tuple:
    try:
        return fn_impl_get(impl, target, component), None, None
    except Exception as e:
        # we can't pickle tracebacks, so we send them as a
        # formated traceback so we can at least do some debugging
        tb = traceback.format_exception(type(e), e, e.__traceback__)
        return None, e, tb



class interface(ttbl.tt_interface):
    """
    Power control interface

    Implements an interface that allows to control the power to a
    target, which can be a single switch or a whole power rail of
    components that have to be powered on and off in an specific
    sequence.
    """

    def __init__(self, *impls, get_parallel: bool = False, **kwimpls):
        # in Python 3.6, kwargs are sorted; but for now, they are not.
        ttbl.tt_interface.__init__(self)
        # we need an ordered dictionary because we need to iterate in
        # the same order as the components were declared--as that is
        # what the user dictates. Because the power on/off order of
        # each rail component matters.
        self.impls_set(impls, kwimpls, impl_c)
        self.get_parallel = get_parallel



    def _target_setup(self, target, iface_name):
        # Called when the interface is added to a target to initialize
        # the needed target aspect (such as adding tags/metadata)
        for name, impl in self.impls.items():
            # check this here so if the impl doesn't inherit
            # ttbl.power.impl_c, it is still checked
            assert name not in ( 'all', 'full' ), \
                "power component '%s': cannot be called '%s'; name reserved" \
                % (name, name)
            assert impl.explicit in ( None, 'on', 'off', 'both' ), \
                "power component '%s': impls' explicit value is %s;" \
                " expected None, 'on', 'off' or 'both'" % (name, impl.implicit)
            impl.target_setup(target, iface_name, name)

    def _release_hook(self, target, _force):
        # nothing to do on target release
        # we don't power off on release so we can pass the target to
        # someone else in the same state it was
        for component, impl in self.impls.items():
            if impl.off_on_release:
                target.log.info(f"{component}: powering off upon release")
                impl.off(target, component)
                target.log.info(f"{component}: powered off upon release")


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
        if impl.ignore_get:
            return None
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
        while ts - ts0 < impl.paranoid_get_samples * impl.timeout:
            result = impl.get(target, component)
            ts = time.time()
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
            % (component, ts - ts0, " ".join(str(r) for r in results)))


    def _get(self, target, impls = None, whole_rail: bool = True):
        # get the power state for the target's given power components,
        # keep data ordered, makes more sense
        data = collections.OrderedDict()
        if impls == None:	# none give, do the whole power rail
            impls = iter(self.impls.items())
            whole_rail = True
        normal = {}
        explicit = {}
        explicit_on = {}
        explicit_off = {}

        impls_non_aliased = {}
        for component, impl in impls:
            if component in self.aliases:
                component = self.aliases[component]
            impls_non_aliased[component] = impl

        # ugly trick: remove current processes's daemon setting to
        # fake the concurrent futures processpoolexecutor, which
        # as of Pyhton 3.11 doesn't allow them for unknown reaosns
        # and in Stackoverflow everyone and their mum just fakes
        # it. Note we'll reset it later  in the finally block
        current_process = multiprocessing.process.current_process()
        _config = getattr(current_process, "_config", None)
        daemon_orig = _config.get('daemon', None)
        _config['daemon'] = False


        if not self.get_parallel:
            # Run serially all the get operations
            #
            # We still default to this since we are having issues in
            # parallelizing / pickling, it trips in SSLcontexts which
            # we are not sure where it comes from.
            for component, impl in impls_non_aliased.items():
                # need to get state for the real one!
                if component in self.aliases:
                    component_real = self.aliases[component]
                else:
                    component_real = component
                try:
                    state = self._impl_get(impl, target, component_real)
                except impl.error_e as e:
                    if not impl.ignore_get_errors:
                        raise
                    # if this is an explicit component, ignore any errors
                    # and just assume we are not using this for real power
                    # control
                    target.log.error(
                        "%s: ignoring power state error from explicit power component: %s"
                        % (component, e))
                    state = None
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

        else:
            # Run in parallel all the get operations: this way very large
            # power rails (which can happen once you add different
            # components and detectors and retries) are not that painful
            # to run frequently.
            #
            # Note the get() operations are mostly I/O bound, but still we
            # use processes rather than threads, so we are not contenting
            # for the Python GIL and they are truly running in parallel
            executor = concurrent.futures.ProcessPoolExecutor(len(impls_non_aliased))
            try:

                futures = {
                    # for each target id, queue a thread that will call
                    # _run_on_by_targetid(), who will call fn taking care
                    # of exceptions

                    # self.aliases.get(component, component): gets the real
                    # component name if there is an alias; if there is no alias, we just use
                    # the component name we got
                    component: executor.submit(_impl_get_trampoline, self._impl_get,
                                               impl, target, component)
                    for component, impl in impls_non_aliased.items()
                }

                for component in futures:
                    impl = self.impls[component]
                    try:
                        state, e, tb = futures[component].result()
                    except Exception as e:
                        target.log.error(
                            "BUG!? %s: exception getting _get() result: %s",
                            component, e, exc_info = True)
                        continue
                    if e:
                        # if the call to _get() for the driver got an issue
                        if not impl.ignore_get_errors:
                            raise
                        # if this is an explicit component, ignore any errors
                        # and just assume we are not using this for real power
                        # control
                        target.log.error(
                            "%s: ignoring power state error from explicit"
                            " power component: %s: %s",
                            component, e, tb)
                        state = None
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
                executor.shutdown(wait = True)
            finally:
                _config['daemon'] = daemon_orig

        # What state are we in?
        #
        # See 'Overall power state and explicit power components'
        # above, but basically we need to report:
        #
        #  state: True (on) or False (off)
        #  substate: 'normal', 'full', 'partial'
        #
        if all(i in [ True, None ] for i in list(normal.values()) + list(explicit_off.values())):
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

        if whole_rail and getattr(ttbl.tls, 'interface', None) == "power":
            # update full power state in inventory ONLY if we are
            # using this call in the *power* interface (eg not as part
            # of the *buttons* interface)
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
        _state, data, _substate = self._get(target, impls, whole_rail)

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
            try:		        # we retry power off twice
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
        if whole_rail and getattr(ttbl.tls, 'interface', None) == "power":
            # update full power state in inventory ONLY if we are
            # using this call in the *power* interface (eg not as part
            # of the *buttons* interface)
            target.fsdb.set('interfaces.power.state', False)
            target.fsdb.set('interfaces.power.substate',
                            "full" if explicit else "normal")
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
        _state, data, _substate = self._get(target, impls, whole_rail)

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
                continue	        # fallthrough is error recovery

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
                        % (why, retries)) from e
                target.log.error("%s: power-on%s failed: retrying (%d/%d) "
                                 "the whole power rail: %s",
                                 component, why, retries, retries_max, e)
                try:
                    # power off the whole given rail, but no pre/post
                    # execution, since we are just dealing with the components
                    self._off(target, impls,
                              " (retrying because %s failed)" % component,
                              False)
                except:		        # pylint: disable = bare-except
                    pass	        # yeah, we ignore errors here
                index = 0	        # start again
                if e.wait:
                    time.sleep(e.wait)
                continue	        # fallthrough is error recovery!

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
                try:		        # Let's retry
                    self._impl_on(impl, target, component_real)
                    continue	        # good, it worked
                except Exception as e:
                    target.log.error(
                        "%s: power-on%s failed (again): aborting: %s"
                        % (component, why, e))
                    try:	        # ok, not good, giving up
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
        if not isinstance(why, str):
            raise TypeError(type(why))
        target.log.info("powered on%s" % why)
        if whole_rail and getattr(ttbl.tls, 'interface', None) == "power":
            # update full power state in inventory ONLY if we are
            # using this call in the *power* interface (eg not as part
            # of the *buttons* interface)
            target.fsdb.set('interfaces.power.state', True)
            target.fsdb.set('interfaces.power.substate',
                            "full" if explicit else "normal")
            target.fsdb.set('powered', "On")


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
            wait = float(target.tags.get('power_cycle_wait', 0))
        if wait == 0:
            wait = float(target.tags.get('interfaces.power.cycle_wait', 10))
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

            if action not in [ 'on', 'press', 'close',
                               'off', 'release', 'open',
                               'cycle' ]:
                raise ValueError(
                    "%s: sequence #%d: invalid action spec; "
                    " expected on|press|close|off|release|open|cycle; got %s"
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
            if action in ( 'on', 'press', 'close' ):
                self._on(target, impls, f" (because sequenced '{s}')",
                         _all, explicit)
            elif action in ( 'off', 'release', 'open' ):
                self._off(target, impls, f" (because sequenced '{s}')",
                          _all, explicit)
            elif action == 'cycle':
                wait = float(target.tags.get('power_cycle_wait', 2))
                self._off(target, impls, f" (because sequenced '{s}')",
                          _all, explicit)
                if wait:
                    time.sleep(wait)
                self._on(target, impls, f" (because sequenced '{s}')",
                         _all, explicit)
            else:
                raise RuntimeError(
                    "%s: unknown action"
                    " (expected on|press|close|off|release|open|cycle)"
                    % action)



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

            if action not in [ 'on', 'press', 'close',
                               'off', 'release', 'open',
                               'cycle' ]:
                raise ValueError(
                    "%s%s: sequence #%d: invalid action spec; "
                    " expected on|press|close|off|release|open|cycle; got %s"
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

    :param str iface_name: (optional; default *power*) name of the
      interface where this is being used.

      Implementations have no way to know which interface they are
      being used for (needing for setting state in the right
      location), so if used in other interface than *power* (default),
      use paramer *iface_name*.

    :param float delay: (optional, default 0) time in seconds to delay
      all operations

    Parameters are the same as for :class:impl_c.

    """
    def __init__(self, name = None, iface_name = "power",
                 delay: float = 0, **kwargs):
        impl_c.__init__(self, **kwargs)
        if name == None:
            name = "%x" % id(self)
        self.name = name
        self.iface_name = iface_name
        self.delay = delay
        self.upid_set("Fake power controller #%s" % name,
                      name = name, iface_name = iface_name)

    # State is stored in interfaces.power.COMPONENT, so it in the
    # right inventory in the namespace and it doesn't collide with
    # *state*, which is set by the upper layers.
    def on(self, target, component):
        delay = float(target.fsdb.get(
            f"interfaces.{self.iface_name}.{component}.delay", self.delay))
        target.log.warning(f"fake_c powering {component} ON after {delay}s")
        time.sleep(delay)
        target.fsdb.set(
            'interfaces.%s.%s.fake-state' % (self.iface_name, component), True)
        target.log.warning(f"fake_c powered {component} ON after {delay}s")

    def off(self, target, component):
        delay = float(target.fsdb.get(
            f"interfaces.{self.iface_name}.{component}.delay", self.delay))
        target.log.warning(f"fake_c power {component} OFF after {delay}s")
        time.sleep(delay)
        target.fsdb.set(
            'interfaces.%s.%s.fake-state' % (self.iface_name, component), None)
        target.log.warning(f"fake_c powered {component} OFF after {delay}s")

    def get(self, target, component):
        delay = float(target.fsdb.get(
            f"interfaces.{self.iface_name}.{component}.delay", self.delay))
        target.log.warning(f"fake_c power {component} getting after {delay}s")
        time.sleep(delay)
        state = target.fsdb.get(
            'interfaces.%s.%s.fake-state' % (self.iface_name, component))
        target.log.warning(f"fake_c power {component} get after {delay}s")
        return state == True


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
        # FIXME: upid set from pc, negating

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

# FIXME: daemon_c and daemon_podman_container_c need to be split into
# a third base class containing all the basic functionality shared by
# both (commonl.kws_expand and friends, verify prototypes, verify_timeout,
# etc)
class daemon_c(impl_c):
    """Generic power controller to start daemons in the server machine

    FIXME: document

    :param list(str) cmdline: command line arguments to pass to
      :func:`subprocess.check_output`; this is a list of
      strings, first being the path to the command, the rest being the
      arguments.

      All the entries in the list are templated with *%(FIELD)s*
      expansion, where each field comes either from the *kws*
      dictionary or the target's metadata.

    :param str path: (optional; defaults to first component of command
      line) Path to the binary to execute.

      .. warning:: this might be fully deprecated, since its use has
                   been taken over by *check_path*

    :param str check_path: (optional; defaults to *path*) binary path
      to use when checking if the process is alive.

      Some processes, after starting with a given binary, fork and
      transform into another (eg: */usr/bin/program1* forks into
      */usr/bin/program2* which runs for a long time). To check if the
      component is running, we check for the PID we are monitoring
      corresponding to */usr/bin/program2* instead of *program1*.

    :param str name: (optional) name of this component; defaults to
      the basename of the path to run.

      eg: if calling */usr/bin/somedaemon*, name would be *daemon*.

    :param bool mkpidfile: (optional; default *True*) create a pidfile
      when the process starts, using as name/template the value of
      *pidfile*.

    :param str pidfile: (optional) pidfile name (template); defaults
      to "PATH/COMPONENT-NAME.pid". *PATH* is the state directory for
      the given target (usually
      */var/lib/ttbd/instance/targets/TARGETNAME*). *COMPONENT* is the
      component under which this driver has been registered when
      adding to the interface. *NAME* is the name of this driver
      instance, see above.

    :param bool close_fds: (optional; default *True*) close or not all
      file descriptors before running the command; see
      :python:`subprocess.Popen` for more information.

      If set to *False*, you can select which file descriptors are
      kept open with:

      >>> os.setinheritable(FD, True)

    :param bool kill_before_on: (optional; default *True*) before
      starting the process, kill any possible process that is running
      with the same command line and if any, report it as a possible
      bug.

    :param str stderr_name: (optional) set a template for the name of
      the file that will contain the stderr for the daemon.

      Defaults to TARGETSTATEDIR/COMPONENT-NAME.stderr

      Can be set before calling :meth:`on`

    Other parameters as to :class:ttbl.power.impl_c.

    The *kws* member are keywords that can be used to expand the
    command line; before calling :meth:`on`, they'll be expanded with
    the target's keywords. This process is currently a wee messy,
    since it just brings the whole inventory and in most cases there
    is no need for all of it.
    """
    #: KEY=VALUE to add to the environment
    #: Keywords to add for templating the arguments
    def __init__(self, cmdline,
                 precheck_wait = 0, env_add = None, kws = None,
                 path = None, check_path = None, name = None,
                 pidfile = "%(path)s/%(component)s-%(name)s.pid",
                 mkpidfile = True, paranoid = False,
                 close_fds = True, kill_before_on: bool = True,
                 stderr_name: str = None,
                 **kwargs):
        assert isinstance(cmdline, list), \
            "cmdline has to be a list of strings; got %s" \
            % type(cmdline).__name__
        assert precheck_wait >= 0
        assert isinstance(close_fds, bool)
        assert isinstance(kill_before_on, bool)
        assert pidfile == None or isinstance(pidfile, str)

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
        if env_add != None:
            commonl.assert_dict_of_strings(env_add, "env_add")
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
        if check_path == None:
            self.check_path = self.path
        else:
            assert isinstance(check_path, str) and os.path.isfile(check_path), \
                f"{check_path}: invalid file or non existing"
            self.check_path = check_path
        if name == None:
            self.name = os.path.basename(self.path)
        else:
            assert isinstance(name, str)
            self.name = name
        self.pidfile = pidfile
        assert isinstance(mkpidfile, bool)
        self.mkpidfile = mkpidfile
        self.close_fds = close_fds
        self.stdin = None
        self.kill_before_on = kill_before_on
        #: Name template for the file to use to dump the process's
        #: stderr; can be set before calling on(); can be templated
        #: with kws
        self.stderr_name = stderr_name



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


    def _cmdline_expand(self, target, kws, cmdline):
        _cmdline = []
        count = 0
        try:
            for i in cmdline:
                _cmdline.append(commonl.kws_expand(i, kws))
                count += 1
        except KeyError as e:
            message = "configuration error? can't template command line #%d," \
                " missing field or target property: %s" % (count, e)
            target.log.error(message)
            raise self.power_on_e(message)
        return _cmdline


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

        kws = dict(target.kws)
        if self.kws:
            kws.update(self.kws)
        kws.update(self.upid)
        kws.setdefault('name', self.name)
        # bring in runtime properties (override the rest)
        kws.update(target.fsdb.get_as_dict())
        kws['component'] = component

        # render the stderr file name, so a using class can override it
        if self.stderr_name == None:
            self.stderr_name = os.path.join(
                target.state_dir, component + "-" + self.name + ".stderr")

        # render the real commandline against kws
        _cmdline = []
        count = 0
        try:
            for i in self.cmdline + self.cmdline_extra:
                # some older Linux distros complain if this string is unicode
                _cmdline.append(str(commonl.kws_expand(i, kws)))
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
            for k, v in self.env_add.items():
                env[k] = commonl.kws_expand(v, kws)
        else:
            env = os.environ
        if self.pidfile:
            pidfile = self.pidfile % kws
            commonl.rm_f(pidfile)
        else:
            pidfile = None
        stderrf = open(commonl.kws_expand(self.stderr_name, kws), "w+")

        if self.kill_before_on:
            def _go_for_the_kill(cmdline_check):
                pids = commonl.kill_by_cmdline(" ".join(cmdline_check))
                if pids:
                    target.log.error(
                        f"BUG? {component}/on: killed PIDs '{pids}'"
                        f" with the same command line: {_cmdline}")
            # some daemons will set a different process as name and
            # some depending on the color of the moon, will use either
            # depdending on what state of stuckness they are so...do both
            _go_for_the_kill(_cmdline)
            if self.path and self.path != _cmdline[0]:
                _go_for_the_kill([ self.path ] + _cmdline[1:])
            if self.check_path \
               and self.check_path != self.path \
               and self.check_path != _cmdline[0]:
                _go_for_the_kill([ self.check_path ] + _cmdline[1:])

        try:
            p = subprocess.Popen(_cmdline, env = env, cwd = target.state_dir,
                                 stdout = stderrf, close_fds = self.close_fds,
                                 stdin = self.stdin,
                                 stderr = subprocess.STDOUT, bufsize = 0,
                                 shell = False,
                                 universal_newlines = False)
            if pidfile and self.mkpidfile:
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
        pid = commonl.process_started(pidfile, self.check_path,
                                      component + "-" + self.name, target.log,
                                      self.verify,
                                      ( target, component, _cmdline, ))
        if pid == None:
            self.log_stderr(target, component, stderrf)
            raise self.power_on_e("%s: %s failed to start"
                                  % (component, self.name))
        if pid != None and pid > 0:
            ttbl.daemon_pid_add(pid)


    def off(self, target, component):
        kws = dict(target.kws)
        if self.kws:
            kws.update(self.kws)
        kws.update(self.upid)
        kws.setdefault('name', self.name)
        # bring in runtime properties (override the rest)
        kws.update(target.fsdb.get_as_dict())
        kws['component'] = component
        pidfile = self.pidfile % kws
        try:
            commonl.process_terminate(pidfile, path = self.check_path,
                                      tag = component + "-" + self.name)
        except OSError as e:
            if e != errno.ESRCH:
                raise


    def get(self, target, component):		# power interface
        kws = dict(target.kws)
        if self.kws:
            kws.update(self.kws)
        kws.update(self.upid)
        kws.setdefault('name', self.name)
        # bring in runtime properties (override the rest)
        kws.update(target.fsdb.get_as_dict())
        kws['component'] = component
        return commonl.process_alive(self.pidfile % kws, self.check_path) != None


# derive daemon_c so we get verify()  and
# _cmdline_expand(), but we re-do most
class daemon_podman_container_c(daemon_c):
    """Run a daemon inside a Podman container

    A container is spun to execute a command (usually a long standing
    service provider) isolated from the main system

    >>> pc = ttbl.power.daemon_podman_container_c(
    >>>     "SOMENAME",
    >>>     cmdline = [
    >>>         "fedora:34",
    >>>         "/bin/ls", "-l",
    >>>     ]
    >>> )

    :param str name: name given to the container, will be
      passed to *podman run*

    :param list(str) cmdline: command line to add to *podman run* (see
      below); example:

    :param dict env_add: environment variables to add to the container
      (will be passed with *-e* to *podman run*).

    Other parameters as to :class:`ttbl.power.impl_c`.

    The container:

    - is run a child of the daemon process if not using *-d*, thus if
      the process is killed, the container is killed too.

    - a container name is composed by adding the target name and
      component to the *name* parameter to generate
      *TARGETNAME_COMPONENT_NAME*

    **Debugging**

    To find running containers, as *root* or user running the
    daemon, issue::

      $ podman ps
      CONTAINER ID  IMAGE   COMMAND               CREATED             STATUS                 PORTS                   NAMES
      c379aedfed4b          rpyc_classic --ho...  About a minute ago  Up About a minute ago  0.0.0.0:3003->3003/tcp  t0_aa0_SOMENAME

    To run a shell inside the container, run either::

      $ podman exec -ti c379aedfed4b /bin/bash
      $ podman exec -ti tt_aa0_SOMENAME /bin/bash

    **Configuration tips**

    In general, except for very basic configurations, you might need
    to subclass the container class to set container configurations.

    >>> class my_class(ttbl.power.daemon_container_c):
    >>>
    >>>     def __init__(self, myparams, **kwargs):
    >>>         ...verify and set myparams...
    >>>         ttbl.power.daemon_container_c.__init__(self, **kwargs)
    >>>         self.upid_set("LONG NAME", data1=val1, data2 = val2
    >>>
    >>>     def on(self, target, component):
    >>>         ...determine runtime info, set self.kws

    - *Add an image*: if you don't want to use / can use an image
      available on a registry (summary of
      https://www.redhat.com/sysadmin/building-buildah) create a file
      called *image.Dockerfile* with::

        FROM centos:8
        RUN dnf install -y python36 usbutils strace
        RUN dnf clean all

      and run to create an image named *centos8python36*::

        $ buildah bud -f image.Dockerfile -t centos8python36
        $ podman run localhost/centos8python36 echo "I work"

      This then can be fed to the podman command line as
      *localhost/centos8python36*

      >>> cmdline = [
      >>>     ...,
      >>>     # these two have to be the last arguments
      >>>     "localhost/centos8python36",
      >>>     COMMANDTOEXECUTEINTHECONTAINER,
      >>>     ARG1, ARG2,...
      >>> ]

    - *Capturing output to consoles*: the output of the container is
      captured to a file called *COMPONENTNAME.stderr* in the target's
      state directory.

      It can be exposed as a console via the console interface by
      adding to the target object:

      >>> target.interface_impl_add(
      >>>     "console", "log_COMPONENTNAME",
      >>>     ttbl.console.logfile_c("COMPONENTNAME-CONTAINERNAME.stderr"))

    - *Exposing network ports*: the default container configuration
      allows the container to access the host network. To expose ports
      from inside the container in the host, specify the *--publish*
      command line option:

      >>> cmdline = [
      >>>     ...,
      >>>     "--publish", "PORT_HOST:PORT_CONTAINER",
      >>>     ...,
      >>> ]

    - *Exposing other host directories to the container*: using the
      container's *-v|--volume* option:

      >>> cmdline = [
      >>>     ...,
      >>>     # expose /opt/somedir as readonly from
      >>>     # /opt/somedir/*someversion* take *someversion* from self.kws
      >>>     "--volume=/opt/somedir/%(someversion)s:/opt/somedir:ro",
      >>>     # expose as readonly, take *someversion* from self.kws
      >>>     "--volume=/opt/somedir/%(someversion)s:/opt/somedir:ro",
      >>>     ...,
      >>> ]

      Some of the options to be added:

      - *rw* / *ro*: give read/write or read/only access

      - *O*: give overlay access (host is read only, container is
        read-write and changes get discarded when the container is
        destroyed)

      See *podman-run*'s man page for more information and other
      settings

    - *Exposing hardware devices*

      The container can access hardware devices, as long as:

      1. the user the daemon runs under has permission to access the
         device

      2. the container has to be given the right command lines to
         acces it (*--device*, *--volume*); for example, for passing
         access to a device, given its serial number, we need to find
         its */dev/usb/bus/BUSNUMBER/DEVICENUMBER* path and its
         */sys/bus/usb* path

         >>> cmdline = [
         >>>     ...,
         >>>
         >>>     "--device=%(device_path)s:%(device_path)s:rwm",
         >>>     "--volume=%(device_syspath)s:%(device_syspath)s",
         >>>     ...,
         >>> ]

         Those paths (*device_path* and *device_syspath*) are
         published in the *self.kws* in the *on* method, since they
         have to be found upon runtime:

         >>>     def on(self, target, component):
         >>>         ...
         >>>         syspath, busnum, devnum = ttbl.usb_device_by_serial(
         >>>             self.usb_serial_number, None, "busnum", "devnum"
         >>>         )
         >>>         if syspath == None or busnum == None or devnum == None:
         >>>             raise RuntimeError(
         >>>                 f"Cannot find USB device with serial {self.usb_serial_number}")
         >>>        ...
         >>>        self.kws = {
         >>>            # Keywords for mapping a USB device
         >>>            "device_path": f"/dev/bus/usb/{int(busnum):03d}/{int(devnum):03d}",
         >>>            "device_syspath": syspath,
         >>>            ...,
         >>>        }
         >>>        ttbl.power.daemon_podman_container_c.on(self, target, component)

         See example implementation at FIXME.

    3. Other command line additions:

       - *--restart*: restart on failure, note it might conflict with *--rm*

         >>>         cmdline = [
         >>>             ...,
         >>>             # "always" conflicts with --rm; this is enough to
         >>>             # restart when running in forking --mode (see below)
         >>>             # even adding :COUNT conflicts with --rm...hmm
         >>>             "--restart", "on-failure",
         >>>             ...,
         >>>        ]

       - *--cap-add*: if you need to debug

         >>>         cmdline = [
         >>>             ...,
         >>>             # allow strace for debugging and others etc
         >>>             "--cap-add=SYS_PTRACE",
         >>>             ...,
         >>>        ]



    **System Setup**

    This driver requires the podman package being installed in the
    server::

      $ sudo dnf install -y podman

    Ensure the user that runs the daemon has SUBUIDs::

      $ sudo usermod --add-subuids 10000-65536 --add-subgids 10000-65536 ttbd

      $ sudo -u ttbd podman system migrate
      $ sudo -u podman unshare cat /proc/self/uid_map
      0        991          1
      1      70000     100001
      $ FIXME

    **Troubleshooting**

    - If the container system for the user is all messed up, the
      username can be wiped up::

        $ sudo su - DAEMONUSER    # become the user that runs the daemon
        $ rm -rf ~DAEMONUSER/.{config,local/share}/containers
        $ rm -rf /run/user/DAEMONUSER/{libpod,runc,vfs-*}
        $ podman unshare rm -rf .{config,local/share}/containers

    **FIXME/PENDING**

    - use podman python library instead of shell

    - expose the container ID in
      interfaces.INFACENAME.COMPONENT.container_id when started

    """

    def __init__(self,
                 name: str, cmdline: list,
                 precheck_wait: float = 0,
                 env_add: dict = None,
                 rm_container: bool = True,
                 **kwargs):
        commonl.verify_str_safe(name, do_raise = False, name = "name")
        commonl.assert_list_of_strings(cmdline, "command line", "command")
        assert isinstance(precheck_wait, numbers.Real) and precheck_wait >= 0
        assert isinstance(rm_container, bool)

        # we don't really use this except for the verify definition
        daemon_c.__init__(self, cmdline, env_add = env_add, **kwargs)

        if env_add != None:
            commonl.assert_dict_of_strings(env_add, "environment variables")
            self.env_add = dict(env_add)	# copy so we avoid manipulation
        else:
            self.env_add = dict()
        self.precheck_wait = precheck_wait
        self.rm_container = rm_container

        self.cmdline = cmdline

        self.name = name
        self.kws = None		        # on() defines as a dict
        self.upid_set(
            f"Podman container #{name}",
            name = name,
            cmdline = ' '.join(cmdline),
        )


    #: Path to use to call podman
    path_podman = "/usr/bin/podman"

    #: Minimum container speficification
    #:
    #: This tries to have all the dependencies that we'd use on most
    #: drivers that run containers, to have a common image.
    #:
    #: This can be fed to commonl.buildah_image_create() to generate
    #: the image upon server configuration.
    #:
    #: crontabs -> run-parts
    dockerfile = """
FROM fedora-minimal
RUN \
     microdnf install -y \
         crontabs \
         findutils \
         procps \
         python3-rpyc \
         strace \
         usbutils; \
     microdnf clean all
"""

    def _cmdline_run(self, target, component, cmdline, env = None):
        # call it only after the component, so it is easier to
        # reference then when using the logfile_c driver to expose
        # it as a console
        stderrf_name = os.path.join(target.state_dir,
                                    f"{component}-{self.name}.stderr")

        stderrf = open(stderrf_name, "w+")	# passed to subprocess
        try:
            p = subprocess.Popen(cmdline, env = env, cwd = target.state_dir,
                                 close_fds = True,
                                 stdin = None,
                                 stdout = stderrf, stderr = subprocess.STDOUT,
                                 bufsize = 0,
                                 shell = False, universal_newlines = False)
            del stderrf
            return p
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
                for i in cmdline:
                    target.log.error(
                        "cmdline #%d: [%s] %s", count, type(i).__name__, i)
                    count += 1
                for key, val in env.items():
                    target.log.error(
                        "env %s: [%s] %s", key, type(val).__name__, val)
            raise
        except OSError as e:
            raise self.power_on_e("%s: %s failed to start [cmdline %s]: %s" % (
                component, self.name, " ".join(cmdline), e))


    # FIXME: replace with commonl.verify_timeout()
    def _verify_timeout(self, target, component, timeout,
                        verify_f,
                        *verify_args,
                        poll_period = 0.25,
                        **verify_kwargs):
        # Well, not verify if it is running
        t0 = t = time.time()
        while True:
            if t - t0 > timeout:
                target.log.error(
                    "%s: verifying with %s timed out at +%.1f/%.1d",
                    self.name, verify_f, t - t0, timeout)
                self.log_stderr(target, component)
                raise self.power_on_e("%s: %s failed to start"
                                      % (component, self.name))
            if verify_f(*verify_args, **verify_kwargs):
                target.log.info(
                    "%s: verified at +%.1f/%.1fs",
                    self.name, t - t0, timeout)
                break
            time.sleep(poll_period)		# Give it .1s to come up
            t = time.time()


    def on(self, target, component):
        # Deck of fields to replace in the command line and env vars
        #
        # FIXME: this kws setting shall match daemon_c.on's prefix
        kws = dict(target.kws)
        if self.kws:
            kws.update(self.kws)
        kws.update(self.upid)
        # bring in runtime properties (override the rest)
        kws.update(target.fsdb.get_as_dict())
        kws['component'] = component

        # Start the command line with 'podman run'
        cmdline = [
            self.path_podman,
            # FIXME: runc gives a unix socket too long error
            "--runtime", "crun",
            "run",
            "--name", f"{target.id}_{component}",
            "--annotation", "run.oci.keep_original_groups=1",
        ]
        if self.rm_container:
            cmdline.append("--rm")

        # Add environment
        for name, val in self.env_add.items():
            cmdline.append("-e")
            cmdline.append(f"{name}={commonl.kws_expand(val, kws)}")

        # append the stuff from the user after "podman run [-e
        # KEY=VAL [...]]", expanding the fields
        cmdline += self._cmdline_expand(target, kws, self.cmdline)
        target.log.info("%s: command line: %s"
                        % (component, " ".join(cmdline)))

        console_name = "log-" + component
        if hasattr(target, "console"):
            try:
                target.console.impl_get_by_name(console_name, "console")
                # console for the log file has been registered
                ttbl.console_generation_set(target, console_name)
            except IndexError:
                # console is not registered, skip
                pass

        # remove leftovers--the power subsystem will only call this if
        # we really have to power on, so if there is something half
        # way there, *we want it dead first* -- and sometimes it does
        # happen.
        self.off(target, component)
        self._cmdline_run(target, component, cmdline)

        if self.precheck_wait:
            time.sleep(self.precheck_wait)

        # Verify the container started
        self._verify_timeout(target, component, 3,
                             self.get, target, component, )

        # Verify the container is functional
        self._verify_timeout(target, component, 3,
                             self.verify, target, component, cmdline)


    def off(self, target, component):
        # kill the container
        try:
            subprocess.run([ "podman", "kill", "--signal", "KILL",
                            f"{target.id}_{component}" ],
                        # don't check -- if it fails, prolly off already
                        timeout = 5, check = False)
        except subprocess.TimeoutExpired:
            # If killing the container fails and times out,
            # try stopping the container as an alternative
            subprocess.run(["podman", "stop", f"{target.id}_{component}"],
                           timeout = 5, check = False)

        # really really kill it
        #
        # force removal of the container until there is nothing left
        # and try multiple times, since sometimes things get left
        # lingering even when we know they should not but yeah it
        # happens
        top = 5
        for _cnt in range(1, top + 1):
            # call repeatedly until it reports empty, meaning the
            # container is fully dead
            r = subprocess.run(
                [ "podman", "rm", "--ignore", "--force", f"{target.id}_{component}" ],
                timeout = 5, check = False, capture_output = True, text = True)
            if not r.stdout.strip():
                # if podman rm -fi doesn't return anything, it means
                # the container is solid dead and we are good to go
                break
        else:
            raise RuntimeError(
                f"{target.id}_{component}: timed out forcibly killing"
                f" container after {top} tries")


    def get(self, target, component):
        # check if the container is running by just listing the
        # container we the name we gave it -- if it shows in the
        # command output, then we are good.
        #
        # note we filter only running containers and JUST the one
        # we named -- if someone else creates a container with the
        # same name this would fail but we are not doing that.
        output = subprocess.check_output(
            [
                "podman", "ps",
                "--filter", f"name={target.id}_{component}",
                "--filter", "status=running",
                # yup, Names...not Name, because they might have many
                "--format", "{{.Names}}",
            ],
            timeout = 5)
        return f"{target.id}_{component}".encode("ascii") in output


    def verify(self, target, component, cmdline_expanded):
        """
        Verify the container is running

        Can be overriden to do any other checks

        :returns bool: *True* if the service is working as expected
          (eg: a port is open)
        """
        return True


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
        cmdline_s = " ".join(self.cmdline)
        if condition_msg == None:
            self.condition_msg = "'%s' returns %d" % (
                cmdline_s, expected_retval)
        else:
            self.condition_msg = condition_msg
        self.cwd = cwd
        self.env = env
        self.expected_retval = expected_retval
        self.when_on = when_on
        self.when_off = when_off
        self.poll_period = poll_period
        self.timeout = timeout
        self.upid_set(
            "Delayer until command '%s' returns %d,"
            " checking every %.2fs timing out at %.1fs" % (
                cmdline_s, expected_retval, poll_period, timeout),
            command = cmdline_s,
            expected_retval = expected_retval,
            poll_period = poll_period,
            timeout = timeout)

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
            ts = time.time()
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
            ts = time.time()
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


class rpyc_c(daemon_podman_container_c):
    """Expose a containeraized Python environment in the server to client via RPYC

    This driver is used to expose RPYC servers that that allows us to
    execute Python code in the server environment
    (https://rpyc.readthedocs.io/en/latest/).

    When started, it starts a server in the server that listens on a
    TCP port (by default wrapped over SSL). The client then can
    connect to it and instantiate Python objects in the environment
    and call them / use them as if it was local. For example:

    >>> import rpyc
    >>> remote = rpyc.ssl_connect(HOSTNAME, PORTNUMBER)
    >>> with remote.builtins.open("somefile", "w") as f:
    >>>    f.write("hello")

    Creates a file *somefile* in the target environment.

    .. note: this can open security issues and to avoid such, this
             environment is by default run inside a rootless container
             using podman.

    The function :func:`tcfl.tl.rpyc_connect` returns a ready to use
    remote connection object given a target and the component name for the
    target (which is assumed in the *power* interface):

    >>> remote = tcfl.tl.rpyc_connect(target, "COMPONENTNAME")
    >>> remote_sys = remote.modules['sys']


    :param int port: TCP port in which to listen

    :param str host: (optional, default *0*--attach to all interfaces)

    :param bool ssl_enabled: (optional, default *True*) run all
      communication between RPYC client and server SSL encrypted.

      Uses the target-defined SSL Certificate Authority, certificates
      can be downloaded from the target with
      target.certs.get("CERTNAME")

    :param str venv_path: (optional, default *None*) Python Virtual
      Environment (venv) inside the container where to execute the
      RPYC server.

      Note that if the venv uses a diffferent python version than that
      of the container (eg: Python 3.6 vs Python 3.9), the RPYC server
      must be available inside said virtual environment and the path
      to it overriden in the *env_add* variable, e.g.:

      >>> ttbl.power.rpy_c(
      >>>     ...
      >>>     venv_path = "/some/venv",
      >>>     env_add = { 'RPYC_CLASSIC': "/some/venv/bin/rpyc_classic.py" },
      >>>     ...

    :param dict env_add: environment variables to add to the container
      (will be passed with *-e* to *podman run*).

      Note the path to the RPYC server will default to *rpyc_classic*
      but can be overriden by setting here the *RPYC_CLASSIC*
      environment variable:

      >>> ttbl.power.rpy_c(
      >>>     ...
      >>>     env_add = { 'RPYC_CLASSIC': "/some/venv/bin/rpyc_classic.py" },
      >>>     ...

    :param dict(str) data_files: (optional) files that will be created
      in the configuration directory mapped to the container's
      */etc/ttbd/data*.

      When this is powered on, :meth:`on` is executed; the files are
      then created and available inside the container at
      */etc/ttbd/data*.

      This is a dictionary keyed by file name (no subdirectories); the
      value is a string that will be written to the file; the string
      will be *%(FIELD)s* substituted against the :data:`kws` member
      which includes the target's inventory data and anything added to
      it.

    :param dict(str) run_files: (optional) files that will be created
      in the configuration directory mapped to the container's
      */etc/ttbd/run*.

      When this is powered on, :meth:`on` is executed; the files are
      then created and executed before running the RPYC server.

      This is meant for scripting. Note the *run_files* are created
      and executed after the data files, thus the run files can access
      them.

    The rest of the parameters are as to :class:`ttbl.power.daemon_podman_container_c`.

    **System Setup**

    1. Ensure there is an image name with RPYC support

       See :class:`daemon_podman_container_c` for image setup; the base
       image called *ttbd* is already defined to be able to run *rpyc*
       containers.

    """
    def __init__(self, image_name: str, rpyc_port: int,
                 cmdline = None,
                 venv_path: str = None,
                 env_add: dict = None,
                 run_files: dict = None,
                 data_files: dict = None,
                 ssl_enabled = True,
                 **kwargs):
        assert isinstance(image_name, str)
        assert isinstance(rpyc_port, int) and rpyc_port > 0 and rpyc_port < 65546
        assert isinstance(ssl_enabled, bool)

        self.rpyc_port = rpyc_port
        if cmdline == None:
            cmdline = []
        else:
            commonl.assert_list_of_strings(cmdline,
                                           "command line options", "argument")

        if env_add == None:
            env_add = {}
        else:
            commonl.assert_dict_of_strings(env_add, "env_add")

        if run_files == None:
            run_files = {}
        else:
            commonl.assert_dict_of_strings(run_files, "run_files")
        self.run_files = run_files

        if data_files == None:
            data_files = {}
        else:
            commonl.assert_dict_of_strings(data_files, "data_files")
        self.data_files = data_files

        if venv_path:
            # run RPYC inside a Python virtual environment that is
            # inside the container
            env_add['VENVPYTHON'] = venv_path + "/bin/python"
        # no env runs directly the rpyc_classic server

        cmdline += [
            # Port where RPYC serves
            "--publish", f"{rpyc_port}:{rpyc_port}",
            # Z: ensure mounting fixes SELinux labels too, because SELinux...
            "--volume", "%(path)s/%(component)s.etc:/etc/ttbd:ro,Z",
            image_name,
            "/bin/bash", "-xeuc",
            "ls -lR /etc/ttbd; "        # DEBUG info on the console
            # for PIP: "rpyc_classic.py",
            "run-parts /etc/ttbd/run; "
            "cd $HOME;"
            # unbuffer so we get output in the console---might slow down
            " PYTHONUNBUFFERED=1 exec ${VENVPYTHON:-} ${RPYC_CLASSIC:-rpyc_classic}"
            # listen on all interfaces of the container, we'll map it later
            f" --port {str(rpyc_port)} --host 0 --mode forking"
        ]
        if ssl_enabled:
            # rpyc_c.on() will copy ca* and server* from the
            # certificates directory (target STATEDIr/certiticates) to
            # the cfg dir (target's STATEDIR/COMPONENT.etc) which is
            # mapped with --volume to /etc/ttbd.
            # note the /etc/ttbd/certificates path is mapped by
            # the container from the certificates in the target's
            # directory TARGETSTATEDIR/certificates -- these are
            # always re-created new upon target's allocation.
            cmdline[-1] += \
                " --ssl-cafile /etc/ttbd/ca.cert" \
                " --ssl-certfile /etc/ttbd/server.cert" \
                " --ssl-keyfile /etc/ttbd/server.key"
        self.ssl_enabled = ssl_enabled

        daemon_podman_container_c.__init__(
            self, "rpyc", cmdline,
            rm_container = True, env_add = env_add, **kwargs
        )
        self.name = "rpyc"
        self.upid_set(f"RPYC Server @TCP:{rpyc_port}",
                      image_name = image_name,
                      rpyc_port = rpyc_port,
                      ssl_enabled = ssl_enabled)



    #: Minimum container speficification
    #:
    #: This can be fed to commonl.buildah_image_create() to generate
    #: the image upon server configuration.
    #:
    #: crontabs -> run-parts
    dockerfile = """
FROM fedora-minimal
RUN \
    microdnf install -y \
       crontabs \
       procps \
       python3-rpyc \
       strace \
       usbutils; \
    microdnf clean all
"""

    def target_setup(self, target, iface_name, component):
        target.fsdb.set(f"interfaces.{iface_name}.{component}.rpyc_port",
                        self.upid['rpyc_port'])
        target.fsdb.set(f"interfaces.{iface_name}.{component}.ssl_enabled",
                        self.upid['ssl_enabled'])
        daemon_podman_container_c.target_setup(
            self, target, iface_name, component)

    def config_dir_setup(self, target, component):
        pass

    def on(self, target, component):
        # Container configuration dir
        # note this is mapped by the on() method to /etc/ttbd inside
        # the container
        cfg_dir = os.path.join(target.state_dir, component + ".etc")
        run_dir = os.path.join(cfg_dir, "run")
        data_dir = os.path.join(cfg_dir, "data")
        shutil.rmtree(cfg_dir, ignore_errors = True)
        commonl.makedirs_p(cfg_dir)
        commonl.makedirs_p(run_dir)
        commonl.makedirs_p(data_dir)

        if self.ssl_enabled:
            # ensure the SSL certificate support has been enabled,
            # since it is only done so on demand.  We do it by requesting
            # a certificate for RPYC--this will force the server cert
            # to be created
            iface_cert = getattr(target, "certs", None)
            if iface_cert == None:
                raise RuntimeError(
                    f"{target.id}: does not support SSL certificates! BUG?")
            iface_cert.put_certificate(
                target,
                ttbl.who_daemon(),
                { "name": "rpyc" },
                None, None)

        # copy the certificates to the config dir
        shutil.copy(target.state_dir + "/certificates/ca.cert", cfg_dir)
        shutil.copy(target.state_dir + "/certificates/server.key", cfg_dir)
        shutil.copy(target.state_dir + "/certificates/server.cert", cfg_dir)

        # Get the data and run files; data first, since run files
        # might need them
        for file_name, file_data in self.data_files.items():
            with open(os.path.join(data_dir, file_name), "w") as f:
                f.write(commonl.kws_expand(file_data, self.kws))
        for file_name, file_data in self.run_files.items():
            with open(os.path.join(run_dir, file_name), "w") as f:
                f.write(commonl.kws_expand(file_data, self.kws))
                os.fchmod(f.fileno(), 0o755)

        # hook for subclasses to re-define
        self.config_dir_setup(target, component)

        daemon_podman_container_c.on(self, target, component)


    def verify(self, target, component, cmdline_expanded):
        time.sleep(1)	# force delay
        return commonl.tcp_port_busy(self.rpyc_port)



class rpyc_aardvark_c(rpyc_c):
    """Driver to expose an Aardvark device using Totalphase's Python
    Aardvark library over the Python RPYC Remote system.

    When powered on, it starts a podman container which has access to
    an specific Aardvark device and that exports an RPYC service
    https://rpyc.readthedocs.io/en/latest/ in the given TCP port to
    use the `aardvark_py
    <https://aardvark-py.readthedocs.io/en/master/`_ library.

    A client then can establish an RPYC connection and instantiate an
    aardvark object:

    >>> remote = tcfl.tl.rpyc_connect(target, "COMPONENTNAME")
    >>> raardvark_py = remote.modules['aardvark_py']

    >>> r, handles, ids = raardvark_py.aa_find_devices_ext(1, 1)
    >>> assert r > 0
    >>> handle = raardvark_py.aa_open(0)
    >>> features = raardvark_py.aa_features(handle)
    >>> assert features == 27
    >>> target.report_pass("Aardvark: features is 27")
    >>> raardvark_py.aa_close(handle)


    :param str usb_serial_number: USB serial number for the Aaardvark
      device to use.

    :param int rpyc_port: TCP port number to use for the RPYC
      connection. This port will be opened on the server and expect an
      a client connecting using SSL with certificates from the
      target's cert interface.

    System Setup
    ^^^^^^^^^^^^

    **Server**

    Create a container image with the Aardvark PY library, RPYC and
    other utilities for debugging; generate a file called
    *aardvark_py.Dockefile* with the contents::

        FROM fedora-minimal
        RUN microdnf install -y crontabs usbutils strace python3-rpyc python3-rpyc
        RUN microdnf clean all
        RUN pip3 install --no-deps aardvark_py

    And setup the container image for Aardvark::

        $ buildah bud -f aardvark_py.Dockerfile -t aardvark_py

    You can also use, from the in a :ref:`server configuration file
    <ttbd_configuration>`, the helper to auto-generate a local image
    upon server initialization:

    >>> commonl.buildah_image_create("aardvark_py", ttbl.aardvark.dockerfile)

    Which will create the image if non-existant.

    Client:

      $ sudo dnf install -y python3-rpyc
      $ pip3 install --user rpyc        	# if not available

    """
    def __init__(self, usb_serial_number: str, rpyc_port: int,
                 image_name: str = "aardvark_py",
                 off_on_release: bool = True,
                 **kwargs):
        assert isinstance(usb_serial_number, str)
        assert isinstance(rpyc_port, int) \
            and rpyc_port > 1024 and rpyc_port <= 65536, \
            "rpyc_port: expected integer from 1024 to 65536; " \
            "got {type(rpyc_port)}"

        self.usb_serial_number = usb_serial_number

        rpyc_c.__init__(
            self,
            image_name,		# FIXME: build instructions
            rpyc_port,
            cmdline = [
                #
                # Map the device
                #
                "--device=%(device_path)s:%(device_path)s:rwm",
                "--volume=%(device_syspath)s:%(device_syspath)s",

                # "always" conflicts with --rm; this is enough to
                # restart when running in forking --mode (see below)
                # even adding :COUNT conflicts with --rm...hmm
                "--restart", "on-failure",
            ],
            ssl_enabled = True,
            off_on_release = off_on_release,
            **kwargs
        )
        self.upid_set(
            f"Aardvark I2C/SPI #{usb_serial_number}",
            usb_serial_number = usb_serial_number,
        )
        self.name = "aardvark"


    #: Minimum container speficification
    #:
    #: This can be fed to commonl.buildah_image_create() to generate
    #: the image upon server configuration. We assume the basic *ttbd*
    #: image is available
    dockerfile = """
FROM ttbd
RUN pip3 install --no-deps aardvark_py
"""

    # rpyc_c.target_setup() -> will be called

    def on(self, target, component):
        # Find /dev/bus/usb/BUSNUM/DEVNUM for the Aardvark associated
        # to this component given the serial number
        syspath, busnum, devnum = ttbl.usb_device_by_serial(
            self.usb_serial_number, None, "busnum", "devnum"
        )
        if syspath == None or busnum == None or devnum == None:
            raise RuntimeError(
                f"Cannot find USB device with serial {self.usb_serial_number}")
        # Create the /dev/bus/usb/NNN/ZZZ path using the bus and dev numbers
        devpath = f"/dev/bus/usb/{int(busnum):03d}/{int(devnum):03d}"

        # create a dictionary of keywords with that information which
        # the command line defined in __init__ will use to start the
        # podman contained daemon.
        self.kws = {
            "device_path": devpath,
            "device_syspath": syspath,
            "rpyc_port": self.rpyc_port,
        }
        rpyc_c.on(self, target, component)


    def verify(self, target, component, _cmdline):
        return commonl.tcp_port_busy(self.rpyc_port)



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
        _env_add = {
            # this is needed so socat generates timestamps for UTC,
            # since we don't need to care where the server is
            "TZ": "UTC"
        }
        if env_add:
            _env_add.update(env_add)
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
                "-d",		# THIRD -d is very important to get
                                # timestamp/offset information in the
                                # log file which we'll use
                address1,	        # will be formatted against kws
                address2,	        # will be formatted against kws
            ],
            precheck_wait = precheck_wait,
            env_add = _env_add,
            **kwargs)


    def on(self, target, component):
        # this is what we use to tell if the thing has turned on in
        # the verify() method, so wipe it first to make sure we have a
        # clean state
        commonl.rm_f(f"{target.state_dir}/{component}-{self.name}.log")
        daemon_c.on(self, target, component)


    def verify(self, target, component, cmdline_expanded):
        # this is the log file name, that has been expanded already by
        # the daemon_c class calling start
        return os.path.exists(cmdline_expanded[2])


def _check_has_iface_buttons(target):
    buttons_iface = getattr(target, "buttons", None)
    if not buttons_iface or not isinstance(buttons_iface, interface):
        raise RuntimeError("%s: target has no buttons interface" % target.id)


class button_sequence_pc(impl_c):
    """Power control implementation that executest a button sequence on
    power on, another on power off.

    Requires a target that supports the *buttons* interface.

    :param list sequence_on: (optional; list of events) sequence of
      events to do on power on (see :func:ttbl.power.intrface.sequence
      for sequence reference).

    :param list sequence_off: (optional; list of events) sequence of
      events to do on power off (see :func:ttbl.power.intrface.sequence
      for sequence reference).


    Other parameters as to :class:ttbl.power.impl_c.

    For example, to click a power button one second to power on, one
    would add to the power rail:

    >>> target.interface_add("power", ttbl.power.interface(
    >>>     (
    >>>         "release buttons",
    >>>         ttbl.power.buttons_released_pc("power", "reset")
    >>>     ),
    >>>     ...
    >>>     (
    >>>         "power button",
    >>>         ttbl.power.button_sequence_pc(sequence_on = [
    >>>             # click BUTTONNAME 1 second to power on
    >>>             ( 'press', 'BUTTONNAME' ),		# press the button
    >>>             ( 'wait', 1 ),			# hold pressed 1 sec
    >>>             ( 'release', 'BUTTONNAME' ),	# release the button
    >>>         ])
    >>>     ),
    >>>     ...
    >>> )

    When having buttons instrumented, it is always a good idea to
    include a :class:buttons_released_pc also (as described), to
    ensure all the buttons are released when powering on (to for
    example make sure the *reset* button is not pressed while trying
    to turn on a machine).

    """
    def __init__(self, sequence_on = None, sequence_off = None, **kwargs):
        impl_c.__init__(self, **kwargs)
        self.sequence_on = sequence_on
        self.sequence_off = sequence_off
        l = []
        if sequence_on:
            lon = [ ]
            for operation, argument in sequence_on:
                lon.append("%s:%s" % (operation, argument))
            l.append("OFF:" + ",".join(lon))
        if sequence_off:
            loff = [ ]
            for operation, argument in sequence_off:
                loff.append("%s:%s" % (operation, argument))
            l.append("ON:" + ",".join(loff))
        self.upid_set(
            "Button/jumper sequence %s" % " ".join(l),
            sequence_on = ",".join("%s:%s" % (operation, argument)
                                   for operation, argument in sequence_on),
            sequence_off = ",".join("%s:%s" % (operation, argument)
                                    for operation, argument in sequence_off)
        )

    def on(self, target, _component):
        _check_has_iface_buttons(target)
        if self.sequence_on:
            target.buttons.sequence(target, self.sequence_on)

    def off(self, target, _component):
        _check_has_iface_buttons(target)
        if self.sequence_off:
            target.buttons.sequence(target, self.sequence_off)

    def get(self, target, _component):
        # no real press status, so can't tell
        return None

# register the button's default state property so it is not wiped
# across allocations
ttbl.test_target.properties_keep_on_release.add(
    # FIXME: need a central regex to validate target name; now it is
    # hardcoded in ttbl.config.target_add()
    re.compile("^interfaces\.buttons\.[_a-z0-9A-Z]+\.default_state"))

class buttons_released_pc(impl_c):
    """
    Power control implementation that ensures a list of buttons
    are released (not pressed) before powering on a target.

    :param str buttons: names of buttons that must be released upon
      power on

    :param dict overrideable_states: dictionary keyed by button name
      of the buttons whose default state can be overriden and what
      shall be their default state (*False* means
      released/off, which is the same as listing it in *buttons*;
      *True* means pressed/on).

      >>> { "power": False, "reset": False, "security": True }

      to override the defult sete, set property
      *interface.buttons.BUTTONNAME.default_state* to boolean *True*
      or *False* (for on/pressed, off/released).

    >>> ttbl.power.buttons_released_pc("reset", "test", "overdrive")

    Other parameters as to :class:ttbl.power.impl_c.

    """
    def __init__(self, *buttons, overrideable_states: dict = None, **kwargs):
        commonl.assert_list_of_strings(buttons, "buttons", "button")
        impl_c.__init__(self, **kwargs)
        self.overrideable_states = {}
        for button in buttons:
            # note this is the "original" behaviour, which sets
            # default state to off/released and doesn't allow
            # overriding and only allows OFF
            self.overrideable_states[button] = None
        if overrideable_states:
            # new behavior, allows you to override
            commonl.assert_dict_of_types(overrideable_states,
                                         "overrideable_states", bool)
            for button, default_state in overrideable_states.items():
                self.overrideable_states[button] = default_state
        self.upid_set(
            "Button setter to default state (%s)" % "/".join(buttons),
            buttons = " ".join(buttons)
        )


    def target_setup(self, target, _iface_name, _name):
        # register the default state property so it can be set by the
        # current user
        for button, default_state in self.overrideable_states.items():
            if default_state == None:
                # non overrideable setting, clear any past one and
                # move on
                target.property_set(
                    f"interfaces.buttons.{button}.default_state", None)
                continue
            target.properties_user.add(
                f"interfaces.buttons.{button}.default_state")
            # publish the current default state if there was none;
            # this helps keep the setting between daemon restarts
            # FIXME: this might not really work if the
            # interfaces. hierarchy is wiped upon start and re-generated
            current_default_state = target.property_get(
                f"interfaces.buttons.{button}.default_state")
            if current_default_state == None:
                current_default_state = default_state
            target.property_set(
                f"interfaces.buttons.{button}.default_state",
                current_default_state)


    def on(self, target, component):

        sequence = []
        for button, default_state in self.overrideable_states.items():
            # Get the default state for this button
            #
            # We get from the inventory first, for realtime settings
            # and default to what was configured.
            runtime_default_state = target.property_get(
                f"interfaces.buttons.{button}.default_state",
                None)
            if default_state == None and runtime_default_state != None:
                raise impl_c.error_e(
                    f"{target.id} trying to override button {button} with"
                    f" property 'interfaces.buttons.{button}.default_state'"
                    " is not allowed per configuration; reset property"
                    " to clear condition")
            # ok, now that we have certified the default state can be
            # overriden, override it if a runtime one is specicified
            if runtime_default_state != None:
                default_state = runtime_default_state
            if default_state == True:
                sequence.append(( 'on', button ))
            elif default_state in ( False, None ):
                sequence.append(( 'off', button ))
            else:
                raise impl_c.error_e(
                    f"invalid default value for button {button} in property"
                    f" 'interfaces.buttons.{button}.default_state'; expected "
                    f" nothing, boolean True or False; got '{default_state}'"
                    f" ({type(default_state)})")

        _check_has_iface_buttons(target)
        target.buttons.sequence(target, sequence)

    def off(self, target, _component):
        pass

    def get(self, target, _component):
        return None			# no real press status, so can't tell


def create_pc_from_spec(power_spec, **kwargs):
    # FIXME: this needs to be improved, it assumes raritan now and has
    # to be more generic (take as stanza the driver name, for example)
    if isinstance(power_spec, str):
        pdu_hostname, pdu_port = power_spec.split(":", 1)
        if "pdu_password" not in kwargs:
            pdu_password = commonl.password_lookup(pdu_hostname)
        return ttbl.raritan_emx.pci(
            "https://" + pdu_hostname, int(pdu_port), password = pdu_password,
            https_verify = False, **kwargs)
    if isinstance(power_spec, ttbl.power.impl_c):
        return power_spec
    raise RuntimeError(f"power_spec: unknown type {type(power_spec)}")



def _execute_action(target: ttbl.test_target, state: bool, soft_failure: bool):
    # executes a power action based on the state variable
    if state == None:
        return
    try:
        target.log.warning(
            "ttbl.power._execute_action(): powering %s",
            "on" if state == True else "off")
        if state == True:
            target.power.put_on(target, ttbl.who_daemon(), {}, {}, None)
        elif state == False:
            target.power.put_off(target, ttbl.who_daemon(), {}, {}, None)
    except Exception as e:
        if soft_failure == False:
            raise
        target.log.warning(
            "ttbl.power._execute_action(): ignoring power %s failure: %s",
            "on" if state == True else "off", e)


_startup_defer_list = []

def defer(target: ttbl.test_target, state: bool,
          defer_list: list = None, soft_failure: bool = True):
    """
    Defer a power action

    This is mostly used during configuration:

    - Execute inmediately as configured (can slow down startup):

      >>> ttbl.power.defer(target, True)

    - Execute later in a batch during configuration:

      >>> somename_list = []
      >>> target = ...createtarget...
      >>> ttbl.power.defer(target, True, somename_list)
      >>> ...
      >>> ttbl.power.execute_defer_list(somename_list)

    - Execute once daemon is complete and serving:

      >>> target = ...createtarget...
      >>> ttbl.power.defer(target, True, "startup")

    :param ttbl.test_target target: target where to act

    :param list defer_list: append to the given defer list; if
      "startup", will be run right after the server starts and starts
      serving. Use :func:`ttbl.execute_defer_list` later to sequence
      the power actions.

    :param bool state: state the target shall be in; *True* for
      powered on, *False* for powered off, *None* for don't do anything.

    """
    assert state == None or isinstance(state, bool), \
        "state: expected bool or None; got {type(state)}"

    if defer_list == None:
        _execute_action(target, state, soft_failure)
        return

    if defer_list == "startup":
        # use tags, since we want them to survive restarts and then
        # we'll just ignore'em
        target.tags["interfaces.power.__on_startup"] = state
        _startup_defer_list.append(( target, state, soft_failure ))
        return

    assert isinstance(defer_list, list), \
        "defer_list: expected list; got {type(defer_list)}"
    defer_list.append(( target, state, soft_failure ))



def execute_defer_list(defer_list: list, name: str, serialize: bool = False,
                       keepalive_fn: callable = None):
    """
    Execute the deferred power actions in @defer_list

    :param list defer_list: list of deferred power actions filled by
      :func:`ttbl.power.defer`

    :param str name: name of the deferred list

    :param bool serialize: (optional; defaults to *False*) execute the
      actions in a serial manner.

    :param callable keepalive_fn: (optional; defaults to *None*) if
      defined, function to call every ten seconds while waiting for
      *defer_list*.

    """
    assert keepalive_fn == None or callable(keepalive_fn)
    logging.info("power defer list '%s': executing", name)
    if serialize:
        for ( target, state, soft_failure ) in defer_list:
            _execute_action(target, state, soft_failure)
    else:
        processes = max(20, len(defer_list))
        current_process = multiprocessing.process.current_process()
        _config = getattr(current_process, "_config", None)
        daemon_orig = _config.get('daemon', None)
        _config['daemon'] = False
        executor = concurrent.futures.ProcessPoolExecutor(processes)
        try:
            futures = {
                executor.submit(_execute_action,
                                target, state, soft_failure): (
                                    target, state, soft_failure
                                )
                for ( target, state, soft_failure ) in defer_list
            }
            ts0 = time.time()
            while True:
                # We are going to run this in a loop and timeout every 10s
                # so we can keepalive
                try:
                    for future in concurrent.futures.as_completed(
                            futures, timeout = 10):
                        target, state, soft_failure = futures[future]
                        try:
                            _ = future.result()
                        except Exception as e:
                            logging.error(
                                "%s: exception running deferred power-%s"
                                " operation: %s",
                                target.id, "on" if state else "off", e)
                            if not soft_failure:
                                raise
                    # if we end up here, it means the as_completed()
                    # process is done with all tasks, so we can stop
                    # repeating the loop
                    break
                except TimeoutError:
                    # if this is being used from the cleanup process, we
                    # want to run the keepalive function evrynow and then,
                    # to notify the service manager this process is alive
                    if keepalive_fn:
                        ts = time.time()
                        logging.info(
                            "power defer list '%s': keepaliving @%.02fs",
                            name, ts - ts0)
                        keepalive_fn()
                    continue
        finally:
            executor.shutdown(wait = True)
            del executor
            _config['daemon'] = daemon_orig

    logging.warning("power defer list '%s': executed", name)
