#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
Test translation of return values from methods into result_c
------------------------------------------------------------

:meth:`tcfl.tc.result_c.from_retval` takes any return value from a
method and tries to convert it into a result_c, mapping into
PASS/ERRR/FAIL/BLCK/SKIP.

This tries to exercise all possible scenarios.

Because some test cases will trigger a failure and we still don't
support tagging an expected failure, we use the *teardown* method to
check the evaluation result--if it is what is expected, we override it
to signal a pass.
"""

import os
import tcfl.tc


class _mc(tcfl.tc._tc_mc):
    # Metaclass for tc_c, to initialize class specific fields
    def __init__(cls, name, bases, d):
        tcfl.tc._tc_mc.__init__(cls, name, bases, d)
        cls.exception_to_result[AssertionError] = tcfl.tc.failed_e


class pass_base(tcfl.tc.tc_c):
    def teardown(self):
        if self.result_eval.passed == 0:
            raise tcfl.tc.fail_e(
                f"expected pass, but result_eval is {self.result_eval}")
        self.report_pass(f"got expected pass")


class pass_empty(pass_base):
    @staticmethod
    def eval():
        pass


class pass_return_nothing(pass_base):
    @staticmethod
    def eval():
        return


class pass_return_none(pass_base):
    @staticmethod
    def eval():
        return None


class pass_return_true(pass_base):
    @staticmethod
    def eval():
        return True


class pass_return_result_c_1(pass_base):
    @staticmethod
    def eval():
        return tcfl.tc.result_c(passed = 1)


class pass_return_result_c_2(pass_base):
    @staticmethod
    def eval():
        return tcfl.tc.result_c(passed = 2)


class pass_raise_pass_e(pass_base):
    @staticmethod
    def eval():
        raise tcfl.tc.pass_e("pass via pass exception")



class fail_base(tcfl.tc.tc_c):
    def teardown(self):
        if self.result_eval.failed == 0:
            raise tcfl.tc.fail_e(
                f"expected failure, but result_eval is {self.result_eval}")
        self.report_pass(f"got expected failure")
        self.result_eval.failed = 0
        self.result_eval.passed = 1


class fail_return_false(fail_base):
    @staticmethod
    def eval():
        return False


class fail_return_result_c_failed_1(fail_base):
    @staticmethod
    def eval():
        return tcfl.tc.result_c(failed = 1)


class fail_return_result_c_failed_2(fail_base):
    @staticmethod
    def eval():
        return tcfl.tc.result_c(failed = 2)


class fail_raise_failed_e(fail_base):
    @staticmethod
    def eval():
        raise tcfl.tc.failed_e("fail via exception")


class fail_assertion(fail_base, metaclass = _mc):
    @staticmethod
    def eval():
        # We configured in the metaclass _mc that AssertionError means fail
        assert False, "fail via assertion exception"



class block_base(tcfl.tc.tc_c):
    def teardown(self):
        if self.result_eval.blocked == 0:
            raise tcfl.tc.fail_e(
                f"expected blockage, but result_eval is {self.result_eval}")
        self.report_pass(f"got expected blockage")
        self.result_eval.blocked = 0
        self.result_eval.passed = 1


class blocked_return_int(block_base):
    @staticmethod
    def eval():
        return 3


class blocked_return_dict(block_base):
    @staticmethod
    def eval():
        return dict()


class blocked_return_list(block_base):
    @staticmethod
    def eval():
        return list()


class blocked_return_set(block_base):
    @staticmethod
    def eval():
        return set()


class blocked_return_str(block_base):
    @staticmethod
    def eval():
        return "somestring"


class fail_return_result_c_blocked_1(block_base):
    @staticmethod
    def eval():
        return tcfl.tc.result_c(blocked = 1)


class fail_return_result_c_blocked_2(block_base):
    @staticmethod
    def eval():
        return tcfl.tc.result_c(blocked = 2)


class fail_raise_blocked_e(block_base):
    @staticmethod
    def eval():
        raise tcfl.tc.blocked_e("block via exception")



class skip_base(tcfl.tc.tc_c):
    def teardown(self):
        if self.result_eval.skipped == 0:
            raise tcfl.tc.failed_e(
                f"expected skip, but result_eval is {self.result_eval}")
        self.report_pass(f"got expected skip")
        self.result_eval.skipped = 0
        self.result_eval.passed = 1


class skip_return_result_c_1(skip_base):
    @staticmethod
    def eval():
        return tcfl.tc.result_c(skipped = 1)


class skip_return_result_c_2(skip_base):
    @staticmethod
    def eval():
        return tcfl.tc.result_c(skipped = 2)


class skip_raise_skip_e(skip_base):
    @staticmethod
    def eval():
        raise tcfl.tc.skip_e("skip via exception")
