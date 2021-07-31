#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ttbl.images


maria = b"""
Doe, A Deer, A female Deer
Ray, A drop of golden sun
Me, a name, I call myself.
Far, A long long way to runnnnnnnnnnnnnnnnnn!
And etc.
"""

class driver(ttbl.images.impl_c):
    def flash_read(self,
                   target,
                   image,
                   file_name,
                   image_offset = 0,
                   read_bytes = None):


        with open(file_name, "wb") as f:
            if image_offset > len(maria):
                image_offset = len(maria)

            if read_bytes is None:
                read_bytes = len(maria) - image_offset

            f.write(maria[image_offset:image_offset+read_bytes])

        return dict()

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "images",
    ttbl.images.interface(image0 = driver()
    )
)
