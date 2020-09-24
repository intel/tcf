#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.debug

target = ttbl.test_target("t0")
ttbl.config.target_add(
    target,
    tags = {
        # trick for the tunneling system
        'ipv4_addr': "127.0.0.1",
        'bsp_models': {
            'bsp1': None,
        },
        'bsps' : {
            "bsp1": dict(val = 1),
        },
        'skip_cleanup' : True,
    }
)
