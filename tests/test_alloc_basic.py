#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

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


class _test(commonl.testing.shell_client_base):
    """
    """

    def eval_00(self):
        self.ttbd = ttbd
        self.mk_tcf_config()

        self.run_local("SERVER=%s %s/../ttbd/allocation-raw-test.sh" %
                       (ttbd.url, os.path.abspath(srcdir)))
