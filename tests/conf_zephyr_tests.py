#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

# We only use single BSP BSP models here, because with QEMU targets
# otherwise we have to muck around which is the right console

ttbl.config.target_add(tt_qemu_zephyr("za-01", [ "x86" ]),
                       target_type = "qemu-x86")
ttbl.config.target_add(tt_qemu_zephyr("zb-01", [ "arm" ]),
                       target_type = "qemu-arm")
ttbl.config.target_add(tt_qemu_zephyr("zc-01", [ "nios2" ]),
                       target_type = "qemu-nios2")
