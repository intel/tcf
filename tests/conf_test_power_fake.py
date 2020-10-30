#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.power

target = ttbl.test_target("t0")
ttbl.config.target_add(
    target,
    tags = {
        'bsp_models': {
            'bsp1': None,
        },
        'bsps' : {
            "bsp1": dict(val = 1),
        },
        'skip_cleanup' : True,
    })
target.interface_add(
    "power", ttbl.power.interface(power0 = ttbl.power.fake_c()))
