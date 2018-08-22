#! /usr/bin/python2
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
import fileinput
import os

import distutils.command.install_data
import distutils.core
import distutils.sysconfig

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
    ),
    data_files = [
        ('etc/ttbd-production/', [ 'conf_06_zephyr.py' ]),
    ],
)
