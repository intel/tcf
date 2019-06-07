#! /usr/bin/python
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
    def eval_00(self, target, target1):
        with target.on_console_rx_cm('Hello World!'), \
             target1.on_console_rx_cm('Hello World!'):
            self.expecter.run()
