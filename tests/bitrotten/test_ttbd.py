#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import argparse
import os
import sys
import unittest

import commonl.testing
import tcfl
import tcfl.tc

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
                os.path.join(_srcdir, "conf_base_tests.py"),
                os.path.join(_srcdir, "conf_zephyr_tests.py"),
                os.path.join(_srcdir, "conf_07_zephyr.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()
        pass

    @staticmethod
    def test_acquire_release():
        # just get the daemon to start and stop
        args = argparse.Namespace
        args.target = [ "t0" ]
        args.ticket = None
        args.force = False
        tcfl.ttb_client.rest_target_acquire(args)
        tcfl.ttb_client.rest_target_release(args)
        pass

    @staticmethod
    def test_power_on_off():
        # just get the daemon to start and stop
        args = argparse.Namespace
        args.target = [ "t0" ]
        args.ticket = None
        args.force = False
        tcfl.ttb_client.rest_target_acquire(args)
        tcfl.ttb_client.rest_target_power_on(args)
        tcfl.ttb_client.rest_target_power_off(args)
        tcfl.ttb_client.rest_target_release(args)
        pass

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
