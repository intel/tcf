#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import tc

class patch_tags(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to patch different tags in older
    servers that are not properly configured.
    """

    def __init__(self, target):
        if 'arm' in target.bsps:
            target.rt['bsps']['arm']['sketch_fqbn'] = \
                "sam:1.6.9:arduino_due_x_dbg"
            target.rt['bsps']['arm']['sketch_kernelname'] = "sketch.ino.bin"

        for bsp in target.bsps_all:
            if 'board' in target.rt['bsps'][bsp]:
                zephyr_board = target.rt['bsps'][bsp]['board']
                target.rt['bsps'][bsp]['zephyr_board'] = zephyr_board
            elif 'zephyr_board' in target.rt['bsps'][bsp]:
                board = target.rt['bsps'][bsp]['zephyr_board']
                target.rt['bsps'][bsp]['board'] = board

            if 'kernelname' in target.rt['bsps'][bsp]:
                zephyr_kernelname = target.rt['bsps'][bsp]['kernelname']
                target.rt['bsps'][bsp]['zephyr_kernelname'] = zephyr_kernelname
            elif 'zephyr_kernelname' in target.rt['bsps'][bsp]:
                kernelname = target.rt['bsps'][bsp]['zephyr_kernelname']
                target.rt['bsps'][bsp]['kernel'] = kernelname

        raise self.unneeded
