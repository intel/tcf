#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import ttbl.pc
import ttbl.tt

class thing_c(ttbl.test_target):
    pass

class thing_plugger_c(ttbl.thing_plugger_mixin):
    def __init__(self, _name):
        ttbl.thing_plugger_mixin.__init__(self)

    @staticmethod
    def plug(target, thing):
        target.log.debug("thing %s plugged to %s", thing.id, target.id)

    @staticmethod
    def unplug(target, thing):
        target.log.debug("thing %s unplugged from %s", thing.id, target.id)

ttbl.config.target_add(thing_c('thing1'))
ttbl.config.target_add(thing_c('thing2'))
ttbl.config.target_add(thing_c('thing3'))

class tt_thing(ttbl.test_target):

    def __init__(self, name):
        ttbl.test_target.__init__(self, name)

    def thing_plug_do(self, thing):
        pass

    def thing_unplug_do(self, thing):
        pass


ttbl.config.target_add(
    tt_thing("t0"),
    tags = {
        'bsp_models': {
            'bsp1': None,
        },
        'bsps' : {
            "bsp1": dict(val = 1),
        },
        'things' : dict(
            thing1 = ("method1", ),
            thing2 = ("method2", 1),
            thing3 = ("method3", 2, 3)
        ),
        'skip_cleanup' : True,
    }
)

ttbl.test_target.get('t0').thing_add('thing1', thing_plugger_c('p1'))
ttbl.test_target.get('t0').thing_add('thing2', thing_plugger_c('p2'))
ttbl.test_target.get('t0').thing_add('thing3', thing_plugger_c('p3'))
