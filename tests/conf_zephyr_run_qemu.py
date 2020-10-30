#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

ttbl.config.target_add(tt_qemu_zephyr("qemu-01", [ "x86" ]),
                       target_type = "qemu-x86")
ttbl.config.target_add(tt_qemu_zephyr("qemu-02", [ "x86" ]),
                       target_type = "qemu-x86")
ttbl.config.target_add(tt_qemu_zephyr("qemu-03", [ "x86" ]),
                       target_type = "qemu-x86")
