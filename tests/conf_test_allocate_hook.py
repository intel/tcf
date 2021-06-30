#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

class interface(ttbl.tt_interface):
    
    def _allocate_hook(self, target, iface_name, allocdb):
        target.fsdb.set("test_property", iface_name + " " + allocdb.allocid)

target = ttbl.test_target("t0")
target.interface_add(
    "sample",
    interface()
)
ttbl.config.target_add(target)
