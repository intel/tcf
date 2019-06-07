#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
import os
import sys
import unittest

import commonl.testing
import tcfl.tc

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
                os.path.join(_srcdir, "conf_run_power.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()
        pass

    @tcfl.tc.target()
    class _test_00(tcfl.tc.tc_c):
        """
        Test the power methods can be run
        """
        @staticmethod
        def eval(target):
            target.power.on()
            r = target.power.get()
            assert r == True, "power state is %s" % r

            target.power.off()
            r = target.power.get()
            assert r == False, "power state is %s" % r

            target.power.cycle()
            r = target.power.get()
            assert r == True, "power state is %s" % r

            target.power.off()
            r = target.power.get()
            assert r == False, "power state is %s" % r

            target.power.reset()
            r = target.power.get()
            assert r == True, "power state is %s" % r

    def test_00(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("1 passed")
        self.assertEqual(r, 0)

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
