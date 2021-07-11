#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import hashlib
import os
import time

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Traceback"
    ])


@tcfl.tc.target(ttbd.url_spec + " and t0")
class _test(tcfl.tc.tc_c):
    """
    Test the ttbl.power.daemon_c class
    """

    @tcfl.tc.subcase()
    def eval_10_power_on(self, target):
        target.power.on()
        state, _, _ = target.power.list()
        assert state == True
        target.report_pass("target reports on")


    @tcfl.tc.subcase()
    def eval_20_power_off(self, target):
        target.power.off()
        state, _, _ = target.power.list()
        assert state == False
        target.report_pass("target reports off")


    @tcfl.tc.subcase()
    def eval_30_power_on(self, target):
        target.power.on()
        state, _, _ = target.power.list()
        assert state == True
        target.report_pass("target reports on")


    @tcfl.tc.subcase()
    def eval_40_power_off(self, target):
        target.power.off()
        state, _, _ = target.power.list()
        assert state == False
        target.report_pass("target reports off")


    def teardown_90_scb(self):
        with self.subcase("server-check"):
            ttbd.check_log_for_issues(self)
