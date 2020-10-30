#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.images

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "images", ttbl.images.interface(
        image0 = ttbl.images.fake_c(estimated_duration = 10),
        image1 = ttbl.images.fake_c(estimated_duration = 20),
    ))
