#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import fileinput

import distutils.command.install_data
import distutils.command.sdist
import distutils.core
import distutils.sysconfig

import setupl


distutils.core.setup(
    name = 'tcf-sketch',
    description = "TCF client setup Arduino Sketch",
    long_description = """\
Dependencies and default config files for Arduino Sketches
""",
    version = setupl.version,
    url = None,
    author = "Inaky Perez-Gonzalez",
    author_email = "inaky.perez-gonzalez@intel.com",
    packages = [
    ],
    scripts = [ ],
    # This is needed so when data is to be installed, our
    # _install_data class is used.
    cmdclass = dict(
    ),
    data_files = [
        ('etc/tcf/', [ 'conf_sketch.py' ]),
    ],
)
