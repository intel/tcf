#! /usr/bin/python2
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
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])


@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _test(tcfl.tc.tc_c):
    """
    We have an allocation for t0, we insert another one in the queue
    and keepalive it. At we leave the first allocation ellapse, thus
    the new allocation shall kick in and t0 shall be assigned to it.
    """
    def eval(self, target):

        allocid, state, _ = tcfl.target_ext_alloc._alloc_targets(
            target.rtb, { "group": [ "t0" ] },
            queue = True, wait_in_queue = False)
        assert state == "queued", \
            "second allocation got state '%s', expected 'queued'" % state

        # is release_hook_called None? let's verify initial conditions
        # are ok
        release_hook_called = target.property_get("release_hook_called")
        assert release_hook_called == None, \
            "release_hook_called is not *None*; got '%s'" % release_hook_called

        timeout = 20
        self.report_info("waiting %.fs for allocation ID %s to timeout"
                         % (timeout, self.allocid))
        for _count in range(20):
            # note we keepalive the new allocid but let thet estcase's
            # (self.allocid) expire by not keepaliving it
            r = target.rtb.send_request("PUT", "keepalive",
                                        json = { allocid: None } )
            time.sleep(1)

        # verify the current testcase's allocid is dead and the new
        # one is alive
        r = target.rtb.send_request("PUT", "keepalive", json = {
            self.allocid: None, allocid: None } )

        state = r[self.allocid]['state']
        assert state == 'invalid', \
            "%s: after %.fs, expected state 'invalid'; got '%s'" % (
                self.allocid, timeout, state)
        self.report_pass("after waiting %.fs, %s's state is '%s'" % (
            timeout, self.allocid, state))

        state = r[allocid]['state']
        assert state == 'active', \
            "%s: after %.fs, expected state 'active'; got '%s'" % (
                self.allocid, timeout, state)
        self.report_pass("after waiting %.fs, %s's state is '%s'" % (
            timeout, allocid, state))

        new_allocid = target.property_get("_alloc.id")
        assert allocid == new_allocid, \
            "target is allocated to %s; expected %s" % (new_allocid, allocid)
        target.report_pass("after timing out, target is allocated to %s"
                           % allocid)

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
