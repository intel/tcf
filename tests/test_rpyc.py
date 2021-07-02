#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import hashlib
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
        "Traceback"
    ])



@tcfl.tc.target(ttbd.url_spec + " and t0")
class _test(tcfl.tc.tc_c):

    def eval_10(self, target):

        with self.subcase("power_on"):
            target.power.on()

        with self.subcase("connect"):
            remote0 = tcfl.tl.rpyc_connect(target, "c0")
            target.report_pass("remote rpyc connects")

        with self.subcase("hashlib_import"):
            hashlib0 = remote0.modules['hashlib']
            target.report_pass("remote hashlib imports")

        with self.subcase("hash"):
            h = hashlib.sha512("this is a silly test".encode('ascii'))
            h0 = hashlib0.sha512("this is a silly test".encode('ascii'))
            if h.hexdigest() == h0.hexdigest():
                target.report_pass("remote and local hashes match")
            else:
                target.report_fail("remote and local hashes don't match",
                                   dict(h0 = h0.hexdigest(), h = h.hexdigest()))

        with self.subcase("power_off"):
            target.power.off()

    def teardown_90_scb(self):
        with self.subcase("server-check"):
            ttbd.check_log_for_issues(self)
