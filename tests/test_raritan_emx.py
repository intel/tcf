#! /usr/bin/python3
#
# Copyright (c) 2017-24 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import unittest

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(os.path.abspath(__file__))
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

topdir = os.path.dirname(srcdir)

@tcfl.tc.target(ttbd.url_spec + " and t0")
class _test(tcfl.tc.tc_c, unittest.TestCase):


    @tcfl.tc.subcase()
    def eval_00_password_censored_if_plain(self, target):
        instrument = target.kws['interfaces.power.AC1.instrument']
        password = target.kws.get(f'instrumentation.{instrument}.password', None)
        assert password == "<plain-text-password-censored>", \
            f"password: expected '<plain-text-password-censored>'; got '{password}'"


    @tcfl.tc.subcase()
    def eval_01_password_not_censored_if_expandable(self, target):
        instrument = target.kws['interfaces.power.AC2.instrument']
        password = target.kws.get(f'instrumentation.{instrument}.password', None)
        expected_filename = "FILE:" + os.path.realpath(f"{topdir}/tests/samplepasswordfile")
        assert password == expected_filename, \
            f"password: expected '{expected_filename}'; got '{password}'"


    @tcfl.tc.subcase()
    def eval_02_no_password_in_published_url(self, target):
        instrument = target.kws['interfaces.power.AC1.instrument']
        url_published = target.kws.get(f'instrumentation.{instrument}.url', None)
        assert "plaintextpassword" not in url_published, \
            f"plain text password exposed in UPID URL: {url_published}"


    @tcfl.tc.subcase()
    def eval_121_power_list_fails_with_the_expected_url(self, target):
        with self.assertRaisesRegex(
                tcfl.error_e, "hostname.domain.*Name or service not known"):
            target.power.list()


    @tcfl.tc.subcase()
    def eval_122_power_on_fails_with_the_expected_url(self, target):
        with self.assertRaisesRegex(
                tcfl.error_e, "hostname.domain.*Name or service not known"):
            target.power.on("AC2")


    @tcfl.tc.subcase()
    def eval_122_power_off_fails_with_the_expected_url(self, target):
        with self.assertRaisesRegex(
                tcfl.error_e, "hostname.domain.*Name or service not known"):
            target.power.off("AC2")


    @tcfl.tc.subcase()
    def eval_141_power_on_fails_with_the_expected_updated_url(self, target):
        with self.assertRaisesRegex(
                tcfl.error_e, r"hostname2\.domain2.*Name or service not known"):
            instrument = target.kws['interfaces.power.AC2.instrument']
            target.property_set(f"instrumentation.{instrument}.url", "user@hostname2.domain2:40")
            target.power.on("AC2")

    @tcfl.tc.subcase()
    def eval_142_power_off_fails_with_the_expected_updated_url(self, target):
        with self.assertRaisesRegex(
                tcfl.error_e, r"hostname2\.domain2.*Name or service not known"):
            instrument = target.kws['interfaces.power.AC2.instrument']
            target.property_set(f"instrumentation.{instrument}.url", "user@hostname2.domain2:40")
            target.power.off("AC2")


    # there is pretty much no easy way to test capture
    @tcfl.tc.subcase()
    def eval_16_capture_start(self, target):
        with self.assertRaisesRegex(
                tcfl.error_e, r"hostname2\.domain2.*Name or service not known"):
            target.capture.start("AC2")
            target.capture.stop("AC2")
            target.capture.get("AC2")


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
