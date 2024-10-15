#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.images

class driver_fake_shell_c(ttbl.images.flash_shell_cmd_c):
    # a fake driver that just runs the a command that waits 5s and
    # exits with a given exit code
    def __init__(self, code, expected_return_code):
        assert isinstance(code, int) and code >= 0
        ttbl.images.flash_shell_cmd_c.__init__(
            self,
            # sleep a wee, otherwise if fails too soon
            cmdline = [ "/bin/sh", "-c", "sleep 5s && exit %d" % code ],
            expected_return_code = expected_return_code)


target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "images", ttbl.images.interface(
        image_fails_0_3 = driver_fake_shell_c(0, 3),
        image_fails_3_2 = driver_fake_shell_c(3, 2),
        image_works_0_0 = driver_fake_shell_c(0, 0),
        image_works_1_1 = driver_fake_shell_c(1, 1),
    ))
