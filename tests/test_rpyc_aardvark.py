#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Cannot find USB device with serial NODEVICE",
        "RuntimeError",
        "Traceback"
    ])


usb_serial_number = os.environ.get("AARDVARK_USB_SERIAL_NUMBER", "NODEVICE")

@tcfl.tc.target(ttbd.url_spec + " and t0")
class _test(tcfl.tc.tc_c):

    def eval_10(self, target):

        with self.subcase("power_on"):
            try:
                target.power.on()
            except Exception as e:
                if usb_serial_number == "NODEVICE" \
                   and 'Cannot find USB device with serial NODEVICE' not in str(e):
                    raise
                target.report_pass("expected failure to power on")
                return

        # Can't really test much more without a USB device to testwith
        with self.subcase("connect"):
            remote = tcfl.tl.rpyc_connect(target, "aa0")
            target.report_pass("aa0 connects")

        with self.subcase("import"):
            aardvark_py = remote.modules['aardvark_py']

        with self.subcase("find"):
            r, _handles, _ids = aardvark_py.aa_find_devices_ext(1, 1)

        with self.subcase("devices"):
            if r == 0:
                raise tcfl.tc.skip_e("No HW available")
            # no devices, can't test HW

            assert r > 0
            handle = aardvark_py.aa_open(0)
            features = aardvark_py.aa_features(handle)
            assert features == 27
            target.report_pass("Aardvark: features is 27")
            aardvark_py.aa_close(handle)

        with self.subcase("power_off"):
            target.power.off()

    def teardown_90_scb(self):
        with self.subcase("server-check"):
            ttbd.check_log_for_issues(self)
