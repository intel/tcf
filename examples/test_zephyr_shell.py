#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# We don't need to document every single thing
# pylint: disable = missing-docstring
import time
import os

import tcfl.tc
import tcfl.tl

@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
# Ask for a target that defines an zephyr_board field, which indicates
# it can run the Zephyr OS
@tcfl.tc.target('zephyr_board',
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "samples", "subsys",
                                          "shell", "shell_module"))
class _test(tcfl.tc.tc_c):
    zephyr_filter = "CONFIG_UART_CONSOLE and CONFIG_SERIAL_SUPPORT_INTERRUPT"
    zephyr_filter_origin = os.path.abspath(__file__)

    def eval(self, target):
        self.expecter.timeout = 20
        target.crlf = "\r"
        target.expect("shell>")
        target.send("select sample_module")
        target.expect("sample_module>")
        for cnt in range(5):
            ts = time.time()
            target.send("ping")
            target.expect("pong")
            target.send("params %d %.2f" % (cnt, ts))
            # Once the kernel is patched, we can remove that ?
            target.expect("argc = 3")
            target.expect("argv[0] = params")
            target.expect("argv[1] = %d" % cnt)
            target.expect("argv[2] = %.2f" % ts)

    def teardown_dump_on_failure(self):
        tcfl.tl.console_dump_on_failure(self)
