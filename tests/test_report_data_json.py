#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import json
import os
import pprint
import time

import tcfl.tc

data  = [
    ( "domain1", "name1", 2 ),
    ( "domain1", "name2", { "a": 1, "b": 2 } ),
    ( "domain1", "name3", True ),
    ( "domain1", "name4", "string" ),
    ( "domain2", "name5", 1 ),
    ( "domain3", "name6", False ),
    ( "domain3", "name7", 3.0 ),
]


class _subtest1_base(tcfl.tc.subtc_c):
    def eval(self):
        # the reporting driver report_data_json has generated a json
        # file called report-[RUNID:]HAHSID.data.json with all the
        # data the parent reported, let's open it and verify it
        # contains the @data list in dictionary form
        json_file_name = self.parent.report_file_prefix + "data.json"
        with open(json_file_name) as f:
            j = json.load(f)
        issues = False
        for domain, name, value in data:
            if domain not in j:
                self.report_fail("domain %s missing in the json data" % domain)
                issues = True
                continue
            domain_data = j[domain]
            value_stored = domain_data.get(name, None)
            if value_stored == None:
                self.report_fail(
                    "data %s missing in the json data for domain %s"
                    % (name, domain))
                issues = True
                continue
            if isinstance(value_stored, dict):
                _value_stored = {}
                for key in value_stored.keys():
                    _value_stored[str(key)] = value_stored[key]
                value_stored = _value_stored
            if value_stored != value:
                self.report_fail(
                    "value for data %s in domain %s differs from the expected value"
                    % (name, domain), dict(
                        value_stored = value_stored,
                        value_expected = value
                    ))
                issues = True
                continue
            self.report_pass("%s/%s matches value %s" % (domain, name, value))
        if issues:
            raise tcfl.tc.failed_e("issues found")
        self.report_pass("all values are valid")


class _test(tcfl.tc.tc_c):
    """
    Generates data that shall be dumped to a report file in json
    format; then it schedules a subtest (that the orchestrator
    executes) right after, in which we verify the original test case
    (which becomes the parent)'s data is generated.
    """
    def eval(self):
        self.subtc["sub1"] = _subtest1_base(self.name + ".subtest1",
                                       __file__, self.origin, self)
        for domain, name, value in data:
            self.report_data(domain, name, value)
