#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import filecmp
import hashlib
import logging
import os
import random
import re
import sys
import tempfile
import unittest

import commonl
import commonl.testing

_src = os.path.abspath(__file__)
_srcdir = os.path.dirname(_src)

class _test_tcf(unittest.TestCase, commonl.testing.test_ttbd_mixin):
    longMessage = True

    @classmethod
    def setUpClass(cls):
        cls.srcdir = os.path.join(_srcdir, "..")
        commonl.testing.test_ttbd_mixin.setUpClass(cls.configfile())

    @classmethod
    def tearDownClass(cls):
        commonl.testing.test_ttbd_mixin.tearDownClass()

    target_no = 10

    @classmethod
    def configfile(cls):
        c = """\

"""
        cls.target_names = []
        for _target in range(cls.target_no):
            target_name = "target-%04x" % random.randrange(65535)
            cls.target_names.append(target_name)
            c = c + "ttbl.config.target_add(ttbl.test_target('%s'))\n" % target_name
        return c

    def test_no_command(self):
        sp = commonl.subpython(self.srcdir + "/tcf")
        r = sp.join()
        self.assertNotEqual(r, 0, msg = sp.output_str)

    def test_target_list(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s list" % self.url)
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())
        for target_name in self.target_names:
            self.assertRegex(
                "".join(sp.stdout_lines), re.compile(target_name),
                msg = "exit: target_name '%s' not found\n" % target_name \
                + sp.output_str + type(self).ttbd_info())

    def test_config_file_bad_url(self):
        """
        Access the URL by configuration
        """
        config = tempfile.NamedTemporaryFile(
            prefix = commonl.testing.mkprefix("tcf-config", cls = type(self)),
            suffix = ".py", delete = True)
        config.write("""\
tcfl.config.url_add("bad/.url_343flimy")
""")
        config.flush()
        config.seek(0)
        sp = commonl.subpython(
            self.srcdir +
            "/tcf --config-path : -vvv --config-path '' --config-file %s list"
            % config.name)
        r = sp.join()
        self.assertEqual(
            r, 1,
            msg = sp.output_str \
            + "tcf-config: ".join(["\n"] + config.readlines()) \
            + type(self).ttbd_info())

    def test_config_bad_url(self):
        """
        Access the URL by configuration
        """

        sp = commonl.subpython(
            self.srcdir
            + "/tcf --config-path : -vvv --url 'bad/.url_343flimy' list")
        r = sp.join()
        self.assertNotEqual(r, 0, msg = sp.output_str)

    def test_config_file_target_list(self):
        """
        Access the URL by configuration
        """
        config = tempfile.NamedTemporaryFile(
            prefix = commonl.testing.mkprefix("tcf-config", cls = type(self)),
            suffix = ".py", delete = True)
        config.write("""\
tcfl.config.url_add("%s")
""" \
                     % self.url)
        config.flush()
        config.seek(0)
        sp = commonl.subpython(
            self.srcdir +
            "/tcf --config-path : -vvv --config-path '' --config-file %s list"
            % config.name)
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str \
            + "tcf-config: ".join(["\n"] + config.readlines()) \
            + type(self).ttbd_info())

        for target_name in self.target_names:
            self.assertRegex(
                "".join(sp.stdout_lines), re.compile(target_name),
                msg = "exit: target_name '%s' not found\n" % target_name \
                + sp.output_str \
                + "tcf-config: ".join(["\n"] + config.readlines()) \
                + type(self).ttbd_info())

    def test_target_acquire_nonexistant(self):
        sp = commonl.subpython(
            self.srcdir +
            "/tcf --config-path : -vvv --url %s acquire non_existant"
            % self.url)
        sp.join()
        self.assertRegex(
            sp.output_str,
            "IndexError: target-id 'non_existant': not found$",
            msg = "IndexError not raised by tcf\n" \
            + sp.output_str + type(self).ttbd_info())

    def test_target_acquire(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s acquire %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

    def test_target_acquire_twice(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s acquire %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s acquire %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

    def test_target_release(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s acquire %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s release %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

    def test_target_release_twice(self):
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s acquire %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s release %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : -vvv --url %s release %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 1,
            msg = sp.output_str + type(self).ttbd_info())

    def test_broker_file_upload__bad_params(self):
        sp = commonl.subpython(
            self.srcdir +
            "/tcf --config-path : -vvv --url %s broker-file-upload"
            % (self.url))
        r = sp.join()
        self.assertNotEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

        sp = commonl.subpython(
            self.srcdir +
            "/tcf --config-path : -vvv --url %s broker-file-upload %s"
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertNotEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

        sp = commonl.subpython(
            self.srcdir +
            "/tcf --config-path : -vvv --url %s broker-file-upload %s /dest/path/file"
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertNotEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())

    def test_broker_file_upload__simple(self):
        filename = self.ttbd_config.name
        sp = commonl.subpython(
            self.srcdir +
            "/tcf --config-path : -vvv --url %s broker-file-upload %s  dest/file %s"
            % (self.url, self.target_names[0], filename))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())
        # Check the file made it to the daemon's file storage (it's in
        # localhost, so we know it is there)
        expected_filename = os.path.normpath("%s/local/dest/file" % (
            self.ttbd_files_dir))
        logging.debug("expected_filename %s", expected_filename)
        if not os.path.isfile(expected_filename):
            self.fail("expected file '%s' not found\n" % expected_filename \
                      + sp.output_str + type(self).ttbd_info())
        if not filecmp.cmp(expected_filename, filename):
            self.fail("uploaded file and original file are different")

        # Check we can list it and it matches the hash
        sp = commonl.subpython(
            self.srcdir + "/tcf --config-path : --url %s broker-file-list %s" \
            % (self.url, self.target_names[0]))
        r = sp.join()
        self.assertEqual(
            r, 0,
            msg = sp.output_str + type(self).ttbd_info())
        for line in sp.stdout_lines:
            listed_filename, hexdigest = line.split(" ", 1)
            if '/dest/file' ==  listed_filename:
                self.assertEqual(
                    hexdigest,
                    commonl.hash_file(hashlib.sha256(),
                                      self.ttbd_config.name).hexdigest())
            # we ignore the rest of the file from other test cases

if __name__ == "__main__":
    commonl.testing.logging_init(sys.argv)
    unittest.main()
