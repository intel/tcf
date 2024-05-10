#! /usr/bin/python3
#
# Copyright (c) 2024 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import os

import ttbl.capture
import ttbl.store
import ttbl.raritan_emx

srcdir = os.path.dirname(os.path.abspath(__file__))
topdir = os.path.dirname(srcdir)

target = ttbl.test_target("t0")
AC1 = ttbl.raritan_emx.pci(
    "username:plaintextpassword@hostname.domain:30")
AC2 = ttbl.raritan_emx.pci(
    "username@hostname.domain:30",
    # this file is in the repo
    password = f"FILE:{topdir}/tests/samplepasswordfile")

target.interface_add(
    "store", ttbl.store.interface()
)
target.interface_add(
    "power", ttbl.power.interface(AC1 = AC1, AC2 = AC2)
)
target.interface_add(
    "capture", ttbl.capture.interface(AC1 = AC1, AC2 = AC2)
)
ttbl.config.target_add(
    target,
    tags = {}
)
