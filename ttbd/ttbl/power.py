#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Control power to targets
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
  :class:`appearing <ttbl.pc.delay_til_file_appears>`, a USB device is
  :class:`detected <ttbl.pc.delay_til_usb_device>` in the system

"""

import collections
import errno
import time
import os
import traceback
import types
import subprocess

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
    """
    def __init__(self, paranoid = False):
        assert isinstance(paranoid, bool)
        #: If the power on fails, automatically retry it by powering
        #: first off, then on again
        self.power_on_recovery = False
        self.paranoid = paranoid
        self.timeout = 10	# used for paranoid checks
        self.wait = 0.5
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
        pass


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
            impls = self.impls.iteritems()
        for component, impl in impls:
            # need to get state for the real one!
            if component in self.aliases:
                component_real = self.aliases[component]
            else:
                component_real = component
            state = self._impl_get(impl, target, component_real)
            self.assert_return_type(state, bool, target,
                                    component, "power.get", none_ok = True)
            data[component] = state
        # the values that are None, we don't care for them, so to
        # consider if we are fully on, is like they are on
        result_all = all(i in ( True, None ) for i in data.values())
        result_any = any(i == True for i in data.values())
        if result_all:					# update cache
            power = True
            target.fsdb.set('powered', "On")
        else:
            power = False
            target.fsdb.set('powered', None)
        return power, data, result_any


    def _get_any(self, target):
        # return if any power component in the rail is on
        _, _, result_any = self._get(target)
        return result_any


    def _off(self, target, impls, why, whole_rail = True):
        #
        # Power off everything
        #
        # We only power off whatever is on, hence why we ask what is
        # on first.
        #
        # If the user asked for the whole rail, then we'll also run
        # the pre/post hooks.
        _, data, result_any = self._get(target, impls)
        if result_any == False:		# everything is off already
            target.log.debug("power-off%s: skipping (already off)" % why)
            return

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
            if data[component] == False:
                target.log.debug("%s: powering off%s: skipping (already off)"
                                 % (component, why))
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


    def _on(self, target, impls, why, whole_rail = True):
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
        result_all, data, _ = self._get(target, impls)
        if result_all == True:
            target.log.debug("power-on%s: skipping (already on)" % why)
            return
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
            if data[component] == True:
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

    def get_list(self, target, _who, _args, _files, _user_path):
        # return a dictionary indicating the individual state of
        # each power component
        _, data, _ = self._get(target)
        # return a sorted list, so the order is maintained
        return dict(power = [ ( i, s ) for i, s in data.items() ])

    def get_get(self, target, _who, _args, _files, _user_path):
        # return a single bool saying if all the power rail
        # components are on
        result, _, _  = self._get(target)
        return dict(result = result)

    def put_on(self, target, who, args, _files, _user_path):
        impls, _all = self.args_impls_get(args)
        with target.target_owned_and_locked(who):
            target.timestamp()
            self._on(target, impls, "", _all)
            return {}

    def put_off(self, target, who, args, _files, _user_path):
        impls, _all = self.args_impls_get(args)
        with target.target_owned_and_locked(who):
            target.timestamp()
            self._off(target, impls, "", _all)
            return {}

    def put_cycle(self, target, who, args, _files, _user_path):
        impls, _all = self.args_impls_get(args)
        # default wait is two seconds
        wait = float(args.get('wait',
                              target.tags.get('power_cycle_wait', 2)))
        with target.target_owned_and_locked(who):
            target.timestamp()
            self._off(target, impls, " (because power-cycle)", _all)
            if wait:
                time.sleep(wait)
            self._on(target, impls, " (because power-cycle)", _all)
            return {}

    def put_reset(self, target, who, args, _files, _user_path):
        self.put_cycle(target, who, args, _files, _user_path)



class fake_c(impl_c):
    """Fake power component which stores state in disk

    Note this object doesn't have to know much parameters on
    initialization, which allows us to share implementations.

    It can rely on the *target* and *component* parameters to
    each method to derive where to act.
    """

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

    """
    def __init__(self, pc):
        assert isinstance(pc, impl_c)
        impl_c.__init__(self)
        self.pc = pc
        # These have to be the same set of default properties in
        # ttbl.power.impl_c
        self.power_on_recovery = pc.power_on_recovery
        self.paranoid = pc.paranoid
        self.timeout = pc.timeout
        self.wait = pc.wait
        self.paranoid_get_samples = pc.paranoid_get_samples

    def on(self, target, component):
        self.pc.off(target, component)

    def off(self, target, component):
        self.pc.on(target, component)

    def get(self, target, component):
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
    """
    #: KEY=VALUE to add to the environment
    #: Keywords to add for templating the arguments
    def __init__(self, cmdline,
                 precheck_wait = 0, env_add = None, kws = None,
                 path = None, name = None,
                 pidfile = None, mkpidfile = True, paranoid = False):
        assert isinstance(cmdline, list), \
            "cmdline has to be a list of strings; got %s" \
            % type(cmdline).__name__
        assert precheck_wait >= 0
        impl_c.__init__(self, paranoid = paranoid)
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
            assert isinstance(path, basestring)
            self.path = path
        if name == None:
            self.name = os.path.basename(self.path)
        else:
            assert isinstance(name, basestring)
            self.name = name
        self.kws.setdefault('name', self.name)
        if pidfile:
            assert isinstance(pidfile, basestring)
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
                for key, val in env.iteritems():
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
                 precheck_wait = 0.2, extra_cmdline = None):
        assert isinstance(address1, basestring)
        assert isinstance(address2, basestring)
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
            env_add = env_add)

    def verify(self, target, component, cmdline_expanded):
        # this is the log file name, that has been expanded already by
        # the daemon_c class calling start
        return os.path.exists(cmdline_expanded[2])
