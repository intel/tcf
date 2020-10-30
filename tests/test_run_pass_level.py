#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import re
import os
import sys
import unittest

from tcfl import commonl.testing
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
                os.path.join(_srcdir, "conf_zephyr_tests.py"),
                os.path.join(_srcdir, "conf_07_zephyr.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()


    @tcfl.tc.target(mode = 'any')
    class _test_00_pass(tcfl.tc.tc_c):
        """
        A test that passes doesn't print a final PASS0 message, but a PASS1
        """
        def eval(self, target):
            self.report_info("I pass")

    def test_00_pass(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log(re.compile(r"^PASS0/[^\s]+\s*.*"))
        self.assert_in_tcf_log(re.compile("^PASS1/.*"))
        self.assertEqual(r, 0)


    @tcfl.tc.target(mode = 'any')
    class _test_01_fail(tcfl.tc.tc_c):
        """
        A test that fails prints FAIL0 message
        """
        @staticmethod
        def eval(target):
            raise tcfl.tc.failed_e("I fail")

    def test_01_fail(self):
        r = self._tcf_run_cut()
        self.assert_in_tcf_log(re.compile(r"^FAIL0/[^\s]+\s*.*"))
        self.assertEqual(r, 1)


    @tcfl.tc.target(mode = 'any')
    class _test_01_block(tcfl.tc.tc_c):
        """
        A test that fails prints BLCK0 message
        """
        @staticmethod
        def eval(target):
            raise tcfl.tc.blocked_e("I block")

    def test_01_block(self):
        r = self._tcf_run_cut()
        self.assert_in_tcf_log(re.compile(r"^BLCK0/[^\s]+\s*.*"))
        self.assertEqual(r, 127)

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
