#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import tcfl.config
import tcfl.tc

tags = {}
arduino_libdir = getattr(tcfl.config, "arduino_libdir", None)
if not arduino_libdir:
    tags['skip'] = "Missing Sketch environment, can't run; install tcf-sketch?"

_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

# Ask for a target that defines an sketch_fqbn field, that's the
# Arduino Sketch descriptor
@tcfl.tc.target("sketch_fqbn", app_sketch = "hello_world.ino")
@tcfl.tc.tags(**tags)
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval(target):
        target.expect("Hello World!")
