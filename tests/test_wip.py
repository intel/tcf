#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import sys
import unittest

import commonl.testing
import tcfl
import tcfl.tl


_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

#@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
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

    # FIXME: interconnects spec's not working?
    #
    # FIXME: app_zephyr can read testcase.ini to merge in values,
    #        discarding build_only.
    #
    # FIXME: when -i RUNID is specified, it is not passed in the
    #       tickets, so the server doesn't show the runid
    #
    # FIXME: ic, targets, test different one-type|any|all modes
    #
    #        - ic testcase to verify in limited mode multiple types of
    #          the same IC are ignored for candidate picks
    #
    #        - ic testcase that fails if an IC is requested but none is found
    #          (now it is ksipped with no message)
    #
    #        - for tcob, we want to run on all mv, ma, a101 but we don't
    #          care about combos on A2, so to generate TGs, we want to
    #          tell it to go single-target-style on the DUT, but not on
    #          the TCOB
    #
    #          In a way it'd be telling that for targets with some mark
    #          we want to cover as much variety as possible and that
    #          would override the limits. By default, if only one
    #          target, the target has a that setting.
    #
    # FIXME: document TCOB properly
    #
    # FIXME: interconnect stuff
    #
    #class ip_interconnect_c(interconnect_c):
    #    def __init__(self, FIXME):
    #        interconnect_c.__init__(self)
    #
    #ttbl.config.interconnect_add(
    #    "ipv4-1",
    #    ttbl.ip.ip_interconnect_c(CONNECTIONS_FIXME))
    #
    # FIXME: *_for_a_target() is set as *_50_for_a_target(), so it
    #        easy to build prefix/postfix, documented.
    #
    # FIXME: move pass_e and friends to __init__.py so expecter doesn't
    #        have to include tc
    #        move tcfl.tc.*_e,tcfl.tc.{tags,target} to tcfl? to simplify
    #        the imports and naming?
    #
    # FIXME: do not set the testcase name for each test method
    #
    # FIXME: deploy-collecting messages have less depth than deploying messages
    #
    # FIXME: testing library captures python log to a file, not to stdout
    #
    # FIXME: app builders
    #
    #        - Figure out how to override?
    #
    # FIXME: hack no arguments to @tcfl.tc.target so no () are needed
    #        http://stackoverflow.com/a/3932122
    #
    # FIXME: need console_setup(9600) for QA
    #
    # FIXME: rename targets_all -> rt_all, targets_selected -> rt_selected
    #
    # FIXME: fix logging of static AND tc_c.report(), needs to print
    #        target/tggroup
    @tcfl.tc.interconnect("id == 'nwa'")
    class _test_00(tcfl.tc.tc_c):
        @staticmethod
        def eval(ic):
            assert ic.id == 'nwa'

    def test_00(self):
        r = self._tcf_run_cut()
        self.assert_not_in_tcf_log("AssertionError")
        self.assert_in_tcf_log("1 passed")
        self.assertEqual(r, 0)



if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
