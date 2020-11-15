#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import pprint

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
    Test that explicity vs normal power components follow the rules
    when executing power on/off sequences.
    """
    def eval(self, target):
        # power ALL off
        target.power.off(explicit = True)
        r = target.power.list()
        state, substate, components = r
        assert state == False and substate == 'full' \
            and all(c['state'] == False for c in components.values()), \
            "after explicit off, power state is not all off: %s" % (r, )
        self.report_pass(
            "after explicit off, we got full off",
            dict(state = state, substate = substate, components = components),
            alevel = 1)

        # power to full on
        target.power.on(explicit = True)
        r = target.power.list()
        state, substate, components = r
        assert state == True and substate == 'full' \
            and all(c['state'] == True for c in components.values()), \
            "after explicit on, power state is not all on: %s" % (r, )
        self.report_pass(
            "after explicit on, we got full on",
            dict(state = state, substate = substate, components = components),
            alevel = 1)
        
        # power off, leaving explicits/off on
        target.power.off()
        r = target.power.list()
        state, substate, components = r
        assert state == False and substate == 'normal', \
            "after power off, power state is not normal off: %s" % (r, )
        for c, d in components.items():
            explicit = d.get('explicit', None)
            if explicit == 'both':
                assert d['state'] == True, \
                    "after powering off from full on," \
                    " explicit/both %s's power is not off: %s" \
                    % (c, r, )
            elif explicit == 'off':
                assert d['state'] == True, \
                    "after powering off from full on," \
                    " explicit/off %s's is not on: %s" \
                    % (c, r, )
            elif explicit == 'on':
                assert d['state'] == False, \
                    "after powering off from full on," \
                    " explicit/on %s's is not off: %s" \
                    % (c, r, )
            else:
                assert d['state'] == False, \
                    "after powering off from full on," \
                    " %s is not off: %s" \
                    % (c, r, )
        self.report_pass(
            "after normal off, powered non-explicits off",
            dict(state = state, substate = substate, components = components),
            alevel = 1)

        target.power.off(explicit = True)
        self.report_pass("full power off")

        # normal power on
        target.power.on()
        r = target.power.list()
        state, substate, components = r
        assert state == True and substate == 'normal', (
            "after power on, power state is not normal on",
            dict(state = state, substate = substate, components = components))
        self.report_pass(
            "after normal on, powered non-explicits on",
            dict(state = state, substate = substate, components = components),
            alevel = 1)

        # normal power off after normal power on leaves explicit/off on
        target.power.on()
        r = target.power.list()
        state, substate, components = r
        assert state == True and substate == 'normal', (
            "after power on, power state is not normal on",
            dict(state = state, substate = substate, components = components))
        self.report_pass(
            "after normal on, powered non-explicits on",
            dict(state = state, substate = substate, components = components),
            alevel = 1)

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
