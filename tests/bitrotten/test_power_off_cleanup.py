#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import sys
import time
import unittest

from tcfl.commonl import testing
import tcfl
import tcfl.ttb_client
import ttbl.config

_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

class _test(unittest.TestCase,
            commonl.testing.test_ttbd_mixin):

    # Uses test_tcf_mixin.setUpClass/tearDownClass
    longMessage = True

    @classmethod
    def setUpClass(cls):
        cls.src = _src
        commonl.testing.test_ttbd_mixin.setUpClass(
            ttbd_config_files = [
                os.path.join(_srcdir, "conf_base_tests.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()

    def test_auto_power_off_if_idle(self):
        rtb, rt = tcfl.ttb_client._rest_target_find_by_id("t0")
        rtb.rest_tb_target_acquire(rt)
        rtb.rest_tb_target_power_cycle(rt)		     # Power on
        time.sleep(1)
        self.assertTrue(rtb.rest_tb_target_power_get(rt))    # Shall be on
        rtb.rest_tb_target_release(rt)

        time.sleep(ttbl.config.target_max_idle * 1.2)        # wait to idle
        self.assertFalse(rtb.rest_tb_target_power_get(rt))   # Shall be off

    def test_auto_power_off_if_idle_and_read_unacquired(self):
        rtb, rt = tcfl.ttb_client._rest_target_find_by_id("t0")
        rtb.rest_tb_target_acquire(rt)
        rtb.rest_tb_target_power_cycle(rt)                   # Power on
        time.sleep(1)
        self.assertTrue(rtb.rest_tb_target_power_get(rt))    # Shall be on
        rtb.rest_tb_target_release(rt)

        ts = time.time()
        ts0 = ts
        # Wait for it to reach the max idle timeout, but reading in
        # the meantime, while unacquired.
        while ts - ts0 < ttbl.config.target_max_idle * 1.2:
            rtb.rest_tb_target_console_read(rt, None, 0)
            time.sleep(2)
            ts = time.time()
        self.assertFalse(rtb.rest_tb_target_power_get(rt))    # Shall be off


    def test_not_auto_power_off_if_idle_and_read_acquired(self):
        rtb, rt = tcfl.ttb_client._rest_target_find_by_id("t0")
        rtb.rest_tb_target_acquire(rt)
        rtb.rest_tb_target_power_cycle(rt)                   # Power on
        time.sleep(1)
        self.assertTrue(rtb.rest_tb_target_power_get(rt))    # Shall be on

        ts = time.time()
        ts0 = ts
        # Wait for it to reach the max idle timeout, but reading in
        # the meantime, while acquired.
        while ts - ts0 < ttbl.config.target_max_idle * 1.2:
            rtb.rest_tb_target_console_read(rt, None, 0)
            time.sleep(2)
            ts = time.time()
        self.assertTrue(rtb.rest_tb_target_power_get(rt))    # Shall be on
        rtb.rest_tb_target_release(rt)


if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
