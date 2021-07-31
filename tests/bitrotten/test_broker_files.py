#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

import filecmp
import requests

import tcfl
import tcfl.tc
import commonl.testing

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target(ttbd.url_spec)
#@tcfl.tc.target()
class _test_00(tcfl.tc.tc_c):
    """
    Test the debug methods can be run
    """

    def eval(self, target):
        uuid = target.kws['tc_hash']
        fn1 = uuid + "-remote1"
        fn2 = uuid + "-remote2"
        # Ensure the files do not exist in the broker, just in case
        target.broker_files.delete(fn1)
        target.broker_files.delete(fn2)
        # Upload a file
        target.broker_files.upload(fn1, __file__)
        # Download it and verify it is the same
        target.broker_files.dnload(fn1, self.tmpdir + "/" + fn1)
        if not filecmp.cmp(__file__, self.tmpdir + "/" + fn1, False):
            raise tcfl.tc.failed_e("downloaded file differs from "
                                   "original file")
        try:
            target.broker_files.dnload(fn2, self.tmpdir + "/" + fn1)
        except requests.HTTPError as e:
            if "can't download" not in e.message \
               and 'No such file or directory' not in e.message:
                raise
            self.report_pass("downloading missing file errors out as expected")
        # Overwrite it
        local_fn2 = os.path.join(self.tmpdir, fn2)
        with open(local_fn2, "w") as f:
            f.write("hello")
        target.broker_files.upload(fn1, local_fn2)
        # Download it and verify it is the same
        target.broker_files.dnload(fn1, local_fn2 + ".downloaded")
        if not filecmp.cmp(local_fn2, local_fn2 + ".downloaded", False):
            raise tcfl.tc.failed_e("downloaded file2 differs from "
                                   "original file")

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(1, 0, 0, 0, 0), \
            "%s: expected 1 testcase passed, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)
