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
    """Test projection getting works

    Started because "tcf get SUTNAME -p instrumentation" was reporting
    everything and no instrumentation

    Going inside the server, ttbl.test_target.to_dict() is getting an
    empty list from commonl.dict_to_flat(). -- seems this is because
    the projections is filtering everything out

    well, a simple projections test seems to pass, core seems to
    filter properly, a debug in the return from ttbd reports the right fields
    so the problem is past tcfl.server_c.targets_get()

    so _rt_handle() is messing it up? definitely not loading'em

    """
    def eval(self, target):

        # FIXME: this is mostly tags
        # FIXME: add fsdb properties

        projections = [ "dict.1", "dict.2.2a*", "dict.2.2b.*" ]
        server = tcfl.server_c.servers[target.rt['server']]
        rts, rts_flat, _inventory_keys = \
            server.targets_get(target_id = target.id, projections = projections)
        assert target.rt['fullid_always'] in rts.keys()
        rt = rts[target.rt['fullid_always']]
        rt_flat = rts_flat[target.rt['fullid_always']]
        target.report_info("rt returns",
                           { "rt": rt, "rt_flat": rt_flat },
                           alevel = 0)
        # we know the following keys have to be here key 2.2a has to
        # be there because we asked for it
        for key in [ "dict.1", "dict.2.2a", "dict.2.2b.2b1" ]:
            if key not in rt_flat:
                target.report_fail(f"expected key {key} missing",
                                   { "rts": rts, "rts_flat": rts_flat },
                                   subcase = "expected_keys_present")


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
