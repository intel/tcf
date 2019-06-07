#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import sys
import unittest

import commonl.testing
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
                os.path.join(_srcdir, "conf_base_tests.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()


    @tcfl.tc.target(mode = "any")
    class _test_mode_00(tcfl.tc.tc_c):
        """
        Request mode 'any' shall run only one target, even if multiple
        types are available
        """
        def eval(self):
            pass

    def test_mode_00(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assert_in_tcf_log("1 passed")
        self.assertEqual(r, 0)


    @tcfl.tc.target(mode = "any")
    @tcfl.tc.target(mode = "any")
    class _test_mode_01(tcfl.tc.tc_c):
        """
        Request mode 'any' for two targets shall run only one target pair,
        even if multiple types are available,
        """
        def eval(self):
            pass

    def test_mode_01(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assert_in_tcf_log("1 passed")
        self.assertEqual(r, 0)


    @tcfl.tc.target(mode = "any")
    @tcfl.tc.target(mode = "one-per-type")
    class _test_mode_02(tcfl.tc.tc_c):
        """
        Request mode 'any' for one targets, one-per-type for each
        shall run on each type for one target, any for the other, as many
        target types as available. In this case, it is three because
        the targets have three different BSP-models, that count as a
        different type for this.
        """
        def eval(self):
            pass

    def test_mode_02(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assert_in_tcf_log("3 passed")
        self.assertEqual(r, 0)


    @tcfl.tc.target(mode = "one-per-type")
    @tcfl.tc.target(mode = "one-per-type")
    class _test_mode_03(tcfl.tc.tc_c):
        """
        Request mode 'one-per-type' for both targets will generate
        nine TCs, as targets have three different BSP-models.
        """
        def eval(self):
            pass

    def test_mode_03(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        # We check on anything from 4 to 9, as it might not generate
        # the 9 of them based on the random permutation generator,
        # that will give up at some point always.
        self.assert_in_tcf_log(re.compile("[456789] passed"))
        self.assertEqual(r, 0)


    @tcfl.tc.target(mode = "all")
    class _test_mode_04(tcfl.tc.tc_c):
        """
        Request mode 'all' shall run in every single available target
        for a single wanted target.
        """
        def eval(self):
            pass

    def test_mode_04(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        # We have 9 targets, 3 BSP models each -- but sometimes,
        # depending on the random selection, more or less can come up,
        # so be flexible
        self.assert_in_tcf_log(re.compile("[23][0-9] passed"))
        self.assertEqual(r, 0)



if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
