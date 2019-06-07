#! /usr/bin/python
import tcfl.tc

@tcfl.tc.target(mode = "any")
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval_00(target):
        target.report_info("Hello 1")

    @staticmethod
    def eval_01(target):
        target.report_info("Hello 2")
