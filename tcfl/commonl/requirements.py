#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import sys
import os
import pkg_resources

def verify_python_version():
    vi = sys.version_info
    return pkg_resources.parse_version("%d.%d" % (vi[0], vi[1])) \
        >= pkg_resources.parse_version("2.7")

def verify_flask_version():
    import flask
    return pkg_resources.parse_version(flask.__version__) \
        >= pkg_resources.parse_version("0.10")

def verify_pyusb_version():
    import usb
    return pkg_resources.parse_version(usb.__version__) \
        >= pkg_resources.parse_version("0")

def verify_zephyr_sdk_version():
    sdk_path = os.environ.get('ZEPHYR_SDK_INSTALL_DIR',None)
    version = None
    if not sdk_path:
        raise ValueError("ZEPHYR_SDK_INSTALL_DIR is not defined")

    file_version = os.path.join(sdk_path,'sdk_version')
    if not os.path.exists(file_version):
        raise ValueError("Cannot find version file in %s"%file_version)

    with open(file_version) as version_file:
        version = version_file.read().strip()
    return pkg_resources.parse_version(version) \
        >= pkg_resources.parse_version("0.8.2")
