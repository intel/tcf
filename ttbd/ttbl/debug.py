#! /usr/bin/python3
#
# Copyright (c) 2017-19 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Interface for common debug operations
-------------------------------------

A target's multiple components can expose each debugging interfaces;
these allow some low level control of CPUs, access to JTAG
functionality, etc in an abstract way based on capability.

Debugging can be started or stopped; depending on the driver this
might mean some things are done to allow that debugging support to
happen. In some components it might need a power cycle.

Each component can have its own :class:`driver <impl_c>` or one driver
might service multiple components (eg: in asymetrical SMP systems)
serviced by OpenOCD.

When the debug support for multiple components is implemented by the
same driver, a single call will be made into it with the list of
components it applies to.

The client side is implemented by :class:`target.debug
<tcfl.target_ext_debug.extension>`.
"""

import collections

import json

import ttbl

class impl_c(ttbl.tt_interface_impl_c):
    """
    Driver interface for a component's debugging capabilities

    The debug interface supports multiple components which will be
    called for the top level debug operations; they are implemented by
    an instance subclassed from this interface.

    Objects that implement the debug interface then can be passed to
    the debug interface as implementations; for example, the QEMU
    driver exposes a debug interface and thus:

    >>> qemu_pc = ttbl.qemu.pc(...)
    >>> ...
    >>> target.interface_add("debug", ttbl.debug.interface(
    >>>   ( "x86", qemu_pc )))

    this assumes that the QEMU driver object *qemu_pc* has been
    instantiated to implement an *x86* virtual machine; thus the debug
    control for the virtual machine *x86* is registered with the
    *debug* interface.
    """
    def __init__(self):
        ttbl.tt_interface_impl_c.__init__(self)

    def debug_list(self, target, component):
        """
        Provide debugging information about the component

        Return *None* if not currently debugging in this component,
        otherwise a dicionary keyed by string with information.

        If the dictionary is empty, it is assumed that the debugging
        is enabled but the target is off, so most services can't be
        accessed.

        Known fields:

        - *GDB*: string describing the location of the GDB bridge
          associated to this component in the format
          PROTOCOL:ADDRESS:PORT (eg: tcp:some.host.name:4564); it
          shall be possible to feed this directly to the *gdb target
          remote* command.
        """
        raise NotImplementedError

    def debug_start(self, target, components):
        """
        Put the components in debugging mode.

        Note it might need a power cycle for the change to be
        effective, depending on the component.

        :param ttbl.test_target target: target on which to operate
        :param list(str) components: list of components on which to operate
        """
        raise NotImplementedError

    def debug_stop(self, target, components):
        """
        Take the components out of debugging mode.

        Note it might need a power cycle for the change to be
        effective, depending on the component.

        :param ttbl.test_target target: target on which to operate
        :param list(str) components: list of components on which to operate
        """
        raise NotImplementedError

    def debug_halt(self, target, components):
        """
        Halt the components' CPUs

        Note it might need a power cycle for the change to be
        effective, depending on the component.
        """
        raise NotImplementedError

    def debug_resume(self, target, components):
        """
        Resume the components' CPUs

        Note it might need a power cycle for the change to be
        effective, depending on the component.
        """
        raise NotImplementedError

    def debug_reset(self, target, components):
        """
        Reset the components' CPUs

        Note it might need a power cycle for the change to be
        effective, depending on the component.
        """
        raise NotImplementedError

    def debug_reset_halt(self, target, components):
        """
        Reset and halt the components' CPUs

        Note it might need a power cycle for the change to be
        effective, depending on the component.
        """
        raise NotImplementedError


class interface(ttbl.tt_interface):
    """Generic debug interface to start and stop debugging on a
    target.

    When debug is started before the target is powered up, then upon
    power up, the debugger stub shall wait for a debugger to connect
    before continuing execution.

    When debug is started while the target is executing, the target
    shall not be stopped and the debugging stub shall permit a
    debugger to connect and interrupt the target upon connection.

    Each target provides its own debug methodolody; to find out how to
    connect, issue a debug-gdb command to find out where to connect
    to.

    When a target has this capability, the interface can be added to
    the target specifying which actual object derived from
    :class:`impl_c` implements the functionality, eg, for a target
    based on QEMU, QEMU provides a debug interface:

    >>> qemu_pc = ttbl.qemu.pc(...)
    >>> ...
    >>> target.interface_add("debug",
    >>>                      ttbl.tt_interface(**{
    >>>                          'x86': qemu_pc
    >>> })

    See :func:`conf_00_lib_pos.target_qemu_pos_add` or
    :func:`conf_00_lib_mcu.target_qemu_zephyr_add` for an example of
    this.

    """
    def __init__(self, *impls, **kwimpls):
        ttbl.tt_interface.__init__(self)
        self.impls_set(impls, kwimpls, impl_c)

    def _target_setup(self, target, iface_name):
        target.fsdb.set("debug", None)

    def _release_hook(self, target, _force):
        self._stop(target, list(self.impls.keys()))


    def _impls_by_component(self, args):
        components = self.arg_get(args, "components", list, allow_missing=True)
        if not components:
            components = list(self.impls.keys())
        # do a single call to one component with everything that
        # resolves to the same implementation from the aliases for
        # that component name.
        v = collections.defaultdict(list)
        for component in components:
            # validate image types (from the keys) are valid from
            # the components and aliases
            impl, component_real = self.impl_get_by_name(component,
                                                         "component")
            v[impl].append(component_real)
        return v


    def get_list(self, target, who, args, _files, _user_path):
        components = self.arg_get(args, "components", list, allow_missing=True)
        if not components:
            components = list(self.impls.keys())
        with target.target_owned_and_locked(who):
            r = {}
            for component in components:
                impl, _component_real = self.impl_get_by_name(component,
                                                              "component")
                r[component] = impl.debug_list(target, component)
                self.assert_return_type(r[component], dict, target,
                                        component, "debug_list",
                                        none_ok = True)
            return dict(result = r)

    def put_start(self, target, who, args, _files, _user_path):
        components = self.arg_get(args, "components", list, allow_missing=True)
        if not components:
            components = list(self.impls.keys())
        with target.target_owned_and_locked(who):
            for component in components:
                impl, _component_real = self.impl_get_by_name(component,
                                                              "component")
                debugging = impl.debug_list(target, component)
                self.assert_return_type(debugging, dict, target,
                                        component, "debug_get", none_ok = True)
                if debugging == None:
                    impl.debug_start(target, component)
            target.fsdb.set("debug", "True")
            return {}

    def _stop(self, target, components):
        for component in components:
            impl, _component_real = self.impl_get_by_name(component,
                                                          "component")
            debugging = impl.debug_list(target, component)
            self.assert_return_type(debugging, dict, target,
                                    component, "debug_get", none_ok = True)
            if debugging != None:
                impl.debug_stop(target, component)
        target.fsdb.set("debug", None)


    def put_stop(self, target, who, args, _files, _user_path):
        components = self.arg_get(args, "components", list, allow_missing=True)
        if not components:
            components = list(self.impls.keys())
        with target.target_owned_and_locked(who):
            self._stop(target, components)
            return {}

    def put_halt(self, target, who, args, _files, _user_path):
        components = self.arg_get(args, "components", list, allow_missing=True)
        if not components:
            components = list(self.impls.keys())
        with target.target_owned_and_locked(who):
            for impl, components \
                in list(self._impls_by_component(args).items()):
                impl.debug_halt(target, components)
            return {}

    def put_resume(self, target, who, args, _files, _user_path):
        components = self.arg_get(args, "components", list, allow_missing=True)
        if not components:
            components = list(self.impls.keys())
        with target.target_owned_and_locked(who):
            for impl, components \
                in list(self._impls_by_component(args).items()):
                impl.debug_resume(target, components)
            return {}

    def put_reset(self, target, who, args, _files, _user_path):
        with target.target_owned_and_locked(who):
            for impl, components \
                in list(self._impls_by_component(args).items()):
                impl.debug_reset(target, components)
            return {}

    def put_reset_halt(self, target, who, args, _files, _user_path):
        components = self.arg_get(args, "components", list, allow_missing=True)
        if not components:
            components = list(self.impls.keys())
        with target.target_owned_and_locked(who):
            for impl, components \
                in list(self._impls_by_component(args).items()):
                impl.debug_reset_halt(target, components)
            return {}
