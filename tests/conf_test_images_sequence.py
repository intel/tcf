#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.images
import ttbl.power

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "power", ttbl.power.interface(
        power0 = ttbl.power.fake_c(),
        power1 = ttbl.power.fake_c(),
        power2eb = ttbl.power.fake_c(explicit = 'both'),
        power3en = ttbl.power.fake_c(explicit = 'on'),
        power4ef = ttbl.power.fake_c(explicit = 'off'),
    )
)
target.interface_add(
    "images", ttbl.images.interface(
        image0 = ttbl.images.flash_shell_cmd_c(
            cmdline = [ "/usr/bin/sleep", "5", ],
            estimated_duration = 6,
            power_sequence_pre = [ ( 'off', 'full' ), ( 'on', 'power3en' ) ],
            power_sequence_post = [ ( 'on', 'power1' ) ],
        ),
        # for parallel flashers
        power_sequence_pre = [ ( 'off', 'full' ), ( 'on', 'power2eb' ) ],
        power_sequence_post = [ ( 'off', 'full', ), ( 'on', 'all' ) ],
        image_p0 = ttbl.images.flash_shell_cmd_c(
            cmdline = [ "/usr/bin/sleep", "5", ],
            estimated_duration = 6, parallel = True,
        ),
        image_p1 = ttbl.images.flash_shell_cmd_c(
            cmdline = [ "/usr/bin/sleep", "5", ],
            estimated_duration = 6, parallel = True,
        ),
    ))
