#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


import os
import errno
import time

import ttbl

class mutex_symlink(ttbl.acquirer_c):
    """
    The lamest file-system based mutex ever

    This is a rentrant mutex implemented using symlinks (an atomic
    operation under POSIX).

    To create it, declare the location where it will be and a string
    the *owner*. Then you can acquire() or release() it. If it is
    already acquired, it can spin busy wait on it (if given a timeout)
    or just fail. You can only release if you own it.

    Why like this? We'll have multiple processes doing this on behalf
    of remote clients (so it makes no sense to track owner by PID. The
    caller decides who gets to override and all APIs agree to use it
    (as it is advisory).

    .. warning:: The reentrancy of the lock assumes that the owner
      will use a single thread of execution to operate under it.

      Thus, the following scenario would fail and cause a race
      condition:

        - Thread A: acquires as owner-A
        - Thread B: starts to acquire as owner-A
        - Thread A: releases as owner-A (now released)
        - Thread B: verifies it was acquired by owner-A so passes as
          acquired
        - Thread B: MISTAKENLY assumes it owns the mutex when it is
          released in reality

      So use a different owner for each thread of execution.

    """

    def __init__(self, target, timeout = 3, wait_period = 0.5):
        assert timeout > 0
        assert wait_period > 0
        ttbl.acquirer_c.__init__(self, target)
        self.target = target
        self.location = os.path.join(target.state_dir, "mutex")
        self.timeout = timeout
        self.wait_period = wait_period


    def acquire(self, who, force):
        """
        Acquire the mutex, blocking until acquired

        :returns bool: True if we acquired, False if we were already
          the owners
        """
        # loop to acquire
        # FIXME: make the symlink target so that it can be opened as a
        # file exclusive while manipulation happens?
        # How to tell it is the same?
        # Check if we have it already -- see the warning in the class
        # header about this.
        current_owner = self.get()
        if current_owner != None and current_owner == who:
            return False
        t0 = time.time()
        while True:
            try:
                t = time.time()
                os.symlink(who, self.location)
                return True
            except OSError as e:
                if e.errno == errno.EEXIST:
                    if self.timeout == None:
                        raise self.busy_e(self)
                    if t - t0 > timeout:
                        raise self.timeout_e(self)
                    time.sleep(self.wait_period)
                else:
                    raise

    def release(self, who, force):
        if force:
            try:
                os.unlink(self.location)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    pass
                raise
            return
        try:
            link_dest = os.readlink(self.location)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise self.cant_release_not_acquired_e(self)
        # Here is the thinking: if you have a right to release this
        # mutex is because you own it; thus, it won't change since the
        # time we read its target until you get to unlock it by
        # removing the file. Yeah, some other process could have come
        # in the middle and removed it and then we are done. Window
        # for race condition
        # I'd rather have an atomic 'unlink if target matches...'
        if link_dest != who:
            raise self.cant_release_not_owner_e(self)
        os.unlink(self.location)


    def get(self):
        try:
            return os.readlink(self.location)
        except OSError as e:
            if e.errno == errno.ENOENT:
                return None
            raise


if __name__ == "__main__":
    import tempfile
    import unittest

    class _test_mutex(unittest.TestCase):
        longMessage = True

        @classmethod
        def setUp(cls):
            tmpdir = tempfile.mkdtemp()
            location = os.path.join(tmpdir, "amutex")
            try:
                os.unlink(location)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise e
            cls.mutex11 = mutex_symlink(location, "user11")
            cls.mutex11b = mutex_symlink(location, "user11")
            cls.mutex12 = mutex_symlink(location, "user12")
            cls.mutex21 = mutex_symlink(location, "user21")
            cls.mutex22 = mutex_symlink(location, "user22")

        @classmethod
        def tearDownClass(cls):
            pass

        def test_1(self):
            cls = type(self)
            cls.mutex11.acquire()
            cls.mutex11.release()
            with self.assertRaises(OSError):
                os.stat(cls.mutex11.location)

        def test_2(self):
            cls = type(self)
            cls.mutex11.acquire()
            with self.assertRaises(mutex_symlink.busy_e):
                cls.mutex12.acquire()
            cls.mutex11.release()

        def test_3(self):
            cls = type(self)
            cls.mutex11.acquire()
            with self.assertRaises(mutex_symlink.cant_release_not_owner_e):
                cls.mutex12.release()
            cls.mutex11.release()

        def test_4(self):
            cls = type(self)
            t0 = time.time()
            cls.mutex11.acquire()
            with self.assertRaises(mutex_symlink.timeout_e):
                cls.mutex12.acquire(timeout = 5)
            t1 = time.time()
            self.assertAlmostEqual(t1 - t0, 5, delta = 1)
            cls.mutex11.release()

        def test_5(self):
            cls = type(self)
            with cls.mutex11:
                with self.assertRaises(mutex_symlink.busy_e):
                    cls.mutex12.acquire()

        def test_6(self):
            # Test reentrancy
            cls = type(self)
            cls.mutex11.acquire()
            cls.mutex11b.acquire()	# Should just work
            cls.mutex11.release()
            cls.mutex12.acquire()
            with self.assertRaises(mutex_symlink.busy_e):
                cls.mutex11b.acquire()
            cls.mutex12.release()

    unittest.main(failfast = True)
