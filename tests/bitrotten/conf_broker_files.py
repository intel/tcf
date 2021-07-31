#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.tt

# We just need a target to refer to the server, won't even power it up
ttbl.config.target_add(
    ttbl.tt.tt_power("t1", None, False),
    tags = {
        'skip_cleanup' : True,
    }
)
