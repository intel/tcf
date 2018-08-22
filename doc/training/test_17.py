import os
import tcfl.tc
import tcfl.tl
@tcfl.tc.target(
    'zephyr_board '
    # Shell app can't run on NIOS2/RISCv32 due to no
    # IRQ-based UART support
    'and not zephyr_board in [ "qemu_nios2", "qemu_riscv32" ]',
    app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                              "samples", "subsys", "shell", "shell"))
class _test(tcfl.tc.tc_c):
    zephyr_filter = "UART_CONSOLE"
    zephyr_filter_origin = os.path.abspath(__file__)

    def eval(self, target):
        self.expecter.timeout = 20
        target.crlf = "\r"
        target.expect("shell>")
        target.send("select sample_module")
        target.expect("sample_module>")
