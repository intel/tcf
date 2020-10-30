#! /usr/bin/python3
import os
import tcfl.tc
import tcfl.tl
@tcfl.tc.target('zephyr_board', mode = 'any',
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          'samples', 'hello_world'))
@tcfl.tc.target('zephyr_board', mode = 'any',
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          'samples', 'hello_world'))
class _test(tcfl.tc.tc_c):
    @staticmethod
    def eval_00(target, target1):
        target.expect('Hello World!')
        target1.expect('Hello World!')
