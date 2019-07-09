#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import inspect
import os
import sys

import requests

from tcfl import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)

ttbd = commonl.testing.test_ttbd(config_files = [
    os.path.join(srcdir, "conf_reap.py") ])


@tcfl.tc.target(ttbd.url_spec + " and id == 't0'")
class _test_00(tcfl.tc.tc_c):
    def eval(self, target):
        """
        Power cycle the target; that will start a daemon and kill
        it; if things work as they should, it shall leave no zombie.
        """
        target.power.on()
        r = target.power.get()
        assert r == True, "power state is not on (as expected) but %s" % r
        _daemon_pid = target.property_get('daemon_pid')
        self.report_info("daemon pid is %s" % _daemon_pid)
        daemon_pid = int(_daemon_pid)

        target.power.off()
        r = target.power.get()
        assert r == False, \
            "power state is not off (as expected) but %s" % r

        # Verify the PID is dead
        zombies = commonl.ps_zombies_list([ daemon_pid ])
        assert not daemon_pid in zombies, \
            "Daemon with pid %d was killed and it is a zombie " \
            "so it didn't reap properly" % daemon_pid

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(1, 0, 0, 0, 0), \
            "%s: expected 1 testcase passed, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)


@tcfl.tc.target(ttbd.url_spec + " and id == 't1'")
class _test_01(tcfl.tc.tc_c):
    @staticmethod
    def eval_on(target):
        """
        Power on the target; it will run 'false' and it shall fail
        """
        try:
            target.power.on()
        except requests.HTTPError as e:
            assert e.message == ("400: t1: Command 'false' returned "
                                 "non-zero exit status 1"), \
                "failed to power on exception didn't contain the " \
                "right message, but %s" % e.message

    @staticmethod
    def eval_off(target):
        """
        Power off the target; it will run 'true' and it shall work
        """
        target.power.off()

    @classmethod
    def class_teardown(cls):
        ttbd.errors_ignore.append(
            "Command 'false' returned non-zero exit status 1")
        ttbd.errors_ignore.append("CalledProcessError(retcode, cmd, "
                                  "output=output)")
        assert cls.class_result == tcfl.tc.result_c(1, 0, 0, 0, 0), \
            "%s: expected 1 testcase passed, got %s instead" \
            % (cls.__name__, cls.class_result)
        ttbd.check_log_for_issues()
        return tcfl.tc.result_c(0, 0, 0, 0, 0)
