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
        "Traceback",
        "DEBUG[",
        # this is not our fault, is a warning on the core
        "FIXME: delete the allocation",
        # FIXME: this is a hack because we are wiping the allocation
        # tcf/run does and the it complains it can't wipe it; the
        # orchestra shall be fine with this, so we ignore it for the
        # time being.
        "allocation/delete:EXIT:EXCEPTION",
    ])


@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _test(tcfl.tc.tc_c):
    """An static allocation doesn't timeout until removed

    The target will be allocated by TCF/run, which might be
    keepaliving it. So we are going to queue an static allocation for
    our test; we'll releae it so the static allocation takes hold
    and test that one then

    """
    def eval(self, target):

        allocid, state, _ = tcfl.target_ext_alloc._alloc_targets(
            target.server, { "group": [ "t0" ] },
            queue = True, wait_in_queue = False, endtime = "static")
        assert state == "queued", \
            f"second allocation got state '{state}', expected 'queued'"

        target.release()

        time.sleep(20)

        # verify target is now on the new allocation
        new_allocid = target.property_get("_alloc.id")
        assert allocid == new_allocid, \
            "target is allocated to %s; expected %s" % (new_allocid, allocid)
        target.report_pass("after releasing, target is allocated to %s"
                           % allocid)

        target.property_set("release_hook_called", None)
        wait_time = 10
        # conf has set the max idle to 2; we'll wait enough time for
        # maintenance to have been called a few times and verify
        # the target is not relesed and it's allocid is still the same
        self.report_info(f"waiting {wait_time} to verify allocation"
                         f" ID {self.allocid} does not timeout")
        time.sleep(wait_time)	# note we do not keepalive

        # was the release hook called? it should not
        release_hook_called = target.property_get("release_hook_called", None)
        assert release_hook_called == None, \
            "seems the target was released, since the field " \
            f"release_hook_called is not None; got '{release_hook_called}'"
        self.report_pass("target was not released as expected")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
