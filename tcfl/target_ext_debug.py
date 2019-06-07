#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Access target's debugging capabilities
--------------------------------------

"""

from . import tc

class debug(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to run methods form the debug
    interface to TTBD targets.

    Use as:

    >>> target.debug.reset_halt()
    >>> target.debug.resume()

    etc ...
    """

    def __init__(self, target):
        if not 'tt_debug_mixin' in target.rt.get('interfaces', []):
            raise self.unneeded

    def start(self):
        """
        Start debugging support on the target
        """
        self.target.report_info("Starting debug", dlevel = 1)
        self.target.rtb.rest_tb_target_debug_start(
            self.target.rt, ticket = self.target.ticket)
        self.target.report_info("Started debug")

    def info(self):
        """
        Return a string with information about the target's debugging support
        """
        self.target.report_info("Getting debug info", dlevel = 1)
        r = self.target.rtb.rest_tb_target_debug_info(
            self.target.rt, ticket = self.target.ticket)
        self.target.report_info("Got debug info")
        return r

    def halt(self):
        """
        Issue a CPU halt to the target's CPUs
        """
        self.target.report_info("Halting", dlevel = 1)
        self.target.rtb.rest_tb_target_debug_halt(
            self.target.rt, ticket = self.target.ticket)
        self.target.report_info("halted")

    def reset(self):
        """
        Issue a CPU reset and into runing to the target's CPUs
        """
        self.target.report_info("Debug resetting", dlevel = 1)
        self.target.rtb.rest_tb_target_debug_reset(
            self.target.rt, ticket = self.target.ticket)
        self.target.report_info("Debug reset")

    def reset_halt(self):
        """
        Issue a CPU reset and halt the target's CPUs
        """
        self.target.report_info("Resetting halt", dlevel = 1)
        self.target.rtb.rest_tb_target_debug_reset_halt(
            self.target.rt, ticket = self.target.ticket)
        self.target.report_info("Reset halt")

    def resume(self):
        """
        Issue a CPU resume to the target's CPUs
        """
        self.target.report_info("Debug resuming", dlevel = 1)
        self.target.rtb.rest_tb_target_debug_resume(
            self.target.rt, ticket = self.target.ticket)
        self.target.report_info("Debug resumed", dlevel = 1)

    def stop(self):
        """
        Stop debugging support on the target
        """
        self.target.report_info("Stopping debug", dlevel = 1)
        self.target.rtb.rest_tb_target_debug_stop(
            self.target.rt, ticket = self.target.ticket)
        self.target.report_info("Stopped debug")

    def openocd(self, command):
        """
        Run an OpenOCD command (if supported)
        """
        self.target.report_info("Running OpenOCD command", dlevel = 1)
        r = self.target.rtb.rest_tb_target_debug_openocd(
            self.target.rt, command, ticket = self.target.ticket)
        self.target.report_info("Ran OpenOCD command")
        return r
