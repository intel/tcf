#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.power

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "power", ttbl.power.interface(
        power0 = ttbl.power.fake_c(),
        power1 = ttbl.power.fake_c(),
        power2 = ttbl.power.fake_c(),
    )
)
