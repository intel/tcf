#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.pc
import ttbl.tt

class tt_test_debug_impl(ttbl.tt_debug_impl):

    def debug_do_start(self, tt):
        tt.fsdb.set('state',  'started')

    def debug_do_info(self, tt):
        return tt.fsdb.get('state')

    def debug_do_reset(self, tt):
        tt.fsdb.set('state',  'reset')

    def debug_do_reset_halt(self, tt):
        tt.fsdb.set('state',  'reset_halt')

    def debug_do_resume(self, tt):
        tt.fsdb.set('state',  'resumed')

    def debug_do_halt(self, tt):
        tt.fsdb.set('state',  'halted')

    def debug_do_stop(self, tt):
        tt.fsdb.set('state', 'stopped')

    def debug_do_openocd(self, tt, command):
        tt.fsdb.set('state', command)

class tt_debug(
        ttbl.test_target,
        ttbl.tt_debug_mixin):

    def __init__(self, name, debug_impl):
        ttbl.test_target.__init__(self, name)
        ttbl.tt_debug_mixin.__init__(self, debug_impl)

ttbl.config.target_add(
    tt_debug("t0", tt_test_debug_impl()),
    tags = {
        'bsp_models': {
            'bsp1': None,
        },
        'bsps' : {
            "bsp1": dict(val = 1),
        },
        'skip_cleanup' : True,
    }
)
