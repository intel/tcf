#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl.pc
import ttbl.tt

class tt_test_power_control_impl(ttbl.tt_power_control_impl):

    def power_on_do(self, target):
        target.fsdb.set('power_state', 'on')

    def reset_do(self, target):
        target.fsdb.set('power_state', 'on')

    def power_off_do(self, target):
        target.fsdb.set('power_state', 'off')

    @staticmethod
    def power_cycle_do(target, wait = 0):
        target.fsdb.set('power_state', 'on')

    def power_get_do(self, target):
        r = target.fsdb.get('power_state')
        if r == None:
            # First run, we assume it's off
            return False
        elif r == 'on':
            return True
        elif r == 'off':
            return False
        else:
            raise AssertionError("r is %s" % r)

ttbl.config.target_add(
    ttbl.tt.tt_power("t0", tt_test_power_control_impl()),
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
