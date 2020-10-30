#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import re

from tcfl import commonl.testing
import tcfl.tc
import tcfl.tl

srcdir = os.path.dirname(__file__)

ttbd = commonl.testing.test_ttbd(config_files = [
    os.path.join(srcdir, "conf_00_lib.py"),
    os.path.join(srcdir, "conf_zephyr_tests.py"),
    os.path.join(srcdir, "conf_zephyr_tests3.py"),
    os.path.join(srcdir, "conf_07_zephyr.py"),
])

tcfl.tc.target_c.extension_register(tcfl.app_zephyr.zephyr)
if not tcfl.app.driver_valid(tcfl.app_zephyr.app_zephyr.__name__):
    tcfl.app.driver_add(tcfl.app_zephyr.app_zephyr)


@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
@tcfl.tc.target(
    ttbd.url_spec + " and zephyr_board",
    app_zephyr = os.path.join(os.environ['ZEPHYR_BASE'],
                              "samples", "hello_world"))
class _01_simple(tcfl.tc.tc_c):
    """
    Expect to find Hello World in the most simple way
    """
    # app_zephyr provides start() methods start the targets
    @staticmethod
    def eval(target):
        target.expect("Hello World! %s" % target.bsp,
                      # In the multiple BSP simulation we have, each
                      # BSP prints to a different console
                      console = target.bsp)


@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
@tcfl.tc.target(
    ttbd.url_spec + " and zephyr_board",
    app_zephyr = os.path.join(os.environ['ZEPHYR_BASE'],
                              "samples", "hello_world"))
class _02_expecter_loop(tcfl.tc.tc_c):
    """
    Expect to find Hello World but by setting hooks and running the
    expecter loop, which shall return a pass exception when all the
    expectations are met.
    """
    @staticmethod
    def setup(target):
        target.on_console_rx("Hello World! %s" % target.bsp, 20,
                             console = target.kws.get('console', None))

    # app_zephyr provides start() methods start the targets
    def eval(self):
        self.expecter.run()


@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
@tcfl.tc.target(
    ttbd.url_spec + " and zephyr_board",
    app_zephyr = os.path.join(os.environ['ZEPHYR_BASE'],
                              "samples", "hello_world"))
@tcfl.tc.target(
    ttbd.url_spec + " and zephyr_board",
    app_zephyr = os.path.join(os.environ['ZEPHYR_BASE'],
                              "samples", "hello_world"))
class _03_multi_bsp_expecter_loop(tcfl.tc.tc_c):
    """
    With a special multi-BSP target we defined in the configuration,
    try to run multiple Hello Worlds on each BSP and ensure we find
    them when running the expectation loop.
    """
    @staticmethod
    def setup(target, target1):
        for t in target, target1:
            t.on_console_rx("Hello World! %s" % t.bsp_model, 20,
                            console = t.kws.get('console', None))

    # app_zephyr provides start() methods start the targets
    def eval(self):
        self.expecter.run()


@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
@tcfl.tc.target(
    ttbd.url_spec + " and zephyr_board",
    app_zephyr = {
        'arm': os.path.join(os.environ['ZEPHYR_BASE'],
                            "samples", "hello_world")
    })
class _03_multi_bsp_only_one_bsp(tcfl.tc.tc_c):
    """
    With a multi-BSP target, we run only in one and the rest get
    stubbed automatically. We see nothing in the output of the others.
    """
    @staticmethod
    def setup(target):
        for bsp in target.bsps_all:
            if bsp == 'arm':
                continue
            # Any output on the other BSPs means the stub is not being silent
            target.on_console_rx(re.compile(".+"),
                                 result = 'fail', timeout = None,
                                 # Each BSP has a console named after it
                                 console = bsp)

    @staticmethod
    def eval(target):
        target.expect("Hello World! arm")


@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
@tcfl.tc.target(
    ttbd.url_spec + " and zephyr_board",
    app_zephyr = dict(
        x86 = os.path.join(os.environ['ZEPHYR_BASE'],
                           "samples", "hello_world"),
        arm = os.path.join(os.environ['ZEPHYR_BASE'],
                           "samples", "hello_world"),
        nios2 = os.path.join(os.environ['ZEPHYR_BASE'],
                             "samples", "hello_world"),
    )
)
class _04_multi_bsp_three_hello_world(tcfl.tc.tc_c):
    """
    With a special three-BSP target we defined in the configuration,
    try to run multiple Hello Worlds on each BSP and ensure we find
    them when running the expectation loop.
    """
    @staticmethod
    def setup(target):
        for bsp in target.bsps_all:
            target.bsp_set(bsp)
            target.on_console_rx("Hello World! %s" % target.bsp, 20,
                                 console = bsp)
    def eval(self):
        self.expecter.run()
