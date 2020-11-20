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
    @staticmethod
    def eval_00(target):
        # power it all, flashing image0 shall power it off, then power
        # on power3en, then flash, then power on power1
        target.power.on(explicit = True)
        target.images.flash({ "image0": __file__ })
        state, substate, components = target.power.list()
        # we are off, because power0 shall be off
        assert state == False, ( state, substate, components )
        # partial because power0 is off, power1 is on
        assert substate == 'partial', ( state, substate, components )
        assert components['power1']['state'] == True, ( state, substate, components )
        assert components['power3en']['state'] == True, ( state, substate, components )

    @staticmethod
    def eval_00(target):
        # power it all off, flash in parallel
        # on power3en, then flash, then power on power1
        target.power.on(explicit = True)
        ts0 = time.time()
        target.images.flash({ "image_p0": __file__, "image_p1": __file__  })
        ts = time.time()

        # shall take around 6 seconds, all in parallel
        assert abs(ts - ts0 - 6) < 2, \
            "image_p0/1 flashing shall have taken 6 seconds in parallel" \
            " but took %.fs" % (ts - ts0)
        state, substate, components = target.power.list()
        # we are off, because power0 shall be off
        assert state == True, ( state, substate, components )
        # partial because power0 is off, power1 is on
        assert substate == 'normal', ( state, substate, components )
        assert components['power2eb']['state'] == False, ( state, substate, components )
        assert components['power3en']['state'] == False, ( state, substate, components )
        # this is explicit off, so we turned it on on on/all
        assert components['power4ef']['state'] == True, ( state, substate, components )

        # power it all, flashing image0 shall power it off, then power
        # on power3en, then flash, then power on power1


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
