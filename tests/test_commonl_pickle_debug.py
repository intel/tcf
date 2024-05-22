#! /usr/bin/python3
#
# Copyright (c) 2024 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import commonl
import tcfl.tc


class _test(tcfl.tc.tc_c):

    @tcfl.tc.subcase()
    def eval_10_dict_pickable_reports_no_pickle_errors(self):
        d = dict(a = 1, b = 2, c = dict(ca = 1, cb = 2))
        paths_failed = commonl.pickle_debug("d", d, None)
        if not paths_failed:
            self.report_pass("pickle_debug reports no failed paths")
        else:
            self.report_pass(
                f"pickle_debug reports failed paths: {paths_failed}")


    @tcfl.tc.subcase()
    def eval_10_dict_unpickable_reports_errors(self):
        # c is not pickable
        d = dict(a = 1, b = 2, c = open(__file__))
        paths_failed = commonl.pickle_debug("d", d, None)
        if not paths_failed:
            raise tcfl.fail_e(
                "pickle_debug does not reports failed path 'c' as expected,"
                f" but {paths_failed}")
        if paths_failed == [ 'd.c' ]:
            self.report_pass(
                f"pickle_debug reports expected failed paths {paths_failed}")
        else:
            raise tcfl.error_e(
                f"pickle_debug reports unkown failed paths: {paths_failed}")
