#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


import os
import sys
import unittest

from tcfl import commonl.testing
import tcfl
import tcfl.app
import tcfl.tc

import conf_app_test_tcf

if not tcfl.app.driver_valid(conf_app_test_tcf.app_test.__name__):
    tcfl.app.driver_add(conf_app_test_tcf.app_test)

_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

class _test(unittest.TestCase,
            commonl.testing.test_ttbd_mixin):
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

    # Use s* targets, only one BSP, no need for stubbing
    @tcfl.tc.target('id:"^s"', app_test = "not_important")
    class _test_00(tcfl.tc.tc_c):
        """
        Test that we can override the app builder's defined actions;
        an 'app_test' will set target.app_test[PHASENAME] = True if
        the app_builder is run, instead of ours, which does nothing.
        """

        def build_50_target(self, target):
            target.report_info("Running overriden build command")
            assert getattr(target, "app_test", None) == None, \
            "app_test buffer has " \
            "been created, this means we didn't override"

            self.overriden_build_50_target(target)
            assert getattr(target, "app_test", None) != None, \
            "app_test buffer has not been created, "\
            "this means we didn't call overriden_build_50_target()"
            assert 'build' in target.app_test

        def eval(self):
            pass

    def test_00(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assert_in_tcf_log("1 passed")
        self.assert_in_tcf_log("0 blocked")
        self.assert_in_tcf_log("0 failed")
        self.assertEqual(r, 0)


if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
