#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

target = ttbl.test_target("t0")
ttbl.config.target_add(
    target,
    tags = {
        'ipv4_addr': "127.0.0.1"
    })
