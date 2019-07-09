#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


import os
import sys
import unittest

from tcfl import commonl.testing
import tcfl
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
                os.path.join(_srcdir, "conf_base_interconnects.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()


    @tcfl.tc.interconnect("id == 'r'")
    class _test_00(tcfl.tc.tc_c):
        """
        We select an interconnect called 'r' and ensure we get said
        interconnect.
        """
        @staticmethod
        def eval(ic):
            assert ic.id == 'r'

    def test_00(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assert_in_tcf_log("1 passed")
        self.assertEqual(r, 0)



    @tcfl.tc.interconnect("id == 'r'")
    class _test_01(tcfl.tc.tc_c):
        """
        We select an interconnect called 'r' and ensure we get said
        interconnect; however, because we filtered so that we could
        only use interconnect 's', we will get skipped.
        """
        @staticmethod
        def eval(ic):
            assert ic.id == 'r'

    def test_01(self):
        def args_mod(args):
            args.target.append('s')

        r = self._tcf_run_cut(args_fn = args_mod)
        self.assert_not_in_tcf_log("AssertionError")
        self.assert_in_tcf_log("1 skipped")
        self.assertEqual(r, 0)



if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
