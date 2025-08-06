#! /usr/bin/python3
#
# Copyright (c) 2017-25 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.config
import ttbl.console

# target for CLI tests that allows us to run things in the local
# system as if it was remote
target = ttbl.test_target("t0")
ttbl.config.target_add(target, tags = { 'skip_cleanup' : True })
target.interface_add(
    "console",
    ttbl.console.interface(
        console = ttbl.console.local_c()
    )
)
