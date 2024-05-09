#! /usr/bin/env python3
#
# Copyright 2024 Intel Corporation
#
# SPDX-License-Header: Apache 2.0
"""
Test the commonl.dict_to_flat function

Since there are many permutations and cases we want to verify
work, we create a framework into which we can feed test
vectors.

Each vector basically is a:

- scenario name (a subcase)
- an input dictionary
- a list of arguments for dict_to_flat() and expected outputs

then for each, the framework just checks expanding the subcases.

"""

import commonl
import tcfl.tc


testvectors = {
    # keyed by scenario name, each scenario
    # { SCENARIONAME: ( INPUTDICT, [ ( KWARGS, EXPECTEDDICT ), ... ] )
    #
    # Each scenario name takes na input dictionary; that can be
    # converted with different kwargs and it shall yield the expected
    # dictionary, which is keyed by flat field name nad the expected
    # value
    "scenario_1": (
        {
            "1": "1",
            "2" : {
                "2a": "2a",
                "2b": {
                    "2b1": "2b1",
                },
            },
            "3": {
            },
        },
        [
            (
                # these are the optional kwargs to dict_to_flat()
                dict(projections = None, sort = True,
                     empty_dict = False, add_dict = False),
                {
                    "1": "1",
                    "2.2a": "2a",
                    "2.2b.2b1": "2b1",
                }
            ),
            (
                dict(projections = None, sort = True,
                     empty_dict = False, add_dict = True),
                {
                    "1": "1",
                    "2.2a": "2a",
                    "2.2b": { "2b1": "2b1" },
                    "2.2b.2b1": "2b1",
                }
            ),
            (
                dict(projections = None, sort = True,
                     empty_dict = True, add_dict = True),
                {
                    "1": "1",
                    "2.2a": "2a",
                    "2.2b": { "2b1": "2b1" },
                    "2.2b.2b1": "2b1",
                    "3": {},
                }
            ),
            (
                dict(projections = [ "2.2a" ], sort = True,
                     empty_dict = True, add_dict = True),
                {
                    "2.2a": "2a",
                }
            ),
            (
                dict(projections = [ "2.2b*" ], sort = True,
                     empty_dict = True, add_dict = True),
                {
                    "2.2b": { "2b1": "2b1" },
                    "2.2b.2b1": "2b1",
                }
            ),
            (
                dict(projections = [ "2.2b.*" ], sort = True,
                     empty_dict = True, add_dict = True),
                {
                    "2.2b.2b1": "2b1",
                }
            ),
        ],
    ),

    "scenario_2": (
        {
            'interconnects': {},
            'id': 't0',
            'type': 'test_target',
            'interfaces': {
                'power': {
                    'power0': {
                        'instrument': 'lloh'
                    },
                },
                'tunnel': {},
                'store': {},
                'certs': {},
            },
            'dict': {
                '1': '1',
                '2': {
                    '2a': '2a',
                    '2b': { '2b1': '2b1' }
                },
                '3': {}
            },
            'path': '/state/targets/t0'
        },
        [
            (
                # this is as in ttbl.test_target.to_dict(), call to l1
                dict(projections = [ 'dict.2.2a*' ],
                     empty_dict = True),
                {
                    "dict.2.2a": "2a"
                },
            )
        ]
    ),
}



def _eval_vector(self, kwargs, d, expected):
    # self -> testcase
    flatd = commonl.dict_to_flat(d, **kwargs)
    # flatd is a [ ( k, v ), ... ]
    flat_fields = [ i[0] for i in flatd ]
    flat_fields_expected = list(expected.keys())

    self.report_info(f"flat fields: {' '.join(flat_fields)}")
    self.report_info(f"flat fields expected: {' '.join(flat_fields_expected)}")

    success = True
    for k, v in flatd:			# look for unexpected fields
        if k not in flat_fields_expected:
            self.report_fail(
                f"found unexpected field {k}",
                { "d": d, "flatd": flatd },
                subcase = f"unexpected_key_{k}")
            success = True
    if success:
        self.report_pass(
            "no unexpected fields found",
            { "d": d, "flatd": flatd }, subcase = "unexpected_key")

    success = True
    for k in flat_fields_expected: 		# look for expected fields
        if k not in flat_fields:
            self.report_fail(
                f"can't find expected field {k}",
                { "d": d, "flatd": flatd },
                subcase = f"expected_key_{k}")
            success = False
    if success:
        self.report_pass(
            "all expected fields found",
            { "d": d, "flatd": flatd }, subcase = "expected_key")


    success = True
    for k, v in flatd:			# check expected values
        if k not in flat_fields_expected:
            # we don't expect this key, failed already in the
            # unexpected_key check, so don't verify it
            continue
        v_expected = expected[k]
        if v != v_expected:
            self.report_fail(
                f"flat {k} has value {type(v)} '{v}',"
                f" expected {type(v_expected)} '{v_expected}'",
                { "d": d, "flatd": flatd, "expected": expected },
                subcase = f"expected_value_{k}")
            success = True
    if success:
        self.report_pass(
            "all values match expectations",
            { "d": d, "flatd": flatd, "expected": expected },
            subcase = "expected_value")



def run(self):
    # self -> testcase
    # iterate over all the scenarios and their kwargs combos
    for name, ( d, kwargs_expected ) in testvectors.items():
        for kwargs, expected in kwargs_expected:
            variation_id_l = []

            # FIXME: verify args in are in the dict_to_flat argspec
            for k, v in kwargs.items():
                if k == "projections" and v:
                    commonl.assert_list_of_strings(v, "projections", "projection")
                    # convert the list of fields into a string
                    variation_id_l.append(commonl.name_make_safe("_".join(v)))
                elif k == "sort" and v:
                    variation_id_l.append("sort")
                elif k == "empty_dict" and v:
                    variation_id_l.append("empty_dict")
                elif k == "add_dict" and v:
                    variation_id_l.append("add_dict")

            with self.subcase(name + "___" + "__".join(variation_id_l)):
                try:
                    _eval_vector(self, kwargs, d, expected)
                except Exception as e:
                    self.report_blck(f"exception: {e}")





class _test(tcfl.tc.tc_c):
    __doc__		# not sure this really works
    def eval(self):
        run(self)



if __name__ == "__main__":
    tcfl.tc.report_driver_c.add(
        tcfl.tc.report_console.driver(2),
        name = "console")
    run(tcfl.tc.tc_c(__file__, __file__, __file__))
