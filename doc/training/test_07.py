#! /usr/bin/python
import os
import tcfl.tc
import tcfl.tl
@tcfl.tc.target('zephyr_board', mode = 'any',
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          'samples', 'hello_world'))
class _test(tcfl.tc.tc_c):
    @staticmethod
    @tcfl.tc.serially()
    def build(target):
        target.zephyr.config_file_write('banner_config',
                                        'CONFIG_BOOT_BANNER=y')

    @staticmethod
    def eval_00(target):
        target.expect('***** BOOTING ZEPHYR OS')

    def eval_01(self):
        self.report_info('Hello 2')
