#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
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
    """
    Validate the innars of the API extension system for target_c
    """
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
        pass


    class _test_01_extension(tcfl.tc.target_extension_c):
        def __init__(self, target):
            target.report_info("ALWAYS NONE EXTENSION")
            raise self.unneeded

    @tcfl.tc.target()
    class _test_01(tcfl.tc.tc_c):
        """
        Tests that an extension that raises
        target_extension_c.unneeded during it's __init__ method doesn't
        get an extension object attached to the target.
        """
        @staticmethod
        def eval(target):
            assert not hasattr(target, "_test_01_extension")
            target.report_info("__DONE__")

    def test_01(self):
        try:
            tcfl.tc.target_c.extension_register(self._test_01_extension)
            cut = eval("self._" + inspect.stack()[0][3])
            r = self._tcf_run_cut(cut)
            self.assert_in_tcf_log("ALWAYS NONE EXTENSION")
            self.assert_in_tcf_log("__DONE__")
            self.assertEqual(r, 0)
        finally:
            tcfl.tc.target_c.extension_unregister(self._test_01_extension)


    class _test_02_extension(tcfl.tc.target_extension_c):
        def __init__(self, target):
            target.report_info("ALWAYS EXTENSION")

        def method(self):
            self.target.report_info("EXTENSION API CALL")

    @tcfl.tc.target()
    class _test_03(tcfl.tc.tc_c):
        """Tests that an extension that does not raise
        target_extension_c.unneeded during it's __init__ method gets
        an extension object attached to the target. Also test any
        method of the extension API is callable via the object created.
        """
        @staticmethod
        def eval(target):
            assert hasattr(target, "_test_02_extension")
            target.report_info("__DONE__")
            target._test_02_extension.method()

    def test_03(self):
        try:
            tcfl.tc.target_c.extension_register(self._test_02_extension)
            cut = eval("self._" + inspect.stack()[0][3])
            r = self._tcf_run_cut(cut)
            self.assert_in_tcf_log("ALWAYS EXTENSION")
            self.assert_in_tcf_log("EXTENSION API CALL")
            self.assert_in_tcf_log("__DONE__")
            self.assertEqual(r, 0)
        finally:
            tcfl.tc.target_c.extension_unregister(self._test_02_extension)



if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
