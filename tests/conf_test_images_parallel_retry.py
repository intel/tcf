#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.images

class _fails_on(ttbl.images.flash_shell_cmd_c):
    # flasher that fails on the Nth time
    def __init__(self, fails_before, *args, **kwargs):
        self.fails_before = fails_before
        ttbl.images.flash_shell_cmd_c.__init__(
            self, *args, **kwargs)
        self.retry = 0

    def flash_start(self, target, images, context):
        image_names = ",".join(images.keys())
        self.retry += 1
        ttbl.images.flash_shell_cmd_c.flash_start(self, target, images, context)

    def flash_post_check(self, target, images, context):
        image_names = ",".join(images.keys())

        if self.retry < self.fails_before:
            msg = "flash/%s: triggering failure at #%d; sleeping 2s" % (
                image_names, self.retry)
            logging.error(msg)
            time.sleep(2)
            return { "msg": msg }
        # good
        logging.info("flash/%s: not triggering failure at #%d",
                     image_names, self.retry)
        return

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "images", ttbl.images.interface(
        image0 = _fails_on(
            fails_before = 0,
            cmdline = [
                "/usr/bin/bash",
                "-c",
                "sleep 5s"
            ],
            parallel = True,
            retries = 3,
            estimated_duration = 30,
        ),
        image2 = _fails_on(
            fails_before = 2,
            cmdline = [
                "/usr/bin/bash",
                "-c",
                "sleep 5s"
            ],
            parallel = True,
            retries = 3,
            estimated_duration = 30,
        ),
    ))
