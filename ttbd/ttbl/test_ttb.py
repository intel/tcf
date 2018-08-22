#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import shutil
import sys
import tempfile
import unittest

import __main__

import testing
import ttbl
import user_control

# Yeah, ugly hack -- FIXME pending a better solution
__main__.log_format = "%(levelname)s %(module)s.%(funcName)s():%(lineno)d: %(message)s"

class _test_target(unittest.TestCase):

    def tearDown(self):
        shutil.rmtree(user_control.User.state_dir)

    def setUp(self):
        prefix = testing.mkprefix("", type(self))
        user_control.User.state_dir = tempfile.mkdtemp(prefix = prefix)
        self.user1 = user_control.User("user1")
        self.user2 = user_control.User("user2")
        self.usernil = user_control.User("usernil")

    def test_acquire__bad_args(self):
        target = ttbl.test_target("a")
        with self.assertRaises(TypeError):
            target.acquire()	# pylint: disable = no-value-for-parameter
        with self.assertRaises(TypeError):
            target.acquire(None)
        with self.assertRaises(TypeError):
            target.acquire(3)
        with self.assertRaises(TypeError):
            target.acquire("a", 3) # pylint: disable = too-many-function-args
        with self.assertRaises(TypeError):
            target.release()	# pylint: disable = no-value-for-parameter
        with self.assertRaises(TypeError):
            target.release(None)
        with self.assertRaises(TypeError):
            target.release(3)
        with self.assertRaises(TypeError):
            target.release("a", 3) # pylint: disable = too-many-function-args

    def test_acquire__good(self):
        target = ttbl.test_target("d")
        who = self.user1
        target.acquire(who)
        self.assertEqual(who, target.owner_get())
        target.release(who)

    def test_acquire__busy(self):
        t = ttbl.test_target("a")
        t.acquire(self.user1)
        with self.assertRaises(ttbl.test_target_busy_e):
            t.acquire(self.user2)


    def test_release__bad_args(self):
        t = ttbl.test_target("a")
        with self.assertRaises(ttbl.test_target_not_acquired_e):
            t.release(self.usernil)
        t.acquire(self.user1)
        t.release(self.user1)
        with self.assertRaises(ttbl.test_target_not_acquired_e):
            t.release(self.user1)

    def test_release_force(self):
        t = ttbl.test_target("a")
        t.acquire(self.user1)
        t.release(self.user1, force = True)
        # This has to work now
        t.acquire(self.user2)
        t.release(self.user2)

if __name__ == '__main__':
    testing.logging_init(sys.argv)
    unittest.main()
