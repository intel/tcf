#! /usr/bin/python3
#
# Copyright (c) 2017-24 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import sys
import unittest

import tcfl.tc


srcdir = os.path.realpath(os.path.dirname(__file__))
ttbd_dir = os.path.join(srcdir, "ttbd")
if not ttbd_dir in sys.path:
    # point to tcf.git/ttbd so we can import ttbl
    sys.path.append(ttbd_dir)

import ttbl.power
import ttbl.raritan_px


class _test(tcfl.tc.tc_c, unittest.TestCase):

    def configure_10(self):
        ttbl.test_target.state_path = os.path.join(self.tmpdir, "state")
        self.target = ttbl.test_target("t0")


    @tcfl.tc.subcase()
    def eval_10_fail_with_no_arguments(self):
        with self.assertRaises(TypeError):
            ttbl.raritan_px.pc()


    @tcfl.tc.subcase()
    def eval_101_fail_if_no_outlet(self):
        with self.assertRaisesRegex(
                ttbl.raritan_px.pc.exception, "missing :OUTLETNUMBER"):
            pc = ttbl.raritan_px.pc("hostname")
            pc._resolve(self.target)


    @tcfl.tc.subcase()
    def eval_101_fail_if_outlet_non_integer(self):
        with self.assertRaisesRegex(
                ttbl.raritan_px.pc.exception, "can't parse 'BADOUTLET' as an integer"):
            pc = ttbl.raritan_px.pc("hostname:BADOUTLET")
            pc._resolve(self.target)


    @tcfl.tc.subcase()
    def eval_102_common_use(self):
        pc = ttbl.raritan_px.pc("username:somepassword@hostname.domain:30")
        pc._resolve(self.target)
        with self.subcase("outlet_number_matches"):
            assert pc.outlet == 30
        with self.subcase("username_matches"):
            assert pc.user == "username"
        with self.subcase("password_matches"):
            assert pc.password == "somepassword"
        with self.subcase("hostname_matches"):
            assert pc.hostname == "hostname.domain"


    @tcfl.tc.subcase()
    def eval_103_password_file(self):
        # this we use in test_raritan_emx.py
        pc = ttbl.raritan_px.pc(
            f"username:FILE:{srcdir}/samplepasswordfile@hostname.domain:30")
        pc._resolve(self.target)
        with self.subcase("outlet_number_matches"):
            assert pc.outlet == 30
        with self.subcase("username_matches"):
            assert pc.user == "username"
        with self.subcase("password_matches"), \
             open(f"{srcdir}/samplepasswordfile", "r") as f:
            password_expected = f.read()
            assert pc.password == password_expected, \
                f"password: read '{pc.password}', expected '{password_expected}'"
        with self.subcase("hostname_matches"):
            assert pc.hostname == "hostname.domain"
