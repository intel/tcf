#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
.. _example_sketch_hello_world:

Arduino Sketch Hello World!
===========================

Given a target supported by the Arduino CLI environment, build and
flash a Hello World and verify it actually prints Hello World.

.. literalinclude:: /examples/test_sketch_hello_world.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_sketch_hello_world.py>`::

  $ tcf run -vvv /usr/share/tcf/examples/test_sketch_hello_world.py
  INFO3/        toplevel @local [+0.5s]: version v0.13-83-gbf636c0-dirty
  INFO2/        toplevel @local [+0.5s]: scanning for test cases
  INFO3/        .../test_sketch_hello_world.py @local [+0.2s]: queuing for pairing
  INFO3/fkpqm7  .../test_sketch_hello_world.py @local [+0.0s]: read property 'console-default': 'None' [None]
  INFO1/h4yglm  .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+0.0s]: will run on target group 'target=inaky-mobl1/arduino-mega-01:arm' (PID 28357 / TID 7f9b0911a580)
  PASS2/h4yglm  .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+0.2s]: configure passed
  PASS3/h4yglmB .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+0.2s]: build passed: 'mkdir -p /tmp/tcf.run-Z06yyN/h4yglm/sketch-h4yglm-5eur' @.../tcf/tcfl/app_sketch.py:87
  PASS3/h4yglmB .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+0.9s]: build passed: 'arduino-cli compile --build-path /tmp/tcf.run-Z06yyN/h4yglm/sketch-h4yglm-5eur --build-cache-path /tmp/tcf.run-Z06yyN/h4yglm/sketch-h4yglm-5eur --fqbn arduino:avr:mega ../../t/alloc-tcf.git/examples/hello_world.ino' @.../tcf/tcfl/app_sketch.py:91
  PASS1/h4yglm  .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+1.0s]: build passed
  allocation ID 8itv4h: allocated: arduino-mega-01
  PASS2/h4yglm  .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+6.7s]: deploy passed
  INFO3/h4yglmE .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+6.7s]: starting
  INFO3/h4yglmE .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+6.7s]: power cycling
  INFO2/h4yglmE .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+10.9s]: power cycled
  INFO3/h4yglmE .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+11.5s]: 00/Hello__World__: found 'Hello\\ World\\!' at @0-12 on console inaky-mobl1/arduino-mega-01:serial0 [report-:h4yglm.console-target.arduino-mega-01.serial0.txt]
  INFO3/h4yglmE .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+11.5s]:    console output: Hello World!
  PASS1/h4yglm  .../test_sketch_hello_world.py @inaky-mobl1/arduino-mega-01 [+11.5s]: evaluation passed
  PASS0/        toplevel @local [+12.5s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:11.585148) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

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
