#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os

import tcfl.tc

srcdir = os.path.dirname(__file__)

#
# Metaclass for tc_c, to initialize class specific fields
#
class _mc(tcfl.tc._tc_mc):
    def __init__(cls, name, bases, d):
        tcfl.tc._tc_mc.__init__(cls, name, bases, d)
        cls.exception_to_result[AssertionError] = tcfl.tc.failed_e

class _01_pass(tcfl.tc.tc_c, metaclass=_mc):
    """
    Return different things that mean "pass"
    """

    @staticmethod
    def test_00_nothing():
        pass

    @staticmethod
    def test_01_None():
        return None

    @staticmethod
    def test_02_True():
        return True

    @staticmethod
    def test_03():
        return tcfl.tc.result_c(1, 0, 0, 0, 0)

    @staticmethod
    def test_04():
        return tcfl.tc.result_c(12, 0, 0, 0, 0)

    @staticmethod
    def test_05():
        raise tcfl.tc.pass_e("pass via pass exception")

    def teardown(self):
        assert self.result_eval.summary() == tcfl.tc.result_c(1, 0, 0, 0, 0)


class _02_fail(tcfl.tc.tc_c, metaclass=_mc):
    """
    Return different things that mean "fail"
    """

    @staticmethod
    def test_02():
        return False

    @staticmethod
    def test_03():
        return tcfl.tc.result_c(0, 0, 1, 0, 0)

    @staticmethod
    def test_04():
        return tcfl.tc.result_c(0, 0, 2, 0, 0)

    @staticmethod
    def test_05():
        raise tcfl.tc.failed_e("fail via exception")

    @staticmethod
    def test_06():
        # We configured in the metaclass _mc that AssertionError means fail
        assert False, "fail via assertion exception"

    def teardown(self):
        assert self.result_eval.summary() == tcfl.tc.result_c(0, 0, 1, 0, 0)
        # that it fails means that it passed, so we override that
        # result with a pass
        self.result_eval = tcfl.tc.result_c(1, 0, 0, 0, 0)

class _03_block(tcfl.tc.tc_c, metaclass=_mc):
    """
    Return different things that mean "block"
    """

    @staticmethod
    def test_02():
        return False

    @staticmethod
    def test_03():
        return tcfl.tc.result_c(0, 0, 0, 1, 0)

    @staticmethod
    def test_04():
        return tcfl.tc.result_c(0, 0, 0, 2, 0)

    @staticmethod
    def test_05():
        raise tcfl.tc.blocked_e("block via exception")

    def teardown(self):
        assert self.result_eval.summary() == tcfl.tc.result_c(0, 0, 0, 1, 0)
        # that it fails means that it passed, so we override that
        # result with a pass
        self.result_eval = tcfl.tc.result_c(1, 0, 0, 0, 0)

class _04_skip(tcfl.tc.tc_c, metaclass=_mc):
    """
    Return different things that mean "skip"
    """

    @staticmethod
    def test_03():
        return tcfl.tc.result_c(0, 0, 0, 0, 1)

    @staticmethod
    def test_04():
        return tcfl.tc.result_c(0, 0, 0, 0, 2)

    @staticmethod
    def test_05():
        raise tcfl.tc.skip_e("skip via exception")

    def teardown(self):
        assert self.result_eval.summary() == tcfl.tc.result_c(0, 0, 0, 0, 1)
        # that it fails means that it passed, so we override that
        # result with a pass
        self.result_eval = tcfl.tc.result_c(1, 0, 0, 0, 0)
