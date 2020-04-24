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
ttbd = commonl.testing.test_ttbd()

class _test(commonl.testing.shell_client_base):
    """
    """

    def eval_00(self):
        self.ttbd = ttbd
        self.report_info("server URL %s" % ttbd.url)

        CURRENT_API_VERSION = tcfl.ttb_client.rest_target_broker.API_VERSION

        self.run_local(
            "curl -sk -X PUT %s/ttb-v%s/login -d password=none -d username=local"
            % (ttbd.url, CURRENT_API_VERSION),
            "user local: not allowed")
        self.report_pass(
            "accessing login via v%s yields expected message for current version"
            % CURRENT_API_VERSION)

        for old_version in range(0, CURRENT_API_VERSION):
            self.run_local(
                "curl -sk -X PUT %s/ttb-v%s/login -d password=none -d username=local"
                % (ttbd.url, old_version),
                "please upgrade")
            self.report_pass(
                "accessing login via old version v%s gives expected error message"
                % old_version)

        for new_version in range(CURRENT_API_VERSION + 1, CURRENT_API_VERSION + 10):
            self.run_local(
                "curl -sk -X PUT %s/ttb-v%s/login -d password=none -d username=local"
                % (ttbd.url, new_version),
                "please downgrade")
            self.report_pass(
                "accessing login via newer version v%s gives expected error message"
                % new_version)
