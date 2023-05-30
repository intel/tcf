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
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Traceback",
        "DEBUG[",
        # this is not our fault, is a warning on the core
        "FIXME: delete the allocation",
        # FIXME: this is a hack because we are wiping the allocation
        # tcf/run does and the it complains it can't wipe it; the
        # orchestra shall be fine with this, so we ignore it for the
        # time being.
        "allocation/delete:EXIT:EXCEPTION",
    ]
)


class _test(commonl.testing.shell_client_base):
    """
    """

    def eval_00(self):
        self.ttbd = ttbd
        self.mk_tcf_config()

        self.run_local("SERVER=%s %s/../ttbd/allocation-raw-test.sh" %
                       (ttbd.url, os.path.abspath(srcdir)))
