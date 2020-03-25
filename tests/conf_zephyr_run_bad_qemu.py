#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

ttbl.config.target_add(tt_qemu_zephyr("bad-qemu-01", [ "x86" ]),
                       target_type = "qemu-x86")
ttbl.test_target.get("bad-qemu-01")._qemu_cmdlines['x86'] \
    +=  " __somethingwrong__ "
