#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl

class tt_db(ttbl.test_target, ttbl.test_target_images_mixin):
    def __init__(self, id):
        tags = {
            'bsps': {
                'x86': dict(zephyr_board = 'qemu_x86',
                            zephyr_kernelname = 'zephyr.elf',
                            board = 'qemu_x86',
                            kernelname = 'zephyr.elf',
                            console = 'x86'),
            },
            'bsp_models': { 'x86' : None },
        }

        ttbl.test_target.__init__(self, id, _tags = tags)
        ttbl.test_target_images_mixin.__init__(self)

    def image_do_set(self, image_type, image_name):
        raise RuntimeError("Failing on purpose")

    def images_do_set(self, images):
        raise RuntimeError("Failing on purpose")

ttbl.config.target_add(tt_db("t0"))
