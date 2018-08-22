#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


import os
import sys
import unittest

import commonl.testing
import tcfl
import tcfl.app_zephyr
import tcfl.tc
import tcfl.tc_zephyr_sanity


zephyr_vars = set(['ZEPHYR_BASE', 'ZEPHYR_SDK_INSTALL_DIR',
                   'ZEPHYR_TOOLCHAIN_VARIANT'])
zephyr_vars_missing = zephyr_vars - set(os.environ.keys())
assert len(zephyr_vars_missing) == 0, \
    "Missing Zephyr environment (%s), can't run" \
    % " ".join(list(zephyr_vars_missing))

ZEPHYR_BASE = os.environ['ZEPHYR_BASE']

_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

class _test(unittest.TestCase,
            commonl.testing.test_ttbd_mixin):
    longMessage = True

    @classmethod
    def setUpClass(cls):
        tcfl.app.driver_add(tcfl.app_zephyr.app_zephyr)
        tcfl.tc.target_c.extension_register(tcfl.app_zephyr.zephyr)
        tcfl.tc.tc_c.driver_add(tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c)

        cls.src = _src
        commonl.testing.test_ttbd_mixin.setUpClass(
            ttbd_config_files = [
                os.path.join(_srcdir, "conf_00_lib.py"),
                os.path.join(_srcdir, "conf_07_zephyr.py"),
                os.path.join(_srcdir, "conf_zephyr_tests.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()
        pass


    # Class here we mainly use it to document...

    class _test_zsc_00(tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c):
        """
        Testcase that rejects an skip
        """

    @unittest.skipIf(zephyr_vars_missing,
                     "Missing Zephyr environment (%s), can't run"
                     % " ".join(list(zephyr_vars_missing)))
    def test_zsc_00(self):
        # Class Under Test is named as this function with _ prefixed.
        r = self._tcf_run_cut(
            filename = os.path.join(_srcdir, "testcase_zsc_00.ini"),
            testcase_name_postfix = "#test")
        self.assert_in_tcf_log("skipped: test: test case skipped")
        self.assertEqual(r, 0)


    class _test_zsc_01(tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c):
        """
        Requests two arch and platform whitelists and excludes, it
        will be skipped.
        """

    @unittest.skipIf(zephyr_vars_missing,
                     "Missing Zephyr environment (%s), can't run"
                     % " ".join(list(zephyr_vars_missing)))
    def test_zsc_01(self):
        r = self._tcf_run_cut(
            filename = os.path.join(_srcdir, "testcase_zsc_01.ini"),
            testcase_name_postfix = "#test")
        self.assert_in_tcf_log("1 skipped")
        self.assertEqual(r, 0)


    class _test_zsc_02(tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c):
        """
        Testcase that
        """

    @unittest.skipIf(zephyr_vars_missing,
                     "Missing Zephyr environment (%s), can't run"
                     % " ".join(list(zephyr_vars_missing)))
    def test_zsc_02(self):

        def say_skip_build(args):
            args.phases_skip.append("build")

        r = self._tcf_run_cut(
            filename = os.path.join(_srcdir, "testcase_zsc_02.ini"),
            testcase_name_postfix = "#test",
            args_fn = say_skip_build)
        self.assert_in_tcf_log("testcase is build only: "
                               "skipping deploy and eval")
        self.assertEqual(r, 0)

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
