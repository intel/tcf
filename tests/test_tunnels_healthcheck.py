#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

import commonl.testing
import tcfl
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])


@tcfl.tc.target(ttbd.url_spec)
class _test(tcfl.tc.tc_c):
    """
    Run the tunnel basic healthcheck
    """

    @staticmethod
    def eval(target):
        target.tunnel._healthcheck()

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
