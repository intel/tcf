#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
import os
import sys
import time
import unittest

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)

ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target(ttbd.url_spec)
class _test_00(tcfl.tc.tc_c):
    """
    Test the console methods can be run
    """
    @staticmethod
    def eval(target):
        consoles = target.console.list()
        assert sorted(consoles) == sorted(['c1', 'c2', 'c3', 'c4']), \
            "List of read consoles (%s) differs from set" % consoles
        for console in consoles:
            ts = time.time()
            s = "%d" % ts
            target.console.enable(console)
            target.console.write(s, console = console)
            r = target.console.read(console = console)
            assert r == s, \
                "read data (%s) doesn't equal written data (%s)" % (r, s)

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
