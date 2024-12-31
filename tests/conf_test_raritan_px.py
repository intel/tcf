#! /usr/bin/python3
#
# Copyright (c) 2024 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import os

import ttbl.capture
import ttbl.store
import ttbl.raritan_px

srcdir = os.path.dirname(os.path.abspath(__file__))
topdir = os.path.dirname(srcdir)

target = ttbl.test_target("t0")
AC1 = ttbl.raritan_px.pc(
    "username:plaintextpassword@hostname.domain:30")
AC2 = ttbl.raritan_px.pc(
    f"username:FILE:{topdir}/tests/samplepasswordfile@hostname.domain:30")

target.interface_add(
    "store", ttbl.store.interface()
)
target.interface_add(
    "power", ttbl.power.interface(AC1 = AC1, AC2 = AC2)
)

ttbl.config.target_add(
    target,
    tags = {}
)
