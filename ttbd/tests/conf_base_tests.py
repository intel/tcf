#! /usr/bin/python2
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
# Note we rely on:
# - targets have bs1, bsp2 and bsp1+bsp2 on many TCs
# - targets are cleaned up

for i in range(9):
    name = "t%d" % i
    target = ttbl.test_target(name, tags = {
        'bsp_models': {
            'bsp1+bsp2': ['bsp1', 'bsp2'],
            'bsp1': None,
            'bsp2': None
        },
        'bsps' : {
            "bsp1": dict(val = 1),
            "bsp2": dict(val = 2),
        },
    })
    target.interface_add("power", ttbl.power.interface(ttbl.pc.nil(name)))

