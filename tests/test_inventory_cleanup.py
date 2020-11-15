#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os

import json
import pprint
import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target(ttbd.url_spec + " and t0")
class _test(tcfl.tc.tc_c):
    """
    Verify that when we have leftover inventory data for drivers, it
    is cleaned up upon server startup.

    The configuration file will insert data in the target and then add
    a driver; verify that the data matches what the driver should have.
    """
    def eval(self, target):
        fields_removed = [
            "instrumentation.1234.name",
            "instrumentation.1234.name_long",
            "interfaces.madeup.instance.instrument"
        ]
        fields_present = [
            "instrumentation.2343.name",
            "instrumentation.2343.name_long",
            "instrumentation.2343.manual",
        ]

        for field in fields_removed:
            value = target.property_get(field, None)
            if value != None:
                raise tcfl.tc.failed_e(
                    "field %s is present and should have been removed" % field,
                    dict(fields = target.kws))
        self.report_pass("spurious fields have been removed")

        for field in fields_present:
            value = target.property_get(field, None)
            if value == None:
                raise tcfl.tc.failed_e(
                    "expected field %s is not present" % field,
                    dict(fields = target.kws))
        self.report_pass("manual fields exist")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
