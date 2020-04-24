#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import ttbl
import ttbl.pc
import ttbl.tt

for ic_name in ['r', 's', 't']:
    ttbl.config.interconnect_add(ttbl.interconnect_c(ic_name),
                                 ic_type = ic_name)
    for i in range(5):
        name = "%s%d" % (ic_name, i)
        ttbl.config.target_add(
            ttbl.tt.tt_power_lc(name, ttbl.pc.nil(name), power = False),
            target_type = "typeA")
        ttbl.test_target.get(name).add_to_interconnect(ic_name)
    for i in range(5):
        i += 5
        name = "%s%d" % (ic_name, i)
        ttbl.config.target_add(
            ttbl.tt.tt_power_lc(name, ttbl.pc.nil(name), power = False),
            target_type = "typeB")
        ttbl.test_target.get(name).add_to_interconnect(ic_name)
