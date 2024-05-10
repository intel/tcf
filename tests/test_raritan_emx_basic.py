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
#import ttbl
import ttbl.raritan_emx


class _test(tcfl.tc.tc_c, unittest.TestCase):

    @tcfl.tc.subcase()
    def eval_10_fail_with_no_arguments(self):
        with self.assertRaises(TypeError):
            ttbl.raritan_emx.pci()


    @tcfl.tc.subcase()
    def eval_101_fail_if_no_outlet_in_URL_nor_args(self):
        with self.assertRaisesRegex(
                AssertionError, "outlet_number: expected int*"):
            ttbl.raritan_emx.pci("hostname")


    @tcfl.tc.subcase()
    def eval_101_outlet_number_in_URL(self):
        pc = ttbl.raritan_emx.pci("hostname:30")
        url, _password, outlet_number = pc._url_resolve(pc.url_base, None)
        assert outlet_number == 29
        with self.subcase("scheme_added"):
            assert url.scheme


    @tcfl.tc.subcase()
    def eval_101_pass_if_outlet_in_args(self):
        pc = ttbl.raritan_emx.pci("hostname", outlet_number = 30)
        _url, _password, outlet_number = pc._url_resolve(pc.url_base, None)
        assert outlet_number == 29

    @tcfl.tc.subcase()
    def eval_102_common_use(self):
        pc = ttbl.raritan_emx.pci("https://username@hostname.domain",
                                  30, password = "somepassword")
        url, password, outlet_number = pc._url_resolve(pc.url_base, None)
        with self.subcase("outlet_number_matches"):
            assert outlet_number == 29
        with self.subcase("scheme_parsed"):
            assert url.scheme == "https"
        with self.subcase("username_matches"):
            assert url.username == "username"
        with self.subcase("password_matches"):
            assert password == "somepassword"
        with self.subcase("hostname_matches"):
            assert url.hostname == "hostname.domain"


    @tcfl.tc.subcase()
    def eval_103_password_file(self):
        # this we use in test_raritan_emx.py
        pc = ttbl.raritan_emx.pci(
            "username:@hostname.domain:30",
            password = f"FILE:{srcdir}/samplepasswordfile")
        url, password, outlet_number = pc._url_resolve(pc.url_base, None)
        with self.subcase("outlet_number_matches"):
            assert outlet_number == 29
        with self.subcase("scheme_parsed"):
            assert url.scheme == "https"
        with self.subcase("username_matches"):
            assert url.username == "username"
        with self.subcase("password_matches"), \
             open(f"{srcdir}/samplepasswordfile", "r") as f:
            password_expected = f.read()
            assert password == password_expected, \
                f"password: read '{password}', expected '{password_expected}'"
        with self.subcase("hostname_matches"):
            assert url.hostname == "hostname.domain"
