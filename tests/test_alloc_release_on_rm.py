#! /usr/bin/python2
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


@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _test(tcfl.tc.tc_c):

    def eval(self, target):

        # we have an allocation -- remove it, and that should force
        # the release hooks to be executed
        #
        # on the configuration we have created on conf_THISFILE.py,
        # there is a single target that, upon being setup, cleans
        # property release_hook_called. When the release hook is
        # called, it sets that property to True.
        #
        # So we remove it and the property shall be True

        self.report_info("removing allocation ID %s" % self.allocid)
        tcfl.target_ext_alloc._delete(target.rtb, self.allocid)
        release_hook_called = target.property_get("release_hook_called")
        assert release_hook_called == True, \
            "seems the release hook was not called, since the field " \
            "release_hook_called is not True; got '%s'" % release_hook_called
        target.report_pass("release hook was called when"
                           " allocation ID %s was removed" % self.allocid)

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
