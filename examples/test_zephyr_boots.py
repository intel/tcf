#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import tcfl.tc

# Ask for a target that defines an zephyr_board field, which indicates
# it can run the Zephyr OS
#
# can't just let it fail if not defined, because then we can't filter
# on the tags and we'll always block if ZEPHYR_APP is undefined
@tcfl.tc.target("zephyr_board",
                app_zephyr = os.path.join(
                    os.environ.get('ZEPHYR_APP',
                                   '__ZEPHYR_APP__not_defined')))
@tcfl.tc.tags(ignore_example = True)
class _test(tcfl.tc.tc_c):
    """
    Build and flash the app given in the environment ZEPHYR_APP,
    evaluate it reaches the boot prompt.

    This is flashing for lazy people.
    """

    @staticmethod
    @tcfl.tc.serially()
    def build(target):
        target.zephyr.config_file_write(
            "banner_config",
            "CONFIG_BOOT_BANNER=y")

    @staticmethod
    def eval(target):
        target.expect("***** Booting Zephyr OS")
