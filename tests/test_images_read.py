#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import time

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir,
                     "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Traceback"
    ])

maria = """
Doe, A Deer, A female Deer
Ray, A drop of golden sun
Me, a name, I call myself.
Far, A long long way to runnnnnnnnnnnnnnnnnn!
And etc.
"""

@tcfl.tc.target("t0")
class flashes(tcfl.tc.tc_c):
    """
    Test the estimated_duration field from the imaging flasing
    interface is acknolwedged by the flashing interface.
    """
    def eval(self, target):
        target.images.read(image="image0",
                           file_name=self.report_file_prefix + "remotefile",
                           image_offset = 0,
                           read_bytes = None)

        with open(self.report_file_prefix + "remotefile") as f:
            data=f.read()

        if data != maria:
            raise tcfl.tc.failed_e("data read differs",
                                   dict(original = maria,
                                        read = data))

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
