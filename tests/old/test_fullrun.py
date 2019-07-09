#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import filecmp
import getpass
import logging
import os
import random
import re
import requests
import shutil
import signal
import sys
import tempfile
import time
import ttbl
from tcfl import commonl.testing
import unittest

# I bet there is a better way to do this...but we need the symbol to
# be in the logging module so that it is not included in the "function
# that called this" by the logging's internals.
# For debugging, levels are D2: 9, D3: 8, D4:7 ...
import logging
setattr(logging, "logc", logging.root.critical)
setattr(logging, "logx", logging.root.exception)
setattr(logging, "loge", logging.root.error)
setattr(logging, "logw", logging.root.warning)
setattr(logging, "logi", logging.root.info)
setattr(logging, "logd", logging.root.debug)
setattr(logging, "logdl", logging.root.log)
from logging import logc, loge, logx, logw, logi, logd, logdl

class test_run(unittest.TestCase, commonl.testing.test_ttbd_mixin):
    """
    Runs a full test run acquire/image-set/power-on/check/power-off-
    """

    @classmethod
    def setUpClass(cls):
        commonl.testing.test_ttbd_mixin.setUpClass(cls.configfile())

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()

    target = "viper-qemu-a"

    @classmethod
    def configfile(cls):
        return """\
#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.tt_qemu as tt_qemu

ttbl.config.target_add(tt_qemu.tt_qemu("%s", [ 'x86' ],
            _tags = {
                'bsps': {
                    'x86': dict(board='qemu_x86',
                                qemu_cmdline=
                                "qemu-system-i386 -m 32 -cpu qemu32 -no-reboot -nographic -display none " \
                                "-net none -clock dynticks -no-acpi -balloon none " \
                                "-L /usr/share/qemu/bios.bin " \
                                "-bios bios.bin -machine type=pc-0.14 " \
                                "-nodefaults -serial stdio"),
                    'arm': dict(board='qemu_cortex_m3',
                                qemu_cmdline=
                                "qemu-system-arm -cpu cortex-m3 " \
                                "-machine lm3s6965evb -nographic " \
                                "-nodefaults -serial stdio")
                }
            }))
""" \
    % cls.target

    def test_00_acquire(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf -vvv --config-path : --url http://localhost:%d "
            "acquire %s"
            % (self.port, self.target))
        self.assertEqual(sp.join(), 0, msg = sp.output_str)

    def test_01_images_upload_set(self):
        kernel = commonl.testing.test_ttbd_mixin.srcdir + "/tests/data/philosophers-uk-generic_pc.elf"
        image = os.path.basename(kernel)
        shutil.copy(kernel, self.wd)
        # FIXME copy file
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : --url http://localhost:%d "
            "images-upload-set %s kernel:%s"
            % (self.port, self.target, image))
        self.assertEqual(sp.join(), 0, msg = sp.output_str)

    def test_02_power_on(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : --url http://localhost:%d "
            "power-on %s"\
            % (self.port, self.target))
        self.assertEqual(sp.join(), 0, msg = sp.output_str)
        logi("letting it run three seconds")
        time.sleep(3)

    def test_03_console_read_all(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : --url http://localhost:%d "
            "console-read --all --filter-ansi %s"\
            % (self.port, self.target))
        self.assertEqual(sp.join(), 0, msg = sp.output_str)
        regex = re.compile("^Philosopher [0-9] (EATING|THINKING)")
        count = 0
        for _line in sp.stdout_lines:
            for line in _line.split("\n"):
                line = line.strip()
                m = regex.match(line)
                if m:
                    count += 1
        self.assertGreater(count, 3, msg = "not enough matches found")

    def test_04_power_off(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : --url http://localhost:%d "
            "power-off %s"\
            % (self.port, self.target))
        self.assertEqual(sp.join(), 0, msg = sp.output_str)

    @unittest.expectedFailure
    def test_05_broker_file_delete(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : --url http://localhost:%d "
            "broker-file-delete %s %s"\
            % (self.port, self.image))
        self.assertEqual(sp.join(), 0, msg = sp.output_str)

    def test_06_release(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : --url http://localhost:%d "
            "release %s"\
            % (self.port, self.target))
        self.assertEqual(sp.join(), 0, msg = sp.output_str)


if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main(failfast = True)
