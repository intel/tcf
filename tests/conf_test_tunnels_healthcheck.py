#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

target = ttbl.test_target("t0")
ttbl.config.target_add(
    target,
    tags = {
        'ipv4_addr': "127.0.0.1",
        "interconnects": {
            # this is just to trick target_ext_tunel.extension._healtcheck()
            "fake": {
                "ipv4_addr": "127.0.0.1",
                "ipv4_prefix_len": 8
            },
        },
    })
