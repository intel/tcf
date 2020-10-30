#! /usr/bin/python3
import tcfl.tc
@tcfl.tc.target('zephyr_board and bsp == "x86"')
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval_00(target):
        target.report_info("Hello 1")

    def eval_01(self):
        self.report_info("Hello 2")
