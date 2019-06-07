#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


#
# Add default targets (three networks A, B and C)
#

if ttbl.config.defaults_enabled:

    for letter in [ 'a', 'b' ]:
        nw_idx = ord(letter)
        nw_name = "nw" + letter
        nw_default_targets_add(letter)
