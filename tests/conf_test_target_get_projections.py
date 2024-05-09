#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.power

target = ttbl.test_target("t0")
target.interface_add(
    "power", ttbl.power.interface(power0 = ttbl.power.fake_c()))
ttbl.config.target_add(
    target,
    tags = {
        "dict": {
            "1": "1",
            "2" : {
                "2a": "2a",
                "2b": {
                    "2b1": "2b1",
                },
            },
            "3": {
            },
        },
    })
