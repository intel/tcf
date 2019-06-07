#! /usr/bin/python2
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
    os.path.join(srcdir, "conf_run_console.py")
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
            target.console.write(s, console_id = console)
            r = target.console.read(console_id = console)
            assert r == s, \
                "read data (%s) doesn't equal written data (%s)" % (r, s)

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(1, 0, 0, 0, 0), \
            "%s: expected 1 testcase passed, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)
