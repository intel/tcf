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

from tcfl.commonl import testing
import tcfl.app_zephyr
import tcfl
import tcfl.tc

tcfl.tc.target_c.extension_register(tcfl.app_zephyr.zephyr)
if not tcfl.app.driver_valid(tcfl.app_zephyr.app_zephyr.__name__):
    tcfl.app.driver_add(tcfl.app_zephyr.app_zephyr)

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


    @tcfl.tc.target("zephyr_board",
                    app_zephyr = os.path.join(ZEPHYR_BASE,
                                              "samples/hello_world"))
    class _test_zephyr_hello_world(tcfl.tc.tc_c):
        def eval(self, target):
            self.expecter.timeout = 10
            # We can use bsp_model because we know we are using a BSP
            # model that consists in a single BSP, and thus bsp_model
            # and the BSP name match
            target.expect("Hello World! %s" % target.bsp_model)

    def test_zephyr_hello_world(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("found expected `Hello World! ")
        self.assertEqual(
            r, 0,
            "r not zero\n"
            "TCF log: " + "".join(open(self.args.log_file).readlines()))

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
