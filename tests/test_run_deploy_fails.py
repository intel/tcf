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
import tcfl.tc

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
        cls.src = _src
        commonl.testing.test_ttbd_mixin.setUpClass(
            ttbd_config_files = [
                os.path.join(_srcdir, "conf_run_deploy_block.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()
        pass

    @tcfl.tc.target("zephyr_board")
    class _test_00(tcfl.tc.tc_c):
        """
        Test that when deploy fails, we pass the error up--the
        configuration is set to fail on images_*_set(), so the test
        has to block.
        """
        @staticmethod
        @tcfl.tc.serially()
        def deploy(target):
            target.images.retries = 3
            target.images.wait = 2
            target.images.upload_set("doesn't", "matter")

    def test_00(self):
        self.exclude_errors.append('RuntimeError("Failing on purpose")')
        self.exclude_errors.append("RuntimeError: Failing on purpose")
        r = self._tcf_run_cut()
        self.assert_in_tcf_log("deploy blocked")
        self.assert_in_tcf_log("1 blocked")
        self.assertEqual(r, 127)

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
