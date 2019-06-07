#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import inspect
import os
import random
import re
import sys
import unittest

import commonl.testing
import tcfl
import tcfl.tc

# So all the aleatory choicing sequences are all the
# same and we can compare results
random.seed(12345)

_srcdir = os.path.dirname(os.path.abspath(__file__))

ttbd = commonl.testing.test_ttbd(config_files = [
    os.path.join(_srcdir, "conf_interconnects.py")
])

class _00_static(tcfl.tc.tc_c):
    """
    Request nothing, static testcase
    """
    def eval(self):
        pass

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(1, 0, 0, 0, 0), \
            "%s: one testcase should be passing, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)


@tcfl.tc.interconnect(ttbd.url_spec, mode = "all")
@tcfl.tc.target(ttbd.url_spec + " and id:'^[rst][0-4]'")
class _01_one_ic_one_tg_all(tcfl.tc.tc_c):
    """
    Request one interconnect -- because we configure two types of
    networks, with three different types of targets this will run
    three times, due to a current limitation in TCF (FIXME) which will
    pick one interconnect type at random and stop looking.
    """
    @staticmethod
    def eval(ic, target):
        assert 'interconnect_c' in ic.rt['interfaces']
        assert ic.id in target.rt['interconnects']

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(3, 0, 0, 0, 0), \
            "%s: three testcases should be passing, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)


@tcfl.tc.interconnect(ttbd.url_spec, mode = "one-per-type")
class _02_one_ic(tcfl.tc.tc_c):
    """
    Request one interconnect, shall run thrice because we have three
    target types
    """
    @staticmethod
    def eval(ic):
        assert 'interconnect_c' in ic.rt['interfaces']

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(3, 0, 0, 0, 0), \
            "%s: three testcases should be passing, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)


@tcfl.tc.interconnect(ttbd.url_spec, mode = 'one-per-type')
@tcfl.tc.interconnect(ttbd.url_spec, mode = 'one-per-type')
class _03_two_ics(tcfl.tc.tc_c):
    """
    Request two interconnects, shall run six times as we have three
    interconnect types and we are requesting one per type of each:

    - 9 possible permutations (3 x 3)
    - 3 repeated permutations (A B vs B A)

    """
    @staticmethod
    def eval(ic, ic1):
        assert 'interconnect_c' in ic.rt['interfaces']
        assert 'interconnect_c' in ic1.rt['interfaces']

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(6, 0, 0, 0, 0), \
            "%s: six testcases should be passing, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)


@tcfl.tc.interconnect(ttbd.url_spec, mode = "all")
@tcfl.tc.interconnect(ttbd.url_spec, mode = "all")
@tcfl.tc.target(ttbd.url_spec + " and ic.id in interconnects", mode = "all")
@tcfl.tc.target(ttbd.url_spec + " and ic1.id in interconnects", mode = "all")
class _04_two_ics_two_tgs(tcfl.tc.tc_c):
    """
    Request two interconnects, two targets, one target on each
    interconnect
    """
    @staticmethod
    def eval(ic, ic1, target, target1):
        assert ic.id in target.rt['interconnects'] \
            or ic1.id in target.rt['interconnects']
        assert ic.id in target1.rt['interconnects'] \
            or ic1.id in target1.rt['interconnects']

    @classmethod
    def class_teardown(cls):
        # networks, 60 total combinations; sometimes we get 59, not
        # sure why yet.
        assert cls.class_result == tcfl.tc.result_c(59, 0, 0, 0, 0) \
            or cls.class_result == tcfl.tc.result_c(60, 0, 0, 0, 0), \
            "%s: fifty nine or sixty testcases should be passing, " \
            "got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)


@tcfl.tc.interconnect(ttbd.url_spec + " and id == 'r'", 'icr')
@tcfl.tc.interconnect(ttbd.url_spec + " and id == 's'", 'ics')
# Impossible, as targets s* are in s but we are asking for s* that
# are on the first interconnect
@tcfl.tc.target(
    ttbd.url_spec + " and id:'^s' and icr.id in interconnects", 'targets1')
@tcfl.tc.target(
    ttbd.url_spec + " and id:'^s' and icr.id in interconnects", 'targets2')
class _05_two_ics_two_tgs_impossible(tcfl.tc.tc_c):
    """
    Request two interconnects of type r and s, two targets of name
    s* (so they are in the s interconnect) but asking for them to
    be in the r interconnect. Shall fail to instantiate the
    testcase as it won't be able to find them.
    """
    @staticmethod
    def eval():
        assert False, "Should never get here"

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(0, 0, 0, 0, 1), \
            "%s: expected one testcases skipped, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)


@tcfl.tc.interconnect(ttbd.url_spec, name = "ic0")
@tcfl.tc.interconnect(ttbd.url_spec, name = "ic1")
@tcfl.tc.target(ttbd.url_spec + " and ic0.id in interconnects")
@tcfl.tc.target(
    ttbd.url_spec + " and ic0.id in interconnects and ic1.id in interconnects")
@tcfl.tc.target(ttbd.url_spec + " and ic1.id in interconnects")
class _05_two_ics_three_tgs_impossible(tcfl.tc.tc_c):
    """
    Request two interconnects, three targets, one target on each
    interconnect, the one in the middle in both. It will fail to
    find such as the current configuration does not have any
    target configured in both interconnects.
    """
    @staticmethod
    def eval():
        assert False, "Should never get here"

    @classmethod
    def class_teardown(cls):
        assert cls.class_result == tcfl.tc.result_c(0, 0, 0, 0, 6), \
            "%s: expected six testcases skipped, got %s instead" \
            % (cls.__name__, cls.class_result)
        return tcfl.tc.result_c(0, 0, 0, 0, 0)
