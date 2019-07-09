#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import sys
import unittest

from tcfl import commonl.testing
import tcfl
import tcfl.tc

srcdir = os.path.dirname(__file__)

ttbd = commonl.testing.test_ttbd(config_files = [
    os.path.join(srcdir, "conf_thing.py") ])

@tcfl.tc.target(ttbd.url_spec + " and id == 'thing1'", name = "thing1")
@tcfl.tc.target(ttbd.url_spec + " and id == 'thing2'", name = "thing2")
@tcfl.tc.target(ttbd.url_spec + " and id == 'thing3'", name = "thing3")
@tcfl.tc.target(ttbd.url_spec + " and id == 't0'")
class _test_00(tcfl.tc.tc_c):
    """
    Exercise the basic thing methods
    """
    @staticmethod
    def eval(target):
        things = target.thing_list()
        assert all(state == False for state in list(things.values())), \
            "initial thing list shall be all unplugged (got %s)" % things

        try:
            target.thing_plug("unexistant thing")
        except Exception as e:
            if not 'unexistant thing: unknown thing' in e.message:
                raise

        target.thing_plug("thing1")
        things = target.thing_list()
        assert things == dict(thing1 = True, thing2 = False, thing3 = False), \
            "thing list after plugging thing1 is not just " \
            "thing1 but %s" % things

        target.thing_unplug("thing1")
        things = target.thing_list()
        assert things == dict(thing1 = False, thing2 = False, thing3 = False), \
            "thing list after unplugging thing1 is " \
            "not all unplugged but %s" % things

        target.thing_plug("thing1")
        target.thing_plug("thing2")
        things = target.thing_list()
        assert things == dict(thing1 = True, thing2 = True, thing3 = False), \
            "list of connected things does not contain " \
            "things 1 & 2: %s" % things

        target.thing_plug("thing3")
        things = target.thing_list()
        assert things == dict(thing1 = True, thing2 = True, thing3 = True), \
            "list of connected things does not contain " \
            "things 1, 2 & 3: %s" % things

        target.thing_unplug("thing2")
        things = target.thing_list()
        assert things == dict(thing1 = True, thing2 = False, thing3 = True), \
            "list of connected things after removal does not contain " \
            "things 1, 3: %s" % things

        target.thing_unplug("thing3")
        things = target.thing_list()
        assert things == dict(thing1 = True, thing2 = False, thing3 = False), \
            "list of connected things after removal does not contain " \
            "things 1: %s" % things

        target.thing_unplug("thing1")
        things = target.thing_list()
        assert things == dict(thing1 = False, thing2 = False,
                              thing3 = False), \
            "list of connected things after removal is " \
            "not empty: %s" % things

    @classmethod
    def class_teardown(cls):
        ttbd.errors_ignore.append("IndexError: unexistant thing: "
                                  "unknown thing, can't plug")
        ttbd.errors_ignore.append("raise IndexError")
        assert cls.class_result == tcfl.tc.result_c(1, 0, 0, 0, 0), \
            "%s: expected 1 testcase passed, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)
