#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

import commonl.testing
import tcfl
import tcfl.tc
import tcfl.target_ext_alloc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])


@tcfl.tc.target(ttbd.url_spec + ' and local_test')
class _test(commonl.testing.shell_client_base):
    """
    Test allocations longer then the limit set by the server get chopped
    """

    def eval_00(self, target):

        self.ttbd = ttbd
        self.mk_tcf_config()

        shorter_than_32 = "shorter than 32"
        longer_than_32 = "longer than 32 longer than 32 longer than 32"

        # allocate with a short reason
        # all these allocations will be queued, as we have the target
        # allocated; it is ok, we just want to read the reason
        allocid, _state, _group = tcfl.target_ext_alloc._alloc_targets(
            target.rtb,
            { 'group': [ target.id ] }, queue_timeout = 0,
            reason = shorter_than_32)

        # get the short reason
        r = target.rtb.send_request("GET", "allocation/%s" % allocid)
        assert r['reason'] == shorter_than_32, \
            "reason returned is not the one sent; got '%s', expected '%s'" \
            % (r['reason'], shorter_than_32)
        self.report_pass("allocid %s: reason is '%s'" % (allocid, r['reason']))

        # allocate with a long reason
        allocid, _state, _group = tcfl.target_ext_alloc._alloc_targets(
            target.rtb,
            { 'group': [ target.id ] }, queue_timeout = 0,
            reason = longer_than_32)

        # get the short reason
        r = target.rtb.send_request("GET", "allocation/%s" % allocid)
        assert r['reason'] == longer_than_32[:32], \
            "reason returned is not the one sent capped to 32;" \
            " got '%s', expected '%s'" \
            % (r['reason'], longer_than_32[:32])
        self.report_pass("allocid %s: reason is shortened '%s'"
                         % (allocid, r['reason']))
