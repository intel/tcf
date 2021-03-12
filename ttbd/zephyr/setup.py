#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# Invoke with
#
# VERSION=$(git describe) python ./setup.py bdist_rpm
#
#

import os
import sys

import distutils.core

import setupl

distutils.core.setup(
    name = 'ttbd-zephyr',
    description = "TCF TTBD server for Zephyr OS",
    long_description = """\
This is the TCF's TTBD for running Zephyr OS in targets
""",
    version = setupl.version,
    url = None,
    author = "Inaky Perez-Gonzalez",
    author_email = "inaky.perez-gonzalez@intel.com",
    # This is needed so when data is to be installed, our
    # _install_data class is used.
    cmdclass = dict(
        install_data = setupl._install_data,
    ),
    data_files = [
        ('@sysconfigdir@/ttbd-production/', [ 'conf_06_zephyr.py' ]),
        # do not @prefix@ this, it always has to be in var/lib/ttbd
        ('/var/lib/ttbd', [ 'frdm_k64f_recovery.bin' ]),
    ],
)
