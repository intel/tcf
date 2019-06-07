#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
import os
import re
import sys
import unittest

import commonl.testing
import tcfl
import tcfl.tc

_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

class _test(unittest.TestCase, commonl.testing.test_tcf_mixin):

    # Uses test_tcf_mixin.setUpClass/tearDownClass
    longMessage = True

    @classmethod
    def setUpClass(cls):
        cls.src = _src
        commonl.testing.test_tcf_mixin.setUpClass()

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_tcf_mixin.tearDownClass()


    class _testcase_static_01(tcfl.tc.tc_c):

        def configure(self):
            pass

        def build(self):
            pass

        def deploy(self):
            pass

        def eval(self):
            pass

        def clean(self):
            pass

    def testcase_static_01(self):
        r = self._tcf_run_cut()
        self.assertEqual(r, 0)


    def _testcase_static_method(self, cut):
        #
        # expect it to complain about
        # invalid methods
        #
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log(
            re.compile(r"%s.(configure|build|deploy|eval|clean)\(\): "
                       r"not a valid method" % cut.__name__))
        self.assertEqual(r, 127)


    class _testcase_static_02_configure(tcfl.tc.tc_c):
        """
        Bad method declaration (no self/static/class), shall fail with
        blocked
        """
        def configure():	# pylint: disable = no-method-argument
            pass

    def testcase_static_02_configure(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        self._testcase_static_method(cut)



    class _testcase_static_02_build(tcfl.tc.tc_c):
        """
        Bad method declaration (no self/static/class), shall fail with
        blocked
        """
        def build():		# pylint: disable = no-method-argument
            pass

    def testcase_static_02_build(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        self._testcase_static_method(cut)



    class _testcase_static_02_deploy(tcfl.tc.tc_c):
        """
        Bad method declaration (no self/static/class), shall fail with
        blocked
        """
        def deploy():		# pylint: disable = no-method-argument
            pass

    def testcase_static_02_deploy(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        self._testcase_static_method(cut)



    class _testcase_static_02_eval(tcfl.tc.tc_c):
        """
        Bad method declaration (no self/static/class), shall fail with
        blocked
        """
        def eval():		# pylint: disable = no-method-argument
            pass

    def testcase_static_02_eval(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        self._testcase_static_method(cut)



    class _testcase_static_02_clean(tcfl.tc.tc_c):
        """
        Bad method declaration (no self/static/class), shall fail with
        blocked
        """
        def clean():		# pylint: disable = no-method-argument
            pass

    def testcase_static_02_clean(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        self._testcase_static_method(cut)



    class _test_static_03_eval_pass(tcfl.tc.tc_c):
        """
        Static testcase with simple evaluation shall pass
        """
        def eval(self):
            self.shcmd_local('echo sample pass; true')

    def test_static_03_eval_pass(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("eval output: sample pass")
        self.assertEqual(r, 0)



    class _test_static_03_eval_block(tcfl.tc.tc_c):
        """
        Static testcase with simple evaluation shall block
        """
        def eval(self):
            self.shcmd_local('echo sample blockage; nonexistant_shell_command')

    def test_static_03_eval_block(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("eval output: sample blockage")
        self.assertEqual(r, 127)



    class _test_static_03_eval_fail(tcfl.tc.tc_c):
        """
        Static testcase with simple evaluation shall fail
        """
        def eval(self):
            self.shcmd_local('echo sample fail; false')

    def test_static_03_eval_fail(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("eval output: sample fail")
        self.assertEqual(r, 1)



    class _test_03_methods(tcfl.tc.tc_c):
        """
        Static testcase verifying that we run eval methods first, then
        test methods with the right start / setup / teardown
        combinations

        Each method prints it's name to a string that keeps being
        accumulating and the last teardown prints it. We verify the
        string has the right sequence (which will be printed by the
        last call to teardown_02().
        """
        s = ""

        def setup_01(self):
            self.s += "setup_01:"

        def setup_02(self):
            self.s += "setup_02:"

        def start_01(self):
            self.s += "start_01:"

        def start_02(self):
            self.s += "start_02:"

        def eval_01(self):
            self.s += "eval_01:"

        def eval_02(self):
            self.s += "eval_02:"

        def test_01(self):
            self.s += "test_01:"

        def test_02(self):
            self.s += "test_02:"

        def teardown_01(self):
            self.s += "teardown_01:"

        def teardown_02(self):
            self.s += "teardown_02:"
            self.report_info("TEARDOWN %s" % self.s)

    def test_03_methods(self):
        r = self._tcf_run_cut()
        self.assert_in_tcf_log(
            "setup_01:setup_02:start_01:start_02:eval_01:eval_02:teardown_01:teardown_02:"
            "setup_01:setup_02:start_01:start_02:test_01:teardown_01:teardown_02:"
            "setup_01:setup_02:start_01:start_02:test_02:teardown_01:teardown_02:")
        self.assertEqual(r, 0)

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
