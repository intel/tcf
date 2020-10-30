#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#! /usr/bin/python3

import ttbl
import ttbl.config
import ttbl.power

target = ttbl.test_target("t0")
ttbl.config.target_add(target)

# add instrumentation data that will be wiped because no driver requests it
target.fsdb.set("instrumentation.1234.name", "test")
target.fsdb.set("instrumentation.1234.name_long", "test")
# add instrumentation data that no driver requests but will be kept
# because it has the "manual" label
target.fsdb.set("instrumentation.2343.name", "test")
target.fsdb.set("instrumentation.2343.name_long", "test")
target.fsdb.set("instrumentation.2343.manual", True)

# make a fake interface, to check it is wiped
target.fsdb.set("interfaces.madeup.instance.instrument", "kola")

target.interface_add(
    "power", ttbl.power.interface(power0 = ttbl.power.fake_c()))
