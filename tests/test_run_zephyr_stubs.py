#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import sys
import unittest

from tcfl import commonl.testing
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
    longMessage = True

    @classmethod
    def setUpClass(cls):
        cls.src = _src
        commonl.testing.test_ttbd_mixin.setUpClass(
            ttbd_config_files = [
                os.path.join(_srcdir, "conf_00_lib.py"),
                os.path.join(_srcdir, "conf_07_zephyr.py"),
                os.path.join(_srcdir, "conf_zephyr_tests3.py"),
            ])
        # FIXME: this shall be researched, why is it happening?
        cls.exclude_errors.append(
            re.compile(r"ttbd\.cleanup_process_fn.*Exception cleaning up: "
                       r".*No such file or directory: .*ttbd-files.*"))

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()
        pass

    @tcfl.tc.target(
        "id == 'za-03' and bsp_model == 'x86'",
        app_zephyr = dict(
            x86 = os.path.join(ZEPHYR_BASE, "samples/hello_world")))
    class _test_stub_00(tcfl.tc.tc_c):
        """
        Asking for a 3-BSP target on a 1 BSP-model runs on BSP x86 but
        stubs Nios2 and ARM.
        """
        def setup(self, target):
            self.expecter.timeout = 10
            for bsp in target.bsps:
                target.bsp_set(bsp)
                target.on_console_rx("Hello World! %s" % target.bsp,
                                     console = target.kws.get('console', None))

        def eval(self, target):
            self.expecter.run()

    def test_stub_00(self):
        r = self._tcf_run_cut()
        self.assert_in_tcf_log(re.compile(
            r"will run on target group 'target=localhost/[^\s]+:x86'"))
        self.assert_in_tcf_log(re.compile(
            r"deployed .*"
            r"kernel-x86:.*/outdir-.*/zephyr\.elf"))
        self.assert_in_tcf_log(re.compile(
            r"deployed .*"
            r"kernel-arm:.*/outdir-.*/zephyr\.elf"))
        self.assert_in_tcf_log(re.compile(
            r"deployed .*"
            r"kernel-nios2:.*/outdir-.*/zephyr\.elf"))
        self.assertEqual(r, 0)


    @tcfl.tc.target(
        "id == 'za-03' and bsp_model == 'x86'",
        app_zephyr = dict(
            x86 = os.path.join(ZEPHYR_BASE, "samples/hello_world")))
    class _test_stub_01(tcfl.tc.tc_c):
        """
        Asking for a 3-BSP target on a 1 BSP-model runs on BSP x86 but
        stubs Nios2, as we ask for ARM not to be stubbed.
        """

        @staticmethod
        @tcfl.tc.serially()
        def build(target):
            del target.bsps_stub['arm']

        def setup(self, target):
            self.expecter.timeout = 10
            for bsp in target.bsps:
                target.bsp_set(bsp)
                target.on_console_rx("Hello World! %s" % target.bsp,
                                     console = target.kws.get('console', None))

        def eval(self, target):
            self.expecter.run()

    def test_stub_01(self):
        r = self._tcf_run_cut()
        self.assert_in_tcf_log(re.compile(
            r"will run on target group 'target=localhost/[^\s]+:x86'"))
        self.assert_in_tcf_log(re.compile(
            r"deployed .*"
            r"kernel-x86:.*/outdir-.*/zephyr\.elf"))
        self.assert_in_tcf_log(re.compile(
            r"deployed .*"
            r"kernel-nios2:.*/outdir-.*/zephyr\.elf"))
        self.assert_not_in_tcf_log(re.compile(
            r"deployed .*"
            r"kernel-arm:.*/outdir-.*/zephyr\.elf"))
        self.assertEqual(r, 0)


    @tcfl.tc.target(
        "id == 'za-03' and bsp_model == 'x86'",
        app_zephyr = dict(
            x86 = os.path.join(ZEPHYR_BASE, "samples/hello_world")))
    class _test_stub_02(tcfl.tc.tc_c):
        """
        Asking for a 3-BSP target on a 1 BSP-model runs on BSP x86 but
        stubs Nios2; ARM's information is removed as if it was never
        initialized. The system shall complain about a missing stub info.
        """
        @staticmethod
        @tcfl.tc.serially()
        def deploy(target):
            # app_zephyr adds stubbing info in build(), so we inject it here
            target.bsps_stub['arm'] = (None, None, None)

        def setup(self, target):
            self.expecter.timeout = 10
            for bsp in target.bsps:
                target.bsp_set(bsp)
                target.on_console_rx("Hello World! %s" % target.bsp,
                                     console = target.kws.get('console', None))
            app_zephyr.eval_start(self, target)

        def eval(self, target):
            self.expecter.run()

    def test_stub_02(self):
        r = self._tcf_run_cut()
        self.assert_in_tcf_log(re.compile(
            r"will run on target group 'target=localhost/[^\s]+:x86'"))
        self.assert_in_tcf_log(re.compile(
            "deploy blocked: arm: BSP has to be stubbed"))
        self.assertEqual(r, 127)



if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
