#! /usr/bin/env python3
#
# Copyright 2024 Intel Corporation
#
# SPDX-License-Header: Apache 2.0

import commonl
import tcfl.tc

class _test_WEIRDNAME(tcfl.tc.tc_c):
    """
    Test :func:`commonl.config_import_file` can import the symbols
    defined in this python file into the main and __sys__ modules.

    We test by importing this file (the script) as a config file into
    the sys and __main__ modules and looking for the presence of the
    *_test_WEIRDNAME* attribute.
    """
    def eval(self):

        import __main__
        import sys

        for module in [ __main__, sys ]:

            with self.subcase(module.__name__):

                if hasattr(module, "_test_WEIRDNAME"):
                    # this ran before, so let's remove it BECAUSE this
                    # is global in the current old scheduler, running
                    # multiple copies of this testcase will be a race
                    # condition
                    delattr(module, "_test_WEIRDNAME")

                commonl.config_import_file(__file__, module.__name__)
                if not hasattr(module, "_test_WEIRDNAME"):
                    self.report_fail(
                        "commonl.config_import_file() did not"
                        f" import {__file__}'s _test into {module.__name__}",
                        {
                            "namespace's dict keys": list(module.__dict__.keys()),
                        })
                else:
                    self.report_pass(
                        "commonl.config_import_file() "
                        f" imports {__file__}'s _test into {module.__name__}")
