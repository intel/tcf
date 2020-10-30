#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import socket

import commonl.testing
import tcfl
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])


@tcfl.tc.target(ttbd.url_spec)
class release_hooks(tcfl.tc.tc_c):
    """
    We allocate a target, create tunnels and then we release it; when
    released, the tunnels are destroyed.
    """

    def eval(self, target):
        target.tunnel.add(22, "127.0.0.1", 'tcp')
        self.report_pass("release hooks were called on target release")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
