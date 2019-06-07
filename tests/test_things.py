#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import unittest

import requests

import commonl.testing
import tcfl.tc
import ttbl.fsdb

srcdir = os.path.dirname(__file__)

ttbd = commonl.testing.test_ttbd(config_files = [
    os.path.join(srcdir, "conf_test_things.py") ])

# use targe3 and not 1 and 2, because next text is going to be
# releasing them half way and we don't want this guy to get it by
# mistake
@tcfl.tc.target(ttbd.url_spec + " and id == 'target3'")
class _01(tcfl.tc.tc_c, unittest.TestCase):

    def eval_(self, target):
        # Shall not be able to plug something we don't own
        with self.assertRaisesRegex(requests.HTTPError,
                                     "400: thing1: tried to use "
                                     "non-acquired target"):
            target.thing_plug('thing1')

    @staticmethod
    def clean():
        ttbd.check_log_for_issues()

@tcfl.tc.target(ttbd.url_spec + " and id == 'thing2'", name = 'thing2')
@tcfl.tc.target(ttbd.url_spec + " and id == 'thing1'", name = 'thing1')
@tcfl.tc.target(ttbd.url_spec + " and id == 'target'")
class _02(tcfl.tc.tc_c, unittest.TestCase):

    def setup(self):
        self.exception_to_result[AssertionError] = tcfl.tc.failed_e

    def eval_01(self, target, thing1):
        # server's state for target
        fsdb_target = ttbl.fsdb.fsdb(os.path.join(ttbd.state_dir, target.id))

        things = target.thing_list()
        self.assertTrue(all([ things[thing] == False for thing in things ]),
                        "all things are not unplugged upon acquisition")

        # if we own the target and the thing, we can plug it
        target.thing_plug(thing1)
        # verify the server records the state
        self.assertEqual(fsdb_target.get("thing-" +  thing1.id), 'True')
        # and the API call confirms
        things = target.thing_list()
        self.assertTrue(things[thing1.id],
                        "thing reports unplugged after plugging it")

        target.thing_unplug(thing1)
        # the server's state information will drop it
        self.assertTrue(fsdb_target.get("thing-" +  thing1.id) == None)
        # and the API will reflect it
        things = target.thing_list()
        self.assertFalse(things[thing1.id],
                         msg = "thing reports unplugged after plugging it")

    def eval_02_thing_released_upon_release(self, target, thing1):
        # server's state for target
        fsdb_target = ttbl.fsdb.fsdb(os.path.join(ttbd.state_dir, target.id))

        target.thing_plug(thing1)
        things = target.thing_list()
        self.assertTrue(things[thing1.id], "thing1 is not plugged; it should")

        # when we release the thing, it becomes unplugged
        thing1.release()
        # verify the server did it
        self.assertTrue(fsdb_target.get("thing-" +  thing1.id) == None)
        # and API confirms the server did it
        things = target.thing_list()
        self.assertFalse(things[thing1.id],
                         "thing not unplugged after releasing it")

    def eval_03(self, target, thing2):
        target.release()
        target.acquire()
        things = target.thing_list()
        self.assertFalse(things[thing2.id],
                         "thing2 not unplugged after releasing the target")

    @staticmethod
    def clean():
        ttbd.check_log_for_issues()
