#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.store
import ttbl.config

target = ttbl.test_target("t0")
ttbl.config.target_add(target) # store interface added automatically
