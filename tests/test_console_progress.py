#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import inspect
import os
import sys
import time
import unittest

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)

ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target(ttbd.url_spec)
class _test(tcfl.tc.tc_c):
    """
    Test progress expectations in text consoles with target.expect()
    and target.shell.run()

    We create a target with a fake text console in
    conf_test_console_progress.py that prints, right after enabling it

      message_1  [every second]
      message_2  [every to seconds]
      message_1  [every second]
      message_2  [every to seconds]
      ...
      message_3  [after 15s]

    then we use it to test expect() and shell.run()
    """
    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_00_full_read(self, target):
        # verify we an read the fake console
        target.console.disable()
        target.console.enable()
        time.sleep(3)	# let it spin up
        data = target.console.read("c0")
        target.report_pass("can read data from the fake console c0",
                           { "data": data })


    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_05_progress_read(self, target):
        # Test we can use expect to read content; the message_3 only
        # comes up after 15s; message_1 comes every second; we wait
        # for a max of 3 seconds, but every time message_1 comes up,
        # we add 2 seconds to a max of 20.
        #
        # If things are fine, the timeout increases beyond 15 until
        # message_3 arrives
        target.console.disable()
        target.console.enable()
        target.expect("")
        target.expect(
            "message_3", timeout = 3,
            progress_expectations = {
                "progress_1": target.console.text(
                    "message_1",
                    timeout = 20,
                    raise_on_found = 2,
                ),
            }
        )
        target.report_pass("expect() worked as expected with progress expectations")


    @tcfl.tc.subcase(break_on_non_pass = False)
    def eval_10_progress_shell(self, target):
        # Same thing, but with target.shell.run()
        #
        # In this case we take message_3 to be a prompt regex, so we
        # "run a command" and wait for the prompt while seeing progress.
        #
        # Test we can use expect to read content; the message_3 only
        # comes up after 15s; message_1 comes every second; we wait
        # for a max of 3 seconds, but every time message_1 comes up,
        # we add 2 seconds to a max of 20.
        #
        # If things are fine, the timeout increases beyond 15 until
        # message_3 arrives
        target.console.disable()
        target.console.enable()
        target.shell.run(
            "write_for_3", timeout = 3,
            prompt_regex = "message_3",
            progress_expectations = {
                "progress_1": target.console.text(
                    "message_1",
                    timeout = 20,
                    raise_on_found = 2,
                ),
            }
        )
        target.report_pass("shell.run() as expected with progress expectations")


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
