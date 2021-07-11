#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import commonl

import ttbl.power

class daemon_test_c(ttbl.power.daemon_c):
    def verify(self, target, component, cmdline_expanded):
        return True

target = ttbl.test_target("t0")
target.interface_add(
    "power",
    ttbl.power.interface(
        c0 = daemon_test_c(
            cmdline = [ "/usr/bin/sleep", "20d" ],
        ),
    )
)
ttbl.config.target_add(target)
