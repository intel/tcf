import os, time, tcfl.tc
@tcfl.tc.target('zephyr_board', app_zephyr = os.path.join("."))
class _test(tcfl.tc.tc_c):

    @tcfl.tc.serially()
    def build_00(self, target):
        target.zephyr.config_file_write('ztest', 'CONFIG_ZTEST=y')

    def setup_catch_failures(self, target):
        target.on_console_rx("PROJECT EXECUTION FAILED",
                             result = 'fail', timeout = False)

    def eval(self, target):
        target.expect("RunID: %(runid)s:%(tghash)s" % target.kws)
        target.expect("PROJECT EXECUTION SUCCESSFUL")
