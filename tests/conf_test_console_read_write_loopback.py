#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl
import ttbl.console

class console_loopback_c(ttbl.console.generic_c):
    def enable(self, target, component):
        write_file_name = os.path.join(target.state_dir,
                                      "console-%s.write" % component)
        # ensure it exists
        with open(write_file_name, "w") as wf:
            wf.write("")

        # now symlink the read to the write file, so what we write is
        # read right away 
        os.symlink(
            write_file_name,
            os.path.join(target.state_dir, "console-%s.read" % component),
        )
    
        ttbl.console.generic_c.enable(self, target, component)

target = ttbl.test_target("t0")
ttbl.config.target_add(target)
console_loopback = console_loopback_c()
target.interface_add("console", ttbl.console.interface(
    c1 = console_loopback,
    c2 = console_loopback,
    c3 = console_loopback,
    c4 = console_loopback,
))
