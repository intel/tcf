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

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target(ttbd.url_spec)
class _test(tcfl.tc.tc_c):

    def eval(self, target):
        n = dict(
            T = True,
            F = False,
            i = 3,
            f = 3.0,
            s = "string",
        )
        n_nested = dict(n)
        n_nested['d'] = n
        d = dict(
            a = n_nested,
            b = n_nested,
            c = n_nested,
        )
        target.properties_set(d)

        def _property_check(name, original):
            val = target.property_get(name)
            if val != original:
                raise tcfl.tc.failed_e(
                    "%s mismatch" % name,
                    dict(original = original, obtained = val))
            self.report_pass("%s matches" % name)

        _property_check('a', d['a'])
        _property_check('b', d['b'])
        _property_check('c', d['c'])
        # get nested attributes
        _property_check('a.d', d['a']['d'])
        _property_check('a.d.i', d['a']['d']['i'])

        prop = "a.d.this doesnt exist"
        val = target.property_get(prop)
        if val != None:
            raise tcfl.tc.failed_e(
                "unexistant property '%s' returns value: %s" % (prop, val))
        self.report_pass("unexistant property '%s' returns None" % prop)

        prop = "this doesnt exist"
        val = target.property_get(prop)
        if val != None:
            raise tcfl.tc.failed_e(
                "unexistant property '%s' returns value: %s" % (prop, val))
        self.report_pass("unexistant property '%s' returns None" % prop)

        prop = "this.doesnt.exist"
        val = target.property_get(prop)
        if val != None:
            raise tcfl.tc.failed_e(
                "unexistant property '%s' returns value: %s" % (prop, val))
        self.report_pass("unexistant property '%s' returns None" % prop)

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
