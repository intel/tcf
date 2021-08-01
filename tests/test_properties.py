#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import collections
import json
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
            with self.subcase(name):
                val = target.property_get(name)
                if val != original:
                    self.report_fail("%s mismatch" % name,
                                     dict(original = original, obtained = val))
                else:
                    self.report_pass("%s matches" % name)

        with self.subcase("property_check"):
            _property_check('a', d['a'])
            _property_check('b', d['b'])
            _property_check('c', d['c'])
            # get nested attributes
            _property_check('a.d', d['a']['d'])
            _property_check('a.d.i', d['a']['d']['i'])

        def _unexistant_property_check(prop_name):
            val = target.property_get(prop_name)
            if val != None:
                self.report_fail(
                    f"unexistant property '{prop_name}':"
                    f" expected None; got {val}")
            else:
                self.report_pass(
                    f"unexistant property '{prop_name}': returns None")

        with self.subcase("unexistant_property"):
            for prop_name in [
                    "a.d.this doesnt exist",
                    "this doesnt exist",
                    "this.doesnt.exist" ]:
                with self.subcase(prop_name):
                    _unexistant_property_check(prop_name)


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)


def field_get_verify(r, property_name, do_raise = False):
    # unfold a.b.c.d which returns { a: { b: { c: { d: value } } } }
    propertyl = property_name.split(".")
    acc = []
    for prop_name in propertyl:
        r = r.get(prop_name, None)
        acc.append(prop_name)
        if r == None:
            if do_raise:
                raise tcfl.tc.failed_e(
                    'field %s is non-existing' % ".".join(acc), dict(r))
            val = None
            break
    else:
        val = r
    return val


@tcfl.tc.target(ttbd.url_spec)
class _test_sorted(tcfl.tc.tc_c):
    """The power components listed by the properties need to be sorted
    according to their declaration order in the configuration

    """

    power_rail = [
        "IOC/YK23406-2",
        "ADB/YK23406-3",
        "main/sp7/8",
        "wait /dev/tty-gp-64b-soc",
        "serial0_soc",
        "wait /dev/tty-gp-64b-ioc",
        "serial1_ioc",
    ]

    def eval(self, target):
        r = target.rtb.send_request(
            "GET", "targets/" + target.id,
            data = { "projection": json.dumps(["interfaces.power" ]) },
            raw = True)
        # Even though JSON and python dicts are unordered, the server
        # provides the resposnes in the right order
        rt = json.loads(r.text, object_pairs_hook = collections.OrderedDict)
        power_impls = field_get_verify(rt, "interfaces.power")
        power_impl_list = list(power_impls.keys())
        if power_impl_list != self.power_rail:
            raise tcfl.tc.failed_e("server didn't keep the power-rail order",
                                   dict(
                                       reported_rail = power_impl_list,
                                       sorted_rail = self.power_rail,
                                   ))
        self.report_pass("server kept power-rail order",
                         dict(
                             reported_rail = power_impls.keys(),
                             sorted_rail = self.power_rail,
                         ))

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
