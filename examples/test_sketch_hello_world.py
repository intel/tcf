#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import tcfl.config
import tcfl.tc

# Ask for a target that defines an sketch_fqbn field, that's the
# Arduino Sketch descriptor
@tcfl.tc.target("sketch_fqbn", app_sketch = "hello_world.ino")
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval(target):
        target.expect("Hello World!")
