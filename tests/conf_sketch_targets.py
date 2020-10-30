#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


ttbl.config.target_add(
    ttbl.test_target("a2-00-bo"),
    tags = {
        'bsp_models': { 'arm': None },
        'bsps' : {
            "arm": dict(
                board = "arduino_due",
                kernelname = 'zephyr.bin',
                zephyr_board = "arduino_due",
                zephyr_kernelname = 'zephyr.bin',
                sketch_fqbn = "sam:1.6.9:arduino_due_x_dbg",
                sketch_kernelname = "sketch.ino.bin",
                console = "",)
        },
        'build_only': True,
        'quark_se_stub': "no",
    },
    target_type = "arduino2")

ttbl.config.target_add(
    ttbl.test_target("a2-01"),
    tags = {
        'bsp_models': { 'arm': None },
        'bsps' : {
            "arm": dict(
                board = "arduino_due",
                kernelname = 'zephyr.bin',
                zephyr_board = "arduino_due",
                zephyr_kernelname = 'zephyr.bin',
                sketch_fqbn = "sam:1.6.9:arduino_due_x_dbg",
                sketch_kernelname = "sketch.ino.bin",
                console = "",)
        },
        'build_only': True,
        'quark_se_stub': "no",
    },
    target_type = "arduino2")
