#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.power

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "power", ttbl.power.interface(
        (
            "release buttons",
            ttbl.power.buttons_released_pc("power", "reset")
        ),
        (
            "AC",			# fake AC power
            ttbl.power.fake_c()
        ),
        (
            "power button",
            ttbl.power.button_sequence_pc(
                sequence_on = [
                    # click power five seconds to power on
                    ( 'press', 'power' ),		# press the button
                    ( 'wait', 5 ),			# hold pressed 1 sec
                    ( 'release', 'power' ),		# release the button
                ],
                sequence_off = [
                    # click power 10 second to power off
                    ( 'press', 'power' ),		# press the button
                    ( 'wait', 10 ),			# hold pressed 10 sec
                    ( 'release', 'power' ),		# release the button
                    ( 'release', 'reset' ),		# release reset too
                ],
            )
        ),
    )
)
target.interface_add(
    "buttons", ttbl.power.interface(
        power = ttbl.power.fake_c(),
        reset = ttbl.power.fake_c()
    )
)
