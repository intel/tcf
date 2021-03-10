#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import time
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

@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _healthcheck(tcfl.tc.tc_c):
    @staticmethod
    def eval_00(target):
        target.capture._healthcheck()

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)

@tcfl.tc.target(ttbd.url_spec + ' and t1')
class _1(tcfl.tc.tc_c):

    def eval_00(self, target):
        # capture to a file
        target.capture.start('stream0')
        time.sleep(2)
        target.capture.stop_and_get('stream0', self.report_file_prefix + "file")

        # capture to JSON
        target.capture.start('stream0')
        time.sleep(2)
        r = target.capture.stop_and_get('stream0', False)
        # from the config file; this capture always returns the same
        assert 'data' in r
        assert r['data'] == 1


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
