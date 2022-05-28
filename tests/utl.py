#! /usr/bin/python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
Unit test library and utilites
==============================
"""
import os

def tcf_tool_path(testcase):
    """
    Return the to the TCF tool in the current source tree
    """
    return os.path.join(testcase.kws['srcdir_abs'], os.path.pardir, "tcf")
