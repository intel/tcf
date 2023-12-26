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
    ]
)


@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _test(tcfl.tc.tc_c):
    """
    We have an allocation for t0, we insert another two in the queue
    and keepalive only the last.

    Release the target and we leave the first allocation to ellapse,
    thus the new allocation shall kick in and t0 shall be assigned to
    it.

    """
    def eval(self, target):

        # we'll let this allocid timeout
        allocid, state, _ = tcfl.target_ext_alloc._alloc_targets(
            target.server, { "group": [ "t0" ] },
            queue = True, wait_in_queue = False)
        # the target at the end will shall be reserved to this
        final_allocid, state, _ = tcfl.target_ext_alloc._alloc_targets(
            target.server, { "group": [ "t0" ] },
            queue = True, wait_in_queue = False)
        assert state == "queued", \
            "second allocation got state '%s', expected 'queued'" % state

        target.property_set("release_hook_called", None)
        # is release_hook_called None? let's verify initial conditions
        # are ok
        release_hook_called = target.property_get("release_hook_called")
        assert release_hook_called == None, \
            "release_hook_called is not *None*; got '%s'" % release_hook_called
        self.report_info(
            f"releasing target so it goes to {allocid} and"
            f" then to {final_allocid}")
        target.release()

        timeout = 20
        self.report_info("waiting %.fs for allocation ID %s to timeout"
                         % (timeout, allocid))
        for _count in range(20):
            # note tcf/run might be keepaliving the testcases's allocid
            # just in case we do it too and we let the new allocid to
            # expire by not keepaliving it
            r = target.server.send_request(
                "PUT", "keepalive",
                json = {
                    self.allocid: None,
                    final_allocid: None,
                } )
            time.sleep(1)

        # verify the current testcase's allocid is dead and the new
        # one is alive
        r = target.server.send_request("PUT", "keepalive", json = {
            self.allocid: None, allocid: None } )

        state = r[allocid]['state']
        assert state == 'invalid', \
            "%s: after %.fs, expected state 'invalid'; got '%s'" % (
                self.allocid, timeout, state)
        self.report_pass(f"after waiting %.fs, %s's state is '%s' as expected" % (
            timeout, allocid, state))

        state = r[self.allocid]['state']
        assert state == 'active', \
            "%s: after %.fs, expected state 'active'; got '%s'" % (
                self.allocid, timeout, state)
        self.report_pass(f"after waiting %.fs, %s's state is '%s' as expected" % (
            timeout, self.allocid, state))

        new_allocid = target.property_get("_alloc.id")
        assert final_allocid == new_allocid, \
            f"target is allocated to {new_allocid}; expected {final_allocid}"
        target.report_pass(
            f"after timing out, target is allocated to {final_allocid}")

        # was the release hook called? let's check
        release_hook_called = target.property_get("release_hook_called")
        assert release_hook_called == True, \
            "seems the release hook was not called, since the field " \
            "release_hook_called is not True; got '%s'" % release_hook_called
        self.report_pass(
            "release hook was called when %s moved from %s to %s" % (
                target.id, self.allocid, new_allocid))

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
