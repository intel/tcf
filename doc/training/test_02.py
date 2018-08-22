#! /usr/bin/python2
import tcfl.tc

class _test(tcfl.tc.tc_c):
    def eval_00(self):
        self.report_info("Hello 1")

    def eval_01(self):
        self.report_info("Hello 2")
