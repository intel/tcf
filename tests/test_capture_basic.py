#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
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
        "Traceback"
    ])

@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _healthcheck(tcfl.tc.tc_c):
    @staticmethod
    def eval_00(target):
        target.capture._healthcheck()

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
