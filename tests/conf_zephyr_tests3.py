#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


# We only use 3-BSP BSP models here, for testcases that will
# specifically manage the console particulars of QEMU multiple BSP.

ttbl.config.target_add(tt_qemu_zephyr("za-03", [ "x86", "arm", "nios2" ]),
                       target_type = "qemu-x86+arm+nios2")
ttbl.config.target_add(tt_qemu_zephyr("zb-03", [ "x86", "arm", "nios2" ]),
                       target_type = "qemu-x86+arm+nios2")
ttbl.config.target_add(tt_qemu_zephyr("zc-03", [ "x86", "arm", "nios2" ]),
                       target_type = "qemu-x86+arm+nios2")
