#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.debug

class debug_loopback_c(ttbl.debug.impl_c):

    def debug_list(self, target, component):
        state = target.fsdb.get('debug_state', None)
        if state == None or state == 'stopped':
            return None
        return {
            'state': target.fsdb.get('debug_state')
        }

    def debug_start(self, target, components):
        target.fsdb.set('debug_state',  'started')

    def debug_stop(self, target, components):
        target.fsdb.set('debug_state',  'stopped')

    def debug_halt(self, target, components):
        target.fsdb.set('debug_state',  'halted')

    def debug_resume(self, target, components):
        target.fsdb.set('debug_state',  'resumed')

    def debug_reset(self, target, components):
        target.fsdb.set('debug_state',  'reset')

    def debug_reset_halt(self, target, components):
        target.fsdb.set('debug_state',  'reset_halted')


target = ttbl.test_target("t0")
ttbl.config.target_add(
    target,
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

target.interface_add("debug",
                     ttbl.debug.interface(debug0 = debug_loopback_c()))
