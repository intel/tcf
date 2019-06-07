#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import logging
import os
import signal
import sys
import tempfile
import time
import unittest

from . import __init__
import testing

class _test_subpython(unittest.TestCase):

    def test_succeed(self):
        sp = __init__.subpython("true")
        # give it some time to start and finish
        while not sp.started():
            time.sleep(1)
        r = sp.join()
        self.assertEqual(r, 0, "%d != 0\noutput:\n%s" % (r, sp.output()))

    def test_fail(self):
        sp = __init__.subpython("false")
        while sp.p.pid == None:
            time.sleep(1)
        self.assertNotEqual(sp.join(), 0)

    def test_terminate(self):
        sp = __init__.subpython("while true; do sleep 10m; done")
        while not sp.started():
            time.sleep(1)
        sp.terminate_if_alive()
        self.assertEqual(sp.join(), -signal.SIGTERM)

    def test_stdin(self):
        # we use tee because as soon as @filename is created, we
        # know the process is ready to rock
        tfile = tempfile.NamedTemporaryFile(prefix = testing.mkprefix(""))
        filename = tfile.name
        sp = __init__.subpython("tee %s" % filename)
        while not os.path.isfile(filename):
            time.sleep(1)
        sp.stdin_write("test string\n")
        # Let the child run
        while len(sp.stdout_lines) < 1:
            time.sleep(1)
            sp.output()

        sp.output()
        self.assertEqual(sp.stdout_lines, [ 'test string\n' ])

        # do it again
        sp.stdin_write("test string2\n")
        # Let the child run
        while len(sp.stdout_lines) < 2:
            time.sleep(1)
            sp.output()
        sp.terminate_if_alive()
        sp.join()
        sp.output()
        self.assertEqual(sp.stdout_lines,
                         [ 'test string\n', 'test string2\n'])

if __name__ == '__main__':
    testing.logging_init(sys.argv)
    unittest.main()
