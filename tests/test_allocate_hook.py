#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import time

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Traceback"
    ])

@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _test(tcfl.tc.tc_c):
    """
    The target is configured in the server side to set a property in
    the allocation hook of an interface.

    Verify said property exists during evaluation--which runs with the
    target allocated.

    We verify the property contains the allocation ID as a unique
    identifier to each allocation.
    """
    def eval(self, target):
        iface_name, allocid = target.property_get("test_property").split()
        assert iface_name == "sample"
        assert allocid == self.allocid
        
    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
