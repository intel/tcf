#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.images


target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "images", ttbl.images.interface(
        image0 = ttbl.images.flash_shell_cmd_c(
            cmdline = [
                "/usr/bin/bash",
                "-c",
                "for ((count = 0; count < 10; count++)); do date; sleep 1s; done"
            ],
            estimated_duration = 13,
        ),
        image_p0 = ttbl.images.flash_shell_cmd_c(
            cmdline = [
                "/usr/bin/bash",
                "-c",
                "for ((count = 0; count < 10; count++)); do date; sleep 1s; done"
            ],
            estimated_duration = 13, parallel = True,
        ),
        image_p1 = ttbl.images.flash_shell_cmd_c(
            cmdline = [
                "/usr/bin/bash",
                "-c",
                "for ((count = 0; count < 10; count++)); do date; sleep 1s; done"
            ],
            estimated_duration = 13, parallel = True,
        ),
        image_timesout = ttbl.images.flash_shell_cmd_c(
            cmdline = [
                "/usr/bin/bash",
                "-c",
                "for ((count = 0; count < 10; count++)); do date; sleep 1s; done"
            ],
            # will always timeout
            estimated_duration = 5,
        ),
    ))
