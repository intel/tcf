#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import errno
import fnmatch
import os
import shutil
import time
import uuid

class fsdb(object):
    """This is a veeeery simple file-system based 'DB', atomic access

    - Atomic access is implemented by storing values in the target of
      symlinks
    - the data stored is strings
    - the amount of data stored is thus limited (to 1k in OSX, 4k in
      Linux/ext3, maybe others dep on the FS).

    Why? Because to create a symlink, there is only a system call
    needed and is atomic. Same to read it. Thus, for small values, it
    is very efficient.
    """
    class exception(Exception):
        pass

    # A UUID for this process
    uuid_ns = uuid.uuid4()

    def __init__(self, location):
        """
        Initialize the database to be saved in the give location
        directory

        :param str location: Directory where the database will be kept
        """
        self.location = location
        assert os.path.isdir(location) \
            and os.access(location, os.R_OK | os.W_OK | os.X_OK)

    def keys(self, pattern = None):
        """
        List the fields/keys available in the database

        :param str pattern: (optional) pattern against the key names
          must match, in the style of :mod:`fnmatch`. By default, all
          keys are listed.
        """
        l = []
        for _rootname, _dirnames, filenames in os.walk(self.location):
            if pattern:
                filenames = fnmatch.filter(filenames, pattern)
            for filename in filenames:
                if os.path.islink(os.path.join(self.location, filename)):
                    l.append(filename)
        return l

    def set(self, field, value):
        """
        Set a field in the database

        :param str field: name of the field to set
        :param str value: value to stored; None to remove that field
        """
        if value != None:
            assert isinstance(value, str)
            assert len(value) < 1023
        location = os.path.join(self.location, field)
        if value == None:
            try:
                os.unlink(location)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    pass
                else:
                    raise
        else:
            # New location, add a unique thing to it so there is no
            # collision if more than one process is trying to modify
            # at the same time; they can override each other, that's
            # ok--the last one wins.
            location_new = \
            	location + "-%s" % uuid.uuid5(self.uuid_ns, "%f" % time.time())
            os.symlink(value, location_new)
            os.rename(location_new, location)

    def get(self, field, default = None):
        location = os.path.join(self.location, field)
        try:
            return os.readlink(location)
        except OSError as e:
            if e.errno == errno.ENOENT:
                return default
            raise


if __name__ == "__main__":
    import tempfile
    import unittest

    class _test_fsdb(unittest.TestCase):
        longMessage = True

        @classmethod
        def setUp(cls):
            cls.tmpdir = tempfile.mkdtemp()
            cls.location = os.path.join(cls.tmpdir, "fs1")

        @classmethod
        def tearDownClass(cls):
            shutil.rmtree(cls.tmpdir)

        def test_1(self):
            cls = type(self)
            with self.assertRaises(AssertionError):
                fsdb(os.path.join(cls.tmpdir, "unexistant"))
            fsdb(cls.tmpdir)

        def test_2(self):
            cls = type(self)
            location = os.path.join(cls.tmpdir, "test_2")
            os.makedirs(location)
            print("LOCATION ", location)
            f1 = fsdb(location)
            f2 = fsdb(location)
            f1.set("field1", "value1")
            f1.get("field1")

            self.assertEqual(f1.get("field1"), "value1")
            self.assertEqual(f2.get("field1"), "value1")

        def test_3(self):
            cls = type(self)
            location = os.path.join(cls.tmpdir, "test_3")
            os.makedirs(location)

            f1 = fsdb(location)
            self.assertIsNone(f1.get("field1"))
            f1.set("field1", "value1")
            self.assertEqual(f1.get("field1"), "value1")
            f1.set("field1", None)
            self.assertIsNone(f1.get("field1"))

    unittest.main(failfast = True)
