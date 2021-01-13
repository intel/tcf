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

import distutils
import distutils.command.bdist_rpm
import distutils.command.install_data
import distutils.command.sdist
import distutils.command.build_py
import distutils.core
import distutils.sysconfig

import setupl

distutils.core.setup(
    name = 'ttbd-pos',
    description = "TCF TTBD server Provisioning OS extensions",
    long_description = """\
These are the extensions to the TTBD server that enable to do fast
imaging on PC-class targets via DHCP / TFTP.
""",
    version = setupl.version,
    url = "http://intel.github.com/tcf",
    author = "Inaky Perez-Gonzalez",
    author_email = "inaky.perez-gonzalez@intel.com",
    cmdclass = dict(
        install_data = setupl._install_data,
    ),
    packages = [ ],
    scripts = [ ],
    data_files = [
        ( 'etc/systemd/system/ttbd@.service.d/', [
            'pos.conf'
        ]),
        ( '/etc/httpd/conf.d/', [
            'ttbd.conf',
        ]),
        ( '/etc/exports.d/', [
            'ttbd-pos.exports',
        ]),
        ( '@prefix@/share/tcf/', [
            'kickstart-install.sh',
            'tcf-image-setup.sh',
            'tcf-pos-live-setup.sh',
        ]),
        ( '@prefix@/share/tcf/content', [
            'evemu.bin.armv7l.tar.gz',
            'evemu.bin.x86_64.tar.gz',
        ]),
    ],
)
