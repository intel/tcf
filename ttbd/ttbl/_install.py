#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Note this file gets rewritten during installation
# By default, we point to the source
import os

# when running from source, we want the toplevel source dir
installroot = os.path.dirname(os.path.dirname(__file__))
sysconfig_paths = [
    installroot,
    os.path.join(installroot, "zephyr")
]
share_path = installroot
