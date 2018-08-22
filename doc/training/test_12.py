#! /usr/bin/python2
import tcfl.tc
@tcfl.tc.interconnect()
@tcfl.tc.target()
@tcfl.tc.target()
class _test(tcfl.tc.tc_c):
    def eval(self):
        self.report_info("got two interconnected targets")
