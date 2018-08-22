#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import re
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
    longMessage = True

    @classmethod
    def setUpClass(cls):
        cls.src = _src
        commonl.testing.test_ttbd_mixin.setUpClass(
            ttbd_config_files = [
                os.path.join(_srcdir, "conf_00_lib.py"),
                os.path.join(_srcdir, "conf_07_zephyr.py"),
                os.path.join(_srcdir, "conf_zephyr_tests.py"),
            ])

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()
        pass

    def test_00(self):
        with self.assertRaises(tcfl.tc.blocked_e):
            @tcfl.tc.tags()	# pylint: disable = unused-variable
            class _test_00(tcfl.tc.tc_c):
                # Request no tags, it shall fail
                pass


    @tcfl.tc.tags("tag1", tag2 = "value2")
    class _test_01(tcfl.tc.tc_c):
        """
        Request boolean and keyword tags
        """
        def eval(self):
            assert 'tag1' in self._tags
            assert self.tag_get('tag1', None)[0] == True
            assert 'tag2' in self._tags
            assert self.tag_get('tag2', None)[0] == "value2"

    def test_01(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags("tag1")
    class _test_02(tcfl.tc.tc_c):
        """
        Request a boolean tag
        """
        def eval(self):
            assert 'tag1' in self._tags
            assert self.tag_get('tag1', None)[0] == True

    def test_02(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags(tag2 = "value2")
    class _test_03(tcfl.tc.tc_c):
        """
        Request a keyword tag
        """
        def eval(self):
            assert 'tag2' in self._tags
            assert self.tag_get('tag2', None)[0] == "value2"

    def test_03(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags("tag1")
    class _test_04(tcfl.tc.tc_c):
        """
        Request boolean tag, filter on it being there
        """
        def eval(self):
            assert 'tag1' in self._tags
            assert self.tag_get('tag1', None)[0] == True

    def test_04(self):
        def say_tags(args):
            args.tags_spec.append("tag1")
        r = self._tcf_run_cut(args_fn = say_tags)
        self.assert_in_tcf_log("_test_04 @local: selected by tag specification")
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags("tag1")
    class _test_05(tcfl.tc.tc_c):
        """
        Request boolean tag, filter on it not being there
        """
        def eval(self):
            assert 'tag1' in self._tags
            assert self.tag_get('tag1', None)[0] == True

    def test_05(self):
        def say_tags(args):
            args.tags_spec.append("not tag1")
        r = self._tcf_run_cut(args_fn = say_tags)
        self.assert_in_tcf_log(
            "_test_05 @local: skipped: because of tag specification")
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags("tag1")
    class _test_06(tcfl.tc.tc_c):
        """
        Request boolean tag, filter on it not being there
        """
        def eval(self):
            assert 'tag2' not in self._tags

    def test_06(self):
        def say_tags(args):
            args.tags_spec.append("not tag2")
        r = self._tcf_run_cut(args_fn = say_tags)
        self.assert_in_tcf_log(
            "_test_06 @local: selected by tag specification")
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags(tag2 = "value2")
    class _test_06b(tcfl.tc.tc_c):
        """
        Request keyword tag, filter on the value being there
        """
        def eval(self):
            assert 'tag2' in self._tags
            assert self.tag_get('tag2', None)[0] == "value2"

    def test_06b(self):
        def say_tags(args):
            args.tags_spec.append("tag2 == 'value2'")
        r = self._tcf_run_cut(args_fn = say_tags)
        self.assert_in_tcf_log(
            "_test_06b @local: selected by tag specification")
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags(tag2 = "value2")
    class _test_07(tcfl.tc.tc_c):
        """
        Request keyword tag, filter on the value not being something
        """
        def eval(self):
            assert 'tag2' in self._tags
            assert self.tag_get('tag2', None)[0] == "value2"

    def test_07(self):
        def say_tags(args):
            args.tags_spec.append("tag2 == 'value3'")
        r = self._tcf_run_cut(args_fn = say_tags)
        self.assert_in_tcf_log(
            "_test_07 @local: skipped: because of tag specification")
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags("skip")
    class _test_08(tcfl.tc.tc_c):
        """
        Request 'skip' tag, the TC is skipped
        """
        def eval(self):
            assert 'skip' in self._tags
            assert self.tag_get('skip', None)[0] == True

    def test_08(self):
        r = self._tcf_run_cut()
        self.assert_in_tcf_log(
            "_test_08 @local: skipped: because of 'skip' tag @")
        self.assert_in_tcf_log("1 skipped")
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)


    @tcfl.tc.tags(skip = "because I want")
    class _test_09(tcfl.tc.tc_c):
        """
        Request 'skip' tag, the TC is skipped
        """
        def eval(self):
            assert 'skip' in self._tags
            assert self.tag_get('skip', None)[0] == True

    def test_09(self):
        r = self._tcf_run_cut()
        self.assert_in_tcf_log(re.compile(
            "_test_09 @local: skipped: "
            "because of 'skip' tag @.*because I want"))
        self.assert_in_tcf_log("1 skipped")
        self.assert_not_in_tcf_log("AssertionError")
        self.assertEqual(r, 0)

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
