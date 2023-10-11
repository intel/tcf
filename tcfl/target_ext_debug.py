#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Access target's debugging capabilities
--------------------------------------

"""
import json

import commonl
from . import tc
from . import msgid_c

class extension(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to run methods form the debug
    :mod:`interface <ttbl.debug>` to targets.

    Use as:

    >>> target.debug.list()
    >>> target.debug.start()
    >>> target.debug.stop()
    >>> target.debug.reset()
    >>> target.debug.halt()
    >>> target.debug.reset_halt()
    >>> target.debug.resume()

    etc ...
    """

    def __init__(self, target):
        if 'debug' not in target.rt.get('interfaces', []):
            raise self.unneeded

    def list(self, components = None):
        """
        Return a debugging information about each component

        :param list(str) components: (optional) list of subcomponents
          for which to report the information (default all)

        :returns dict:  dictionary keyed by components describing each
          components debugging status and other information
          information.

          If a component's value is *None*, debugging is not started
          for that component. Otherwise the dictionary will include
          values keyed by string that are implementation specific,
          with the common ones documented in
          :meth:`ttbl.debug.impl_c.debug_list`.
        """
        r = self.target.ttbd_iface_call("debug", "list", method = "GET",
                                        components = components)
        return r['result']

    def start(self, components = None):
        """
        Start debugging support on the target or individual components

        Note it might need a power cycle for the change to be
        effective, depending on the component.

        If called before powering on, the target will wait for the
        debugger to connect before starting the kernel (when
        possible).

        :param list(str) components: (optional) list of components
          whose debugging support shall start (defaults to all)
        """
        self.target.ttbd_iface_call("debug", "start", method = "PUT",
                                    components = components)

    def stop(self, components = None):
        """
        Stop debugging support on the target

        Note it might need a power cycle for the change to be
        effective, depending on the component.

        :param list(str) components: (optional) list of components
          whose debugging support shall stop (defaults to all)
        """
        self.target.ttbd_iface_call("debug", "stop", method = "PUT",
                                    components = components)

    def halt(self, components = None):
        """
        Halt the target's CPUs

        :param list(str) components: (optional) list of components
          where to operate (defaults to all)
        """
        self.target.ttbd_iface_call("debug", "halt", method = "PUT",
                                    components = components)

    def reset(self, components = None):
        """
        Reset the target's CPUs

        :param list(str) components: (optional) list of components
          where to operate (defaults to all)
        """
        self.target.ttbd_iface_call("debug", "reset", method = "PUT",
                                    components = components)

    def reset_halt(self, components = None):
        """
        Reset and halt the target's CPUs

        :param list(str) components: (optional) list of components
          where to operate (defaults to all)
        """
        self.target.ttbd_iface_call("debug", "reset_halt", method = "PUT",
                                    components = components)

    def resume(self, components = None):
        """
        Resume the target's CPUs

        This is called to instruct the target to resume execution,
        following any kind of breakpoint or stop that halted it.

        :param list(str) components: (optional) list of components
          where to operate (defaults to all)
        """
        self.target.ttbd_iface_call("debug", "resume", method = "PUT",
                                    components = components)
