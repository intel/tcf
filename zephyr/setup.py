#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import fileinput

import distutils.command.install_data
import distutils.command.sdist
import distutils.core
import distutils.sysconfig

import setupl


distutils.core.setup(
    name = 'tcf-zephyr',
    description = "TCF client setup Zephyr OS",
    long_description = """\
Dependencies and default config files for Zephyr OS
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
        install_data = setupl._install_data
    ),
    data_files = [
        ('@sysconfigdir@/tcf/', [ 'conf_zephyr.py',
                                  'sanitycheck-platform-schema.yaml',
                                  'sanitycheck-tc-schema.yaml' ]),
    ],
)
