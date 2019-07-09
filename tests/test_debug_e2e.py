#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

from tcfl import commonl.testing
import tcfl
import tcfl.tc

srcdir = os.path.dirname(__file__)

ttbd = commonl.testing.test_ttbd(config_files = [
    os.path.join(srcdir, "conf_run_debug.py") ])


@tcfl.tc.target(ttbd.url_spec)
class _test_00(tcfl.tc.tc_c):
    """
    Test the debug methods can be run
    """
    @staticmethod
    def eval(target):
        target.debug.start()
        i = target.debug.info()
        assert i == 'started', "info reports %s" % i

        target.debug.halt()
        i = target.debug.info()
        assert i == 'halted', "info reports %s" % i

        target.debug.reset()
        i = target.debug.info()
        assert i == 'reset', "info reports %s" % i

        target.debug.reset_halt()
        i = target.debug.info()
        assert i == 'reset_halt', "info reports %s" % i

        target.debug.resume()
        i = target.debug.info()
        assert i == 'resumed', "info reports %s" % i

        target.debug.stop()
        i = target.debug.info()
        assert i.startswith('stopped'), "info reports %s" % i

        target.debug.openocd('a silly command')
        i = target.debug.info()
        assert i.startswith('a silly command'), "info reports %s" % i

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(1, 0, 0, 0, 0), \
            "%s: expected 1 testcase passed, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)
