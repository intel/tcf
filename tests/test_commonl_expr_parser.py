#! /usr/bin/env python3
#
# Copyright 2024 Intel Corporation
#
# SPDX-License-Header: Apache 2.0
"""
Tests for module :mod:`commonl.expr`
"""

import commonl.expr_parser
import tcfl.tc

class _parser(tcfl.tc.tc_c):
    """
    Tests a bunch of expressions to ensure the parser works ok

    The expression parser is a boolean evaluator, so the result of
    parsing an expression is a boolean. We feed multiple known vectors
    (each a subcase) from the :data:`table`, which uses values from
    :data:`d` and compare with the expected values reported in the table.
    """

    d = {
        # key value list for table below; keep alphabetically sorted
        "bool_false": False,
        "bool_true": True,
        "str_false": "false",
        "str_true": "true",
    }

    table = (
        # expr list using expression dict above; try to keep sorted by
        # logical blocks of whatever meaning is needed and in there,
        # alphabetical

        # booleans
        ( "bool_false", False ),
        ( "bool_false == false", True ),
        ( "bool_false == False", True ),
        ( "bool_false != false", False ),
        ( "bool_false != False", False ),

        ( "bool_true", True ),
        ( "bool_true == true", True ),
        ( "bool_true == True", True ),
        ( "bool_true != true", False ),
        ( "bool_true != True", False ),

        # strings that look like booleans don't eval as booleans, so
        # when comparing them with a boolean they all should fail the
        # comparison

        # a string containng false evaluates as True, since it has content
        ( "str_false", True ),
        ( "str_false != False", True ),
        ( "str_false != false", True ),
        ( "str_false == False", False ),
        ( "str_false == false", False ),
        # but we can compare with the string "false"
        ( "str_false != 'false'", False ),
        ( "str_false != 'true'", True ),
        ( "str_false == 'false'", True ),
        ( "str_false == 'true'", False ),

        # a string containng true evaluates as True, since it has content
        ( "str_true", True ),
        ( "str_true != True", True ),
        ( "str_true != true", True ),
        ( "str_true == True", False ),
        ( "str_true == true", False ),
        # but we can compare with the string "true"
        ( "str_true != 'false'", True ),
        ( "str_true != 'true'", False ),
        ( "str_true == 'false'", False ),
        ( "str_true == 'true'", True ),
    )


    def eval(self):
        for expression, expected in self.table:
            # subcase naming is goig to be hard, since the expression
            # has chars that can't be in names and making it safe
            # would only yield same subcase name for different
            # situations; so let's hash it and let the info printed
            # give more details
            subcase = commonl.mkid(expression)
            evaluation = commonl.expr_parser.parse(expression, self.d)
            if evaluation == expected:
                self.report_pass(f'expression "{expression}" evaluates'
                                 f' to *{expected}* as expected',
                                 subcase = subcase)
            else:
                self.report_fail(f'expression "{expression}" does not'
                                 f' evaluate to *{expected}* as expected',
                                 subcase = subcase, dlevel = -1)
