#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
import ttbl.config
ttbl.config.reason_len_max = 32
ttbl.config.target_add(ttbl.test_target('local_test'))
