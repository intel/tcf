#! /usr/bin/python
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
import tcfl.app_zephyr
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
                os.path.join(_srcdir, "conf_07_zephyr.py"),
                os.path.join(_srcdir, "conf_zephyr_run_qemu.py"),
                os.path.join(_srcdir, "conf_zephyr_tests.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()


    @tcfl.tc.target("zephyr_board",
                    app_zephyr = os.path.join(ZEPHYR_BASE,
                                              "samples/hello_world"))
    class _test_zephyr_00_hello_world(tcfl.tc.tc_c):
        """
        Run Hello World in QEMU and works ok
        """
        @staticmethod
        def setup(target):
            target.on_console_rx("Hello World! %s" % target.bsp_model, 20,
                                 console = target.kws.get('console', None))

        def eval(self, target):
            self.expecter.run()

    def test_zephyr_00_hello_world(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("found expected `Hello World! ")
        self.assertEqual(r, 0)



class _test2(unittest.TestCase,
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
                os.path.join(_srcdir, "conf_zephyr_run_bad_qemu.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        try:
            commonl.testing.test_ttbd_mixin.tearDownClass()
        except RuntimeError as e:
            if 'ttbd has errors in the log' in e.message \
               and '-nodefaultssomethingwrong: invalid option' in e.message:
                # expected, this is the error we triggered
                pass
            else:
                raise

    @tcfl.tc.target("id == 'bad-qemu-01'",
                    app_zephyr = os.path.join(ZEPHYR_BASE,
                                              "samples/hello_world"))
    class _test_zephyr_01_hello_world(tcfl.tc.tc_c):
        """
        Try to start a QEMU target with bad configuration, it shall
        detect QEMU will fail to start. The bad configuration is
        stored in conf_zephyr_run_bad_qemu.py:bad-qemu-01
        """
        def eval(self, target):
            target.on_console_rx("Hello World! %s" % target.bsp, 20,
                                 console = target.kws.get('console', None))
            self.expecter.run()

    def test_zephyr_01_hello_world(self):
        self.exclude_errors.append('RuntimeError: QEMU x86: '
                                   'did not start after 2.00s')
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("bad-qemu-01: QEMU x86: did "
                               "not start after 2.00s")
        self.assertEqual(r, 127)

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
