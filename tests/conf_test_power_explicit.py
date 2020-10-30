#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.power

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "power", ttbl.power.interface(
        ( 'ex', ttbl.power.fake_c(explicit = 'both') ),
        ( 'fp1', ttbl.power.fake_c(explicit = 'on') ),
        ( 'fp2', ttbl.power.fake_c(explicit = 'on') ),
        ( 'ac1', ttbl.power.fake_c(explicit = 'off') ),
        ( 'ac2', ttbl.power.fake_c(explicit = 'off') ),
        ( 'dc', ttbl.power.fake_c() ),
    ))
