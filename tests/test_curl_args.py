#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
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
ttbd.bad_strings.append("user local: not allowed")

class _test(commonl.testing.shell_client_base):
    """
    """

    def eval_00(self):
        self.ttbd = ttbd
        self.report_info("server URL %s" % ttbd.url)

        CURRENT_API_VERSION = tcfl.ttb_client.rest_target_broker.API_VERSION

        # Login with bare parameters
        self.run_local(
            "curl -sk -X PUT %s/ttb-v%s/login -d password=apassword -d username=local"
            % (ttbd.url, CURRENT_API_VERSION),
            "user local: authenticated")
        self.report_pass("can login with non-JSON encoding")

        # Login with JSON parameters
        self.run_local(
            'curl -sk -X PUT %s/ttb-v%s/login -d password="apassword" -d username="local"'
            % (ttbd.url, CURRENT_API_VERSION),
            "user local: authenticated")
        self.report_pass("can login with JSON encoding")
