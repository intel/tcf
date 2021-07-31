#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(config_files = [
    # strip to remove the compiled/optimized version -> get source
    os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
])

@tcfl.tc.target(ttbd.url_spec + ' and t0')
class _test(tcfl.tc.tc_c):
    """
    Test we can download a file using offsets

    We first generate a file, upload it and then try to download it
    using different offsets, verifying the data matches.
    """
    def eval_00_upload(self, target):
        self.file_path = self.report_file_prefix + "original"
        self.file_name = os.path.basename(self.file_path)
        with open(self.file_name, "wb") as f:
            for count in range(1000):
                f.write(f"{count:04d}\n".encode('utf-8'))
        target.store.upload(self.file_name, self.file_path)

    def _eval_offset(self, target, offset):
        read_file = self.report_file_prefix + str(offset)
        target.store.dnload(self.file_name, read_file, offset = offset)

        with open(read_file, "rb") as rf, open(self.file_name, "rb") as of:
            # for offset from end to work, we need to open them in
            # binary mode, so byte conversions don't affect it.
            if offset == None or offset == 0:
                pass
            elif offset > 0:
                of.seek(offset)
            elif offset < 0:
                of.seek(offset, os.SEEK_END)
            # we don't seek the read-file, since that has the offset already :)
            read_data = rf.read()
            original_data = of.read()
            if read_data != original_data:
                target.report_fail(
                    f"{offset}: read data and original data mismatch",
                    dict(read_data = read_data, original_data = original_data,
                         offset = offset)
                )

    @tcfl.tc.subcase()
    def eval_10_dnload(self, target):
        for offset in [
                None,
                0, 10, 100, 1000, 3000, 4000, 5000,
                -10, -100, -1000, -3000, -4000, -5000,
        ]:
            with self.subcase(str(offset)):
                self._eval_offset(target, offset)
