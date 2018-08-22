#! /usr/bin/python2
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
import tcfl
import tcfl.tc
import tcfl.app_sketch

import conf_sketch

_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

arduino_libdir = getattr(tcfl.config, "arduino_libdir", None)

class _test(unittest.TestCase,
            commonl.testing.test_ttbd_mixin):

    # Uses test_tcf_mixin.setUpClass/tearDownClass
    longMessage = True

    @classmethod
    def setUpClass(cls):
        cls.src = _src
        commonl.testing.test_ttbd_mixin.setUpClass(
            ttbd_config_files = [
                os.path.abspath("conf_sketch_targets.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()



    @tcfl.tc.target(
        "id == 'a2-00-bo'",
        app_sketch = "../../qa.git/thirdparty/tcob/DueDev/arduino/sketch.ino")
    class _test_sketch_01(tcfl.tc.tc_c):
        # Build only target
        pass

    @unittest.skipIf(arduino_libdir == None,
                     "Missing Arduino environment")
    def test_sketch_01(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        # Should pass in a build only target
        self.assert_in_tcf_log("1 passed")
        self.assertEqual(r, 0)



    @tcfl.tc.target(
        "id == 'a2-00-bo'",
        app_sketch = "../../qa.git/thirdparty/tcob/DueDev/arduino/sketch.ino")
    class _test_sketch_02(tcfl.tc.tc_c):
        # Build only target
        pass

    @unittest.skipIf(arduino_libdir == None,
                     "Missing Arduino environment")
    def test_sketch_02(self):
        # Class Under Test is named as this function with _ prefixed.
        cut = eval("self._" + inspect.stack()[0][3])

        def args_mod(args):
            args.phases_skip.append("deploy")
            args.phases_skip.append("eval")

        r = self._tcf_run_cut(cut, args_mod)
        self.assert_in_tcf_log("1 passed")
        self.assertEqual(r, 0)

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
