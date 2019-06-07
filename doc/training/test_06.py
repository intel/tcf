#! /usr/bin/python
import os
import tcfl.tc
import tcfl.tl
@tcfl.tc.target('zephyr_board', mode = 'any',
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          'samples', 'hello_world'))
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval_00(target):
        target.report_info('Hello 1')

    def eval_01(self):
        self.report_info('Hello 2')
