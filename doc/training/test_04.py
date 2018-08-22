#! /usr/bin/python2
import tcfl.tc

@tcfl.tc.target("zephyr_board", mode = "any")
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval_00(target):
        target.report_info("Hello 1")

    @staticmethod
    def eval_01(target):
        target.report_info("Hello 2")
