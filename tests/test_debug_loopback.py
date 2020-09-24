#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

import commonl.testing
import tcfl
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target(ttbd.url_spec)
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval(target):
        target.debug.start()
        i = target.debug.list()['debug0'].get('state', None)
        assert i == 'started', "info reports %s" % i

        target.debug.stop()
        i = target.debug.list()['debug0']
        assert i == None, "info reports %s, expeced None" % i

        target.debug.halt()
        i = target.debug.list()['debug0'].get('state', None)
        assert i == 'halted', "info reports %s" % i

        target.debug.resume()
        i = target.debug.list()['debug0'].get('state', None)
        assert i == 'resumed', "info reports %s" % i

        target.debug.reset()
        i = target.debug.list()['debug0'].get('state', None)
        assert i == 'reset', "info reports %s" % i

        target.debug.reset_halt()
        i = target.debug.list()['debug0'].get('state', None)
        assert i == 'reset_halted', "info reports %s" % i

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)

@tcfl.tc.target(ttbd.url_spec)
class release_hooks(tcfl.tc.tc_c):
    """
    If we start debugging, when the target is released the debugging
    is stopped, signalling that
    ttbd.ttbl.debug.interface._release_hook() has run
    """

    def eval(self, target):
        target.debug.start()
        i = target.debug.list()['debug0'].get('state', None)
        assert i == 'started', "info reports %s" % i
        target.release()
        target.acquire()
        state = target.debug.list()['debug0']
        assert state == None, \
            "after releasing and re-acquiring, debug state is %s;" \
            " expected None" % state
        self.report_pass("release hooks were called on target release")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
