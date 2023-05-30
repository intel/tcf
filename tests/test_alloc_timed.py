#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import datetime
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
        "Traceback",
        "DEBUG[",
        # this is not our fault, is a warning on the core
        "FIXME: delete the allocation",
        # FIXME: this is a hack because we are wiping the allocation
        # tcf/run does and the it complains it can't wipe it; the
        # orchestra shall be fine with this, so we ignore it for the
        # time being.
        "allocation/delete:EXIT:EXCEPTION",
    ]
)


@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _test(tcfl.tc.tc_c):
    """A timed allocation times out at a given time

    We have an allocation for t0 by tcf/run. We insert another one in
    the queue that timesout 1min after now. Then we just wait and
    check the new allocation timesout.

    We don't even need to have the target allocated, we just verify
    the alloc expires.

    """
    def eval(self, target):

        # minimum expiration is 1 min ahead
        wait_min = 2
        datetime_now = datetime.datetime.utcnow()
        datetime_end = datetime_now + datetime.timedelta(seconds = 1.5 * 60)

        allocid, state, _ = tcfl.target_ext_alloc._alloc_targets(
            target.rtb, { "group": [ "t0" ] },
            queue = True, wait_in_queue = False,
            endtime = datetime_end.strftime("%Y%m%d%H%M%S"))
        assert state == "queued", \
            f"second allocation got state '{state}', expected 'queued'"

        self.report_info(f"waiting for {wait_min}m for allocation to expire")
        time.sleep(wait_min * 60)
        # verify the current testcase's allocid is dead and the new
        # one is alive
        r = target.rtb.send_request("PUT", "keepalive",
                                    json = { allocid: None } )

        # at this point, the allocaton must have been expired
        state = r.get(allocid, { "state": "allocid missing" })['state']
        assert state == 'invalid', \
            f"allocation {allocid}: after {wait_min}m," \
            f" expected state 'invalid'; got '{state}'"
        self.report_pass(f"new allocation expired as expected")


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
