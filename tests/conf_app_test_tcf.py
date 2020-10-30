#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import tcfl.tc
import tcfl.app

class app_test(tcfl.app.app_c):
    """
    """

    @staticmethod
    def _storage_ensure(target):
        try:
            getattr(target, "app_test")
        except AttributeError:
            setattr(target, "app_test", {})

    @staticmethod
    def build(testcase, target, app_src):
        app_test._storage_ensure(target)
        target.report_info("app_test.build")
        target.app_test['build'] = True

    @staticmethod
    def start(testcase, target, app_src):
        app_test._storage_ensure(target)
        target.report_info("app_test.start")
        target.app_test['start'] = True

    @staticmethod
    def teardown(testcase, target, app_src):
        app_test._storage_ensure(target)
        target.report_info("app_test.teardown")
        target.app_test['teardown'] = True

    @staticmethod
    def clean(testcase, target, app_src):
        app_test._storage_ensure(target)
        target.report_info("app_test.clean")
        target.app_test['clean'] = True
