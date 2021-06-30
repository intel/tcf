#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import ttbl
import ttbl.config

raise ImportError("bitrotten")

class example_target(ttbl.test_target):
    pass

class example_thing(ttbl.test_target):
    pass

class example_thing_plugger(ttbl.thing_plugger_mixin):
    def __init__(self, _name):
        ttbl.thing_plugger_mixin.__init__(self)

    @staticmethod
    def plug(target, thing):
        target.log.debug("thing %s plugged to %s", thing.id, target.id)

    @staticmethod
    def unplug(target, thing):
        target.log.debug("thing %s unplugged from %s", thing.id, target.id)

def example_target_add(name):
    ttbl.config.target_add(example_thing(name))

example_target_add('target')

ttbl.config.target_add(example_thing('thing1'))
ttbl.config.target_add(example_thing('thing2'))
ttbl.config.target_add(example_thing('thing3'))

ttbl.test_target.get('target').thing_add('thing1', example_thing_plugger('p1'))
ttbl.test_target.get('target').thing_add('thing2', example_thing_plugger('p2'))
ttbl.test_target.get('target').thing_add('thing3', example_thing_plugger('p3'))
