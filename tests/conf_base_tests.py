#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.pc
import ttbl.tt

#
# Targets for testing that have nothing in there but a nil power switch
#
# Note we rely on these t0 - t9 targets to have bs1, bsp2 and
# bsp1+bsp2 on many TCs
for i in range(9):
    name = "t%d" % i
    ttbl.config.target_add(
        ttbl.tt.tt_power_lc(name, ttbl.pc.nil(name), power = False),
        tags = {
            'bsp_models': {
                'bsp1+bsp2': ['bsp1', 'bsp2'],
                'bsp1': None,
                'bsp2': None
            },
            'bsps' : {
                "bsp1": dict(val = 1,
                             zephyr_board = "fake_zephyr_board1",
                             zephyr_kernelname = "fake_zephyr_kernelname1"),
                "bsp2": dict(val = 2,
                             zephyr_board = "fake_zephyr_board2",
                             zephyr_kernelname = "fake_zephyr_kernelname2"),
            },
            'skip_cleanup' : True,
        }
    )

# We rely on s0..s9 to be simple targets with a single BSP
for i in range(9):
    name = "s%d" % i
    ttbl.config.target_add(
        ttbl.tt.tt_power_lc(name, ttbl.pc.nil(name), power = False),
        tags = {
            'bsp_models': dict(bsp1 = None),
            'bsps' : dict(bsp1 =
                          dict(val = 1,
                               zephyr_board = "fake_zephyr_board1",
                               zephyr_kernelname = "fake_zephyr_kernelname1")),
            'skip_cleanup' : True,
        }
    )
