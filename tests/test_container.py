#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os

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
    Basic power on/get/off container, exercising the driver
    """
    def eval(self, target):

        with self.subcase("on"):
            target.power.on()

        with self.subcase("get"):
            state, _substate, components = target.power.list()
            assert state == True
            assert components['c0']['state'] == True
            assert components['c1']['state'] == True

        with self.subcase("off"):
            target.power.off()

        for component in [ "c0", "c1" ]:
            with self.subcase(component):
                with self.subcase("on"):
                    target.power.on(component)

                with self.subcase("get"):
                    _state, _substate, components = target.power.list()
                    assert components[component]['state'] == True

                with self.subcase("off"):
                    target.power.off(component)

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
