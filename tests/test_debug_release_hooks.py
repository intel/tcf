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
    os.path.join(srcdir, "conf_00_lib.py"),
    os.path.join(srcdir, "conf_zephyr_run_qemu.py"),
])


@tcfl.tc.target(ttbd.url_spec + ' and interfaces_names:".*tt_debug_mixin.*"')
class _test_00(tcfl.tc.tc_c):
    """
    Test that when we enable debug and then release a target, the
    debug enablement is cleared upon release.
    """
    def eval(self, target):
        rtb = target.rt['rtb']

        # When we start debugging, debugging is set to on
        target.debug.start()
        rt = rtb.rest_tb_target_update(target.id)
        assert rt['debug'] == 'On'

        # When we stop it, the debug property dissapears
        target.debug.stop()
        rt = rtb.rest_tb_target_update(target.id)
        assert not 'debug' in rt

        # When we start it, it appears again
        target.debug.start()
        rt = rtb.rest_tb_target_update(target.id)
        assert rt['debug'] == 'On'

        # But if we release the target, it is cleared
        target.rtb.rest_tb_target_release(target.rt, ticket = self.ticket)

        rt = rtb.rest_tb_target_update(target.id)
        assert not 'debug' in rt

        # Re-acquire the target so the test can conclude well
        target.rtb.rest_tb_target_acquire(target.rt, ticket = self.ticket)

    @classmethod
    def class_teardown(cls):
        ttbd.check_log_for_issues()
        assert cls.class_result == tcfl.tc.result_c(1, 0, 0, 0, 0), \
            "%s: expected 1 testcase passed, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)
