#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl

class tt_serial(ttbl.test_target, ttbl.test_target_console_mixin):
    def __init__(self, id, consoles):
        assert isinstance(consoles, list)
        ttbl.test_target.__init__(self, id)
        ttbl.test_target_console_mixin.__init__(self)
        self.consoles = consoles

    # Ok, this is a hack--we are storing any string in the FSDB
    def console_do_read(self, console_id, offset = 0):
        return iter(self.fsdb.get("console-" + console_id))

    def console_do_write(self, data, console_id):
        self.fsdb.set("console-" + console_id, data)

    def console_do_setup(self, console_id, **kwargs):
        raise NotImplementedError

    def console_do_list(self):
        return self.consoles


ttbl.config.target_add(tt_serial("t0", ['c1', 'c2', 'c3', 'c4']))
