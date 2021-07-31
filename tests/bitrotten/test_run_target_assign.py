#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
import os
import sys
import unittest

import commonl.testing
import tcfl
import tcfl.tc

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
                os.path.join(_srcdir, "conf_00_lib.py"),
                os.path.join(_srcdir, "conf_07_zephyr.py"),
                os.path.join(_srcdir, "conf_zephyr_run_qemu.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()


    @tcfl.tc.target()
    class _test_01(tcfl.tc.tc_c):
        """
        Acquire one target
        """
        def eval(self, target):
            self.report_info("1 targets acquired")
            pass

    def test_01(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("1 targets acquired")
        self.assertEqual(r, 0)


    @tcfl.tc.target()
    @tcfl.tc.target()
    class _test_02(tcfl.tc.tc_c):
        """
        Acquire two targets
        """
        def eval(self, target, target1):
            self.report_info("2 targets acquired")
            pass

    def test_02(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("2 targets acquired")
        self.assertEqual(r, 0)


    @tcfl.tc.target()
    @tcfl.tc.target()
    @tcfl.tc.target()
    class _test_03(tcfl.tc.tc_c):
        """
        Acquire two targets
        """
        def eval(self, target, target1, target2):
            self.report_info("3 targets acquired")
            pass

    def test_03(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("3 targets acquired")
        self.assertEqual(r, 0)


# FIXME: need more testcases for conflicting reservations where
# deadlocks could happen.

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
