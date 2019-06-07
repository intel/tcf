#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Power the target on or off
--------------------------

"""

from . import tc

class power(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to run methods form the power
    control to TTBD targets.

    Use as:

    >>> target.power.on()
    >>> target.power.off()
    >>> target.power.cycle()
    >>> target.power.reset()

    """

    def __init__(self, target):
        if not 'tt_power_control_mixin' in target.rt.get('interfaces', []):
            raise self.unneeded

    def on(self):
        """
        Power on a target
        """
        self.target.report_info("Powering on", dlevel = 1)
        self.target.rtb.rest_tb_target_power_on(
            self.target.rt, ticket = self.target.ticket)
        self.target.testcase.tls.expecter.power_on_post(self.target)
        self.target.report_info("Powered on")

    def get(self):
        """
        Return a target's power status, *True* if powered, *False* otherwise.
        """
        self.target.report_info("Getting power", dlevel = 1)
        r = self.target.rtb.rest_tb_target_power_get(self.target.rt)
        self.target.report_info("Got power")
        return r

    def off(self):
        """
        Power off a target
        """
        self.target.report_info("Powering off", dlevel = 1)
        self.target.rtb.rest_tb_target_power_off(
            self.target.rt, ticket = self.target.ticket)
        self.target.report_info("Powered off")

    def cycle(self, wait = None):
        """
        Power cycle a target
        """
        self.target.report_info("Power cycling", dlevel = 1)
        self.target.rtb.rest_tb_target_power_cycle(
            self.target.rt, ticket = self.target.ticket, wait = wait)
        self.target.testcase.tls.expecter.power_on_post(self.target)
        self.target.report_info("Power cycled")

    def reset(self):
        """
        Reset a target
        """
        self.target.report_info("Resetting", dlevel = 1)
        self.target.rtb.rest_tb_target_reset(
            self.target.rt, ticket = self.target.ticket)
        self.target.testcase.tls.expecter.power_on_post(self.target)
        self.target.report_info("Reset")
