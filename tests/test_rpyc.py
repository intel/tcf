#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import hashlib
import os
import time

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
            time.sleep(2)

        with self.subcase("connect"):
            # target.certs.get() will cache this in target.tmpdir;
            # when we re-run with the same tempdir, it catches it, so
            # wipe'em. FIXME: use the target's allocid to feed into
            # the tmpdir name to avoid this possible conflict.
            commonl.rm_f(os.path.join(target.tmpdir, "client.default.key"))
            commonl.rm_f(os.path.join(target.tmpdir, "client.default.cert"))
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

        with self.subcase("run_file"):
            # the server has been configfured to touch a file in the
            # container environment upon power on
            try:
                with remote0.builtins.open("/tmp/runthisexecuted",
                                           encoding = "utf-8") as f:
                    expected_content = 'ein belegtes Brot mit Schinken'
                    content = f.read().strip()
                    if content == expected_content:
                        target.report_pass("run_file executed properly")
                    else:
                        target.report_fail(
                            "run_file content doesn't match expected?",
                            dict(
                                expected_content = expected_content,
                                expected_content_type = type(expected_content).__name__,
                                read_content = content,
                                read_content_type = type(content).__name__,
                            ),
                            level = 0)
            except Exception as e:
                target.report_fail(
                    "run_file didn't run? can't open file",
                    dict(exception = e), level = 0)

        with self.subcase("power_off"):
            target.power.off()

    def teardown_90_scb(self):
        with self.subcase("server-check"):
            ttbd.check_log_for_issues(self)
