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

import commonl.testing
import tcfl
import tcfl.app_zephyr
import tcfl.tc

tcfl.tc.target_c.extension_register(tcfl.app_zephyr.zephyr)
if not tcfl.app.driver_valid(tcfl.app_zephyr.app_zephyr.__name__):
    tcfl.app.driver_add(tcfl.app_zephyr.app_zephyr)


_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

class _test(unittest.TestCase, commonl.testing.test_tcf_mixin):
    """
    Target decorator tests
    """
    longMessage = True

    @classmethod
    def setUpClass(cls):
        cls.src = _src
        cls.srcdir = _srcdir
        commonl.testing.test_tcf_mixin.setUpClass()

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_tcf_mixin.tearDownClass()

    class _test_01(tcfl.tc.tc_c):
        """
        This should croak because configure is asking for a non existant
        target, as we are static (no targets defined)
        """
        def configure(self, non_existant_target):
            pass

    def test_01(self):
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log(
            "needs target named 'non_existant_target', which hasn't "
            "been declared with the @target class decorator (available: )")
        self.assertEqual(r, 127)

    @tcfl.tc.target()
    class _test_02(tcfl.tc.tc_c):
        """
        This should croak because configure is asking for a non
        existant target
        """
        def configure(self, non_existant_target):
            pass

    def test_02(self):
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log(
            "needs target named 'non_existant_target', which hasn't "
            "been declared with the @target class decorator "
            "(available: target)")
        self.assertEqual(r, 127)

    def test_03(self):
        with self.assertRaisesRegex(tcfl.tc.blocked_e,
                                     "invalid_keyword: unknown key"):
            @tcfl.tc.target(invalid_keyword = 'invalid_value')  # pylint: disable = unused-variable
            class _test_03(tcfl.tc.tc_c):
                """
                This should croak because we are trying to add
                an invalid keyword
                """
                @staticmethod
                def configure():
                    pass

    @tcfl.tc.target
    class _test_04(tcfl.tc.tc_c):
        """
        This should croak because the decorator needs parenthesis
        """
        # FIXME: we need a proper warning for this, it can't load it
        # and the adding empty () to the decorator is ugly
        @staticmethod
        def eval():
            pass

    def test_04(self):
        cut = eval("self._" + inspect.stack()[0][3])
        self._tcf_run_cut(cut)
        self.assert_in_tcf_log("(0 passed, 0 failed, 0 blocked, 0 skipped,")







class _test2(unittest.TestCase, commonl.testing.test_ttbd_mixin):
    """
    Target decorator tests

    Play with different BSP settings in the App builder
    """
    longMessage = True

    @classmethod
    def setUpClass(cls):
        cls.src = _src
        cls.srcdir = _srcdir
        commonl.testing.test_ttbd_mixin.setUpClass(
            ttbd_config_files = [
                os.path.join(cls.srcdir, "conf_base_tests.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()


    @tcfl.tc.target("bsp_count == 2",
                    app_zephyr = { 'bsp1': 'fakesource' })
    class _test2_01(tcfl.tc.tc_c):
        """
        This shall skip because we are asking for a 2 BSP bsp model and
        providing auto builder info for only one.
        """
        pass

    def test2_01(self):
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("can't use; conditions imposed by the spec")
        self.assert_in_tcf_log("1 skipped")
        self.assertEqual(r, 0, cut.__doc__ + self.tcf_log())


    @tcfl.tc.target(app_zephyr = { 'bsp1': 'fakesource' },
                    app_sketch = { 'bsp1': 'fakesource' })
    class _test2_02(tcfl.tc.tc_c):
        """
        This shall block because we are overriding a BSP with two app
        builders.
        """
        pass

    def test2_02(self):
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assertEqual(r, 127, cut.__doc__ + self.tcf_log())


    @tcfl.tc.target()
    class _test2_03(tcfl.tc.tc_c):
        """
        Will fail because there are no app_* builders defined, so when
        querying for one to do the thing, target.app_get()
        throw an exception.
        """
        @staticmethod
        def eval(target):
            for bsp in target.bsps:
                target.app_get(bsp, noraise = False)

    def test2_03(self):
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("eval blocked: "
                               "No App builders defined for target "
                               "'target', can't figure out what to do")
        self.assertEqual(r, 127)


    @tcfl.tc.target("zephyr_board",
                    app_zephyr = "__really_unexistant_source__")
    class _test2_04(tcfl.tc.tc_c):
        """
        Specifying a non-existing directory gives blockage
        """
        def eval(self, target):
            for bsp in target.bsps:
                # FIXME: there has to be a better way to do this, clearer
                target.app_get(bsp).eval_setup(self, target)
                target.on_console_rx("Hello World! %s" % bsp, 20,
                                     console = target.kws.get('console', None))

            # FIXME: there has to be a better way to do this, clearer --
            # we only have to start the target once for a BSP
            target.bsp_set()
            target.app_get(target.bsp).eval_start(self, target)
            # FIXME: replace with self.waitforthingstohappen?
            self.expecter.run()

    def test2_04(self):
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("__really_unexistant_source__: is not "
                               "a directory; cannot find App")
        self.assertEqual(r, 127)


    @tcfl.tc.target("bsp_model != 'bsp1' and bsp == 'bsp1'")
    class _test2_05(tcfl.tc.tc_c):
        """
        Should find only BSP model bsp1+bsp2
        """
        def eval(self, target):
            if target.bsp_model !=  "bsp1+bsp2":
                raise tcfl.tc.blocked_e("target's BSP model is %s"
                                        % target.bsp_model)
            self.report_info("worked ok")

    def test2_05(self):
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("worked ok")
        self.assertEqual(r, 0)


    @tcfl.tc.target(name = "sometargetname")
    class _test2_06(tcfl.tc.tc_c):
        """
        Declaring a target with a name different than the default
        works
        """
        def eval(self, sometargetname):
            self.report_info("worked ok")

    def test2_06(self):
        cut = eval("self._" + inspect.stack()[0][3])
        r = self._tcf_run_cut(cut)
        self.assert_in_tcf_log("worked ok")
        self.assertEqual(r, 0)

    def test2_07(self):
        with self.assertRaisesRegex(tcfl.tc.blocked_e,
                                     "target: unknown App builder "
                                     "'app_nonexistant' "):
            @tcfl.tc.target(app_nonexistant = "doesn't matter") # pylint: disable = unused-variable
            class _test2_07(tcfl.tc.tc_c):
                """
                Specifying a non-existing app builder gives blockage
                """
                def eval(self, target):
                    pass


if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
