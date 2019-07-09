#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

from tcfl import commonl.testing
import tcfl.tc
import tcfl.tc_zephyr_sanity
import tcfl.tl

srcdir = os.path.dirname(__file__)

ttbd = commonl.testing.test_ttbd(config_files = [
    os.path.join(srcdir, "conf_00_lib.py"),
    os.path.join(srcdir, "conf_zephyr_tests.py"),
])

tcfl.tc.target_c.extension_register(tcfl.app_zephyr.zephyr)
if not tcfl.app.driver_valid(tcfl.app_zephyr.app_zephyr.__name__):
    tcfl.app.driver_add(tcfl.app_zephyr.app_zephyr)
tcfl.tc.tc_c.driver_add(tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c)


@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
@tcfl.tc.target(
    ttbd.url_spec + " and zephyr_board",
    app_zephyr = os.path.join(os.environ['ZEPHYR_BASE'],
                              "tests", "kernel", "common"))
class _01_simple(tcfl.tc.tc_c):
    """
    Zephyr's testcase.yaml build, execute and pass
    """
    # app_zephyr provides start() methods start the targets
    @staticmethod
    def eval(target):
        target.expect("PROJECT EXECUTION SUCCESSFUL")
