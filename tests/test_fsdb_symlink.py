#! /usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import urllib

import commonl
import ttbl
import tcfl.tc

class _test(tcfl.tc.tc_c):
    """
    Exercise the FSDB interface (:class:ttbl.fsdb_c) implemented by
    the symlink-based database :class:ttbl.fsdb_symlink_c.

    FIXME: split into pure FSDB functionality check, so we can apply
    it to any provider and symlink-specific (eg: looking for files)
    """

    def eval(self):

        fsdb_dir = os.path.join(self.tmpdir, "db")
        commonl.makedirs_p(fsdb_dir)
        fsdb = ttbl.fsdb_symlink_c(fsdb_dir)
        self.fsdb = fsdb

        l = os.listdir(fsdb_dir)
        if l:
            raise tcfl.tc.failed_e(
                "fsdb database directory not empty",
                dict(listdir = l))
            if False:
                self.subtc["fsdb database directory not empty"].update(
                    tcfl.tc.result_c(errors = 1),
                    "fsdb database directory not empty",
                    listdir = l)

        db = {
            "name ascii" : "string value",
            "name ascii" : "string value",
            # use weird names that would not be welcome in a file,
            # make sure they are encoded -- / and : catch both Win and
            # Linux platforms
            "name :/1" : "string value",
            "name :/2" : "string value",
            "name :/3" : "string value",
            "name :/4" : "string value",
            "name weird /:" : True,
            "name weird /: 2" : False,
            "name ñá %% int" : 2,
            "name ñá %% float" : 3.0
        }
        expected_len = 0
        for name, value in db.items():
            fsdb.set(name, value)
            self.report_pass("key name %s set" % name)
            expected_len += 1
            l = os.listdir(fsdb_dir)
            if len(l) != expected_len:
                raise tcfl.tc.failed_e(
                    "%s: number of files (%d) does not match records (%d)"
                    % (fsdb_dir, len(l), expected_len),
                    dict(listdir = l))
            self.report_pass("%s: number of files (%d) matches records (%d)"
                             % (fsdb_dir, len(l), expected_len))
        self.report_pass("we were able to create records, including"
                         " those with non-filename compatible")

        # verify the entries in the directory match what we have
        # tkae the list of files we created for each field, get an
        # unquoted list and compare against the list of keys we fed
        # and the lsit of keys FSDB reports.
        # Make it all a set() so they are ordered the same.
        l_raw = set(os.listdir(fsdb_dir))
        l_unquoted = set([ urllib.unquote(i) for i in l_raw ])
        keys_db = set(db.keys())
        keys_fsdb = set(fsdb.keys())
        if l_unquoted != keys_db:
            raise tcfl.tc.failed_e(
                "%s: files don't match files"
                % (fsdb_dir),
                dict(listdir_unquoted = l_unquoted,
                     listdir_raw = l_raw,
                     keys_fsdb = keys_fsdb,
                     keys_db = keys_db))

        if keys_fsdb != keys_db:
            raise tcfl.tc.failed_e(
                "%s: keys don't match DB keys"
                % (fsdb_dir),
                dict(listdir_unquoted = l_unquoted,
                     listdir_raw = l_raw,
                     keys_fsdb = keys_fsdb,
                     keys_db = keys_db))
        self.report_pass("keys() match files and db keys")

        for name, value in db.items():
            value_fsdb = fsdb.get(name)
            if value_fsdb != value:
                raise tcfl.tc.failed_e(
                    "%s: key '%s' value from fsdb '%s' does not match"
                    " what we set ('%s')" % (fsdb_dir, name, value, value_fsdb))
        self.report_pass("values set check")

        d = fsdb.get_as_dict()
        if d != db:
            raise tcfl.tc.failed_e(
                "%s: get_as_dict() doesn't match db" % (
                    fsdb_dir), dict(get_as_dict = d, db = db))
        self.report_pass("get_as_dict() returns same as db")

        l = fsdb.get_as_slist()
        for k, v in l:
            if k not in db:
                raise tcfl.tc.failed_e(
                    "%s: get_as_slist() reported field %s doesn't match db" % (
                        fsdb_dir, k), dict(get_as_slist = l, db = db))
            if db[k] != v:
                raise tcfl.tc.failed_e(
                    "%s: get_as_slist() reported field %s, value %s, doesn't match db" % (
                        fsdb_dir, k, v), dict(get_as_slist = l, db = db))
        self.report_pass("get_as_slist() returns same as db")


    def eval_10_test_patterns(self):

        patterned = sorted([
            "name :/1",
            "name :/2",
            "name :/3",
            "name :/4",
        ])
        keys_fsdb = sorted(self.fsdb.keys("name :/*"))
        if keys_fsdb != patterned:
            raise tcfl.tc.failed_e(
                "keys() w/ pattern doesn't match expected",
                dict(keys_fsdb = keys_fsdb, patterned = patterned))
        self.report_pass("keys(PATTERN) filters ok")

        patterned = sorted([
            "name :/1",
            "name :/2",
            "name :/3",
            "name :/4",

            "name weird /:",
            "name weird /: 2",
        ])
        keys_fsdb = sorted([
            i[0]
            for i in self.fsdb.get_as_slist("name :/*", "*name weird*")
        ])
        if keys_fsdb != patterned:
            raise tcfl.tc.failed_e(
                "get_as_slist() w/ pattern doesn't match expected",
                dict(keys_fsdb = keys_fsdb, patterned = patterned))
        self.report_pass("get_as_slist(PATTERN1, PATTERN2) filters ok")

        keys_fsdb = sorted([
            i
            for i in self.fsdb.get_as_dict("name :/*", "*name weird*")
        ])
        if keys_fsdb != patterned:
            raise tcfl.tc.failed_e(
                "get_as_slist() w/ pattern doesn't match expected",
                dict(keys_fsdb = keys_fsdb, patterned = patterned))
        self.report_pass("get_as_dict(PATTERN1, PATTERN2) filters ok")

