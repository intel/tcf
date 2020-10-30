#! /usr/bin/python3
#
# Copyright (c) 2017-20 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""Interaction with JTAGs and similar using OpenOCD
------------------------------------------------

This module provides the building block to debug many boards with
`OpenOCD <http://openocd.org/>`_.

Class :class:`ttbl.openocd.pc` is a power controller that when added
to a power rail, will start *OpenOCD* and then allow to use it to
perform debug operations and flashing on the target's board.

"""
#
# FIXME: clarify the whole target vs target_id in the addrmap, it is
# currently a mess
# FIXME: add a configuration methodology for
# .addrmap_add()
# .board_add()

import codecs
import contextlib
import errno
import logging
import os
import re
import socket
import time
import traceback
import types

import pexpect
try:
    import pexpect.fdpexpect
except ImportError:
    # RHEL 7 -> fdpexpect is a separate module, not a submod of pexpectg    import fdpexpect
    import fdpexpect
    pexpect.fdpexpect = fdpexpect

# FIXME: remove -> cleanup
try:
    from pexpect.exceptions import TIMEOUT as pexpect_TIMEOUT
    from pexpect.exceptions import EOF as pexpect_EOF
except ImportError:
    from pexpect import TIMEOUT as pexpect_TIMEOUT
    from pexpect import EOF as pexpect_EOF

import commonl
import ttbl
import ttbl.debug
import ttbl.images
import ttbl.power

# FIXME: rename to address_maps
addrmaps = {
    # Address maps for each (target/BSP) in a board
    # Each entry is named after the target/BSP inside the board.
    # target_id is the ID of the target we select for doing
    #   operations; if there is none, there is only one and we
    #   don't have to waste time running target selection commands.
    # target is the ID of the target we use to write/read (might
    #   be different than 'target' for some boards.
    'quark_se_a101': {
        'rom': dict(load_addr=0xffffe400, target = None),
        'bootloader': dict(load_addr=0x40000000, target = None),
        'x86': dict(load_addr=0x40010000, target = 1, target_id = 0),
        'arc': dict(load_addr=0x40034000, target = 1, target_id = 1),
    },
    'quark_se': {
        # QMSI v1.1.0 firmware
        'rom': dict(load_addr=0xffffe000, target = None),
        'x86': dict(load_addr=0x40030000, target = 1, target_id = 0),
        'arc': dict(load_addr=0x40000000, target = 1, target_id = 1),
    },
    'quark_d2000_crb': {
        'x86': dict(load_addr=0x00180000, target = 0, target_id = 0),
        'bootloader': dict(load_addr=0x00000000, target = None),
        'rom': dict(load_addr=0x00000000, target = None),
    },
    'stm32f1': {
        'arm': dict(load_addr = 0x08000000),
    },
    'quark_x1000': {
        'x86': dict(load_addr = 0x00000000),
    },
    'frdm_k64f': {
        'arm': dict(load_addr = 0x00000000),
    },
    'nrf5x': {
        'arm': dict(target_id = 0),
    },
    'sam_e70_xplained': {
        'arm': dict(load_addr = 0x00000000),
    },
    'sam_v71_xplained': {
        'arm': dict(load_addr = 0x00000000),
    },
    'snps_em_sk': {
        'arc': dict(load_addr = 0x00000000),
    },
}

# FIXME: move to board[name].akas?
board_synonyms = {
    'quark_se_devboard': 'quark_se_ctb',
    "nrf51_blenano": "nrf51",
    "nrf51_pca10028": "nrf51",
    "nrf52840_pca10056": "nrf52840",
    "nrf52_blenano2": "nrf52",
    "nrf52_pca10040": "nrf52",
}

#: Board description dictionary
#:
#: This is a dictionary keyed by board / MCU name; when the
#: OpenOCD driver is loaded, it is given this name and the entry
#: is opened to get some operation values.
#:
#: Each entry is another dictionary of key/value where key is a
#: string, value is whatever.
#:
#: FIXME: many missing
#:
#: - :data:`hack_reset_halt_after_init
#:   <ttbl.flasher.openocd_c.hack_reset_halt_after_init>`
boards = {
    'arduino_101': dict(
        addrmap = 'quark_se_a101',
        targets = [ 'x86', 'arc' ],
        interface = 'interface/ftdi/flyswatter2.cfg',
        board = None,
        # Well, Quarks are sometimes this quirky and the best way
        # to reset halt them is by issuing a reset and then a
        # reset halt.
        reset_halt_command = "reset; reset halt",
        hack_reset_after_power_on = True,
        config = """
interface ftdi
ftdi_serial "%(serial_string)s"
# Always needed, or openocd fails -100
ftdi_vid_pid 0x0403 0x6010
source [find board/quark_se.cfg]

quark_se.quark configure -event gdb-attach {
        reset halt
        gdb_breakpoint_override hard
}

quark_se.quark configure -event gdb-detach {
        resume
        shutdown
}
"""
    ),

    'galileo': dict(
        addrmap = 'quark_x1000',
        targets = [ 'x86' ],
        config = """
interface ftdi
# Always needed, or openocd fails -100
ftdi_vid_pid 0x0403 0x6010
ftdi_serial "%(serial_string)s"
source [find board/quark_x10xx_board.cfg]
"""
    ),

    'qc10000_crb' : dict(
        addrmap = 'quark_se',
        targets = [ 'x86', 'arc' ],
        # Well, Quarks are sometimes this quirky and the best way
        # to reset halt them is by issuing a reset and then a
        # reset halt.
        reset_halt_command = "reset; reset halt",
        hack_reset_after_power_on = True,
        config = """
interface ftdi
ftdi_serial "%(serial_string)s"
# Always needed, or openocd fails -100
ftdi_vid_pid 0x0403 0x6010

ftdi_channel        0
ftdi_layout_init    0x0010 0xffff
ftdi_layout_signal  nTRST -data 0x0100 -oe 0x0100

source [find board/quark_se.cfg]
"""
    ),

    # OpenOCD 0.8
    'quark_d2000_crb_v8' : dict(
        addrmap = 'quark_d2000_crb',
        targets = [ 'x86' ],
        #board = 'quark_d2000_onboard',
        config = """
interface ftdi
ftdi_serial "%(serial_string)s"
# Always needed, or openocd fails -100
ftdi_vid_pid 0x0403 0x6014
ftdi_channel 0

ftdi_layout_init 0x0000 0x030b
ftdi_layout_signal nTRST -data 0x0100 -noe 0x0100
ftdi_layout_signal nSRST -data 0x0200 -oe 0x0200


# default frequency but this can be adjusted at runtime
#adapter_khz 1000
adapter_khz 6000

reset_config trst_only

source [find target/quark_d2000.cfg]
"""
    ),

    # OpenOCD 0.10
    'quark_d2000_crb' : dict(
        addrmap = 'quark_d2000_crb',
        targets = [ 'x86' ],
        #board = 'quark_d2000_onboard',
        config = """
interface ftdi
ftdi_serial "%(serial_string)s"
# Always needed, or openocd fails -100
ftdi_vid_pid 0x0403 0x6014
ftdi_channel 0

ftdi_layout_init 0x0000 0x030b
ftdi_layout_signal nTRST -data 0x0100 -noe 0x0100
ftdi_layout_signal nSRST -data 0x0200 -oe 0x0200


# default frequency but this can be adjusted at runtime
#adapter_khz 1000
adapter_khz 6000

reset_config trst_only

source [find target/quark_d20xx.cfg]
"""
    ),

    'quark_se_ctb': dict(
        addrmap = 'quark_se',
        targets = [ 'x86', 'arc' ],
        interface = None,
        board = 'quark_se',
        hack_reset_after_power_on = True,
        config = """
interface ftdi
ftdi_serial "%(serial_string)s"
# Always needed, or openocd fails -100
ftdi_vid_pid 0x0403 0x6010

# oe_n  0x0200
# rst   0x0800

ftdi_channel        0
ftdi_layout_init    0x0000 0xffff
ftdi_layout_signal nTRST -data 0x0100 -oe 0x0100
"""
    ),

    #
    # This requires openocd v0.10.0 (pre-development as of 5/9/16)
    #
    'frdm_k64f': dict(
        addrmap = 'frdm_k64f',
        targets = [ 'arm' ],
        target_id_names = { 0: 'k60.cpu'},
        interface = None,
        board = None,
        write_command = "flash write_image erase %(file)s %(address)s",
        config = """\
interface cmsis-dap
cmsis_dap_serial %(serial_string)s
source [find target/k60.cfg]
"""
    ),
    'nrf51': dict(
        addrmap = 'nrf5x',	# Only to describe targets
        targets = [ 'arm' ],
        interface = None,
        board = None,
        write_command = "program %(file)s verify",
        config = """\
source [find interface/jlink.cfg]
jlink serial %(serial_string)s
transport select swd
set WORKAREASIZE 0
source [find target/nrf51.cfg]
"""
    ),
    'nrf52': dict(
        addrmap = 'nrf5x',	# Only to describe targets
        targets = [ 'arm' ],
        interface = None,
        board = None,
        write_command = "program %(file)s verify",
        # We use the nrf51's config, works better
        config = """
source [find interface/jlink.cfg]
jlink serial %(serial_string)s
transport select swd
set WORKAREASIZE 0
source [find target/nrf51.cfg]
"""
    ),
    'nrf52840': dict(
        addrmap = 'nrf5x',	# Only to describe targets
        targets = [ 'arm' ],
        interface = None,
        board = None,
        write_command = "program %(file)s verify",
        # We use the nrf51's config, works better
        config = """
source [find interface/jlink.cfg]
jlink serial %(serial_string)s
transport select swd
set WORKAREASIZE 0
source [find target/nrf51.cfg]
"""
    ),
    #
    # This requires openocd v0.10.0 (pre-development as of 5/9/16)
    #
    'sam_e70_xplained': dict(
        addrmap = 'sam_e70_xplained',
        targets = [ 'arm' ],
        target_id_names = { 0: 'atsame70q21.cpu'},
        interface = None,
        board = None,
        write_command = "flash write_image erase %(file)s %(address)s",
        config = """\
interface cmsis-dap
cmsis_dap_serial %(serial_string)s
source [find target/atsamv.cfg]
"""
    ),

    #
    # This requires openocd v0.10.0 (pre-development as of 5/9/16)
    #
    'sam_v71_xplained': dict(
        addrmap = 'sam_v71_xplained',
        targets = [ 'arm' ],
        target_id_names = { 0: 'samv71.cpu'},
        interface = None,
        board = None,
        write_command = "flash write_image erase %(file)s %(address)s",
        config = """\
interface cmsis-dap
cmsis_dap_serial %(serial_string)s
source [find target/atsamv.cfg]
"""
    ),

    'snps_em_sk': dict(
        addrmap = 'snps_em_sk',
        targets = [ 'arc' ],
        target_id_names = { 0: 'arc-em.cpu'},
        interface = None,
        board = None,
        config = """\
interface ftdi
ftdi_serial "%(serial_string)s"
# Always needed, or openocd fails -100
ftdi_vid_pid 0x0403 0x6014
source [find board/snps_em_sk.cfg]
"""
    ),

    '': dict(
        addrmap = '',
        interface = None,
        board = '',
        config = ""
    ),
}




class action_logadapter_c(logging.LoggerAdapter):
    """
    """
    def __init__(self, logger, extra):
        logging.LoggerAdapter.__init__(self, logger, extra)
        # this will be set later by the _test_target_link() method
        self.prefix = ""

    def process(self, msg, kwargs):
        return 'OpenOCD/%s: %s: %s ' % (self.prefix, self.action, msg), kwargs

class pc(ttbl.power.daemon_c, ttbl.images.impl_c, ttbl.debug.impl_c):
    """

    :param str serial: serial number of the target board; this is
      usually a USB serial number.

    :param str board: name of the board we are connecting against;
      this has to be defined in :data:`boards` or
      :data:`board_synonyms`.

    :param bool debug: (optional) run OpenOCD in debugging mode,
      printing extra information to the log (default *False*).

    *target ID*

    OpenOCD will operate on targets (different to TCF's targets);
    these might one or more CPUs in the debugged system.  Each has an
    ID, which by default is zero.

    *component to OpenOCD target mapping*

    Each component configured in the target addition maps to an
    OpenOCD target in *boards[X][targets]*.

    **OLD OLD**

    This is a flasher object that uses OpenOCD to provide flashing
    and GDB server support.

    The object starts an OpenOCD instance (that runs as a daemon)
    -- it does this behaving as a power-control implementation
    that is plugged at the end of the power rail.

    .. note: OpenOCD will crash randomly for unknown reasons; this
      implementation makes the power system think the target is
      off when OpenOCD has crashed, so it can be restarted.

    To execute commands, it connects to the daemon via TCL and
    runs them using the ``'capture "OPENOCDCOMMAND"'`` TCL command
    (FIXME: is there a better way?). The telnet port is open for
    manual debugging (check your firewall! **no passwords!**); the GDB
    ports are also available.

    The class knows the configuration settings for different
    boards (as given in the `board_name` parameter. It is also
    possible to point it to specific OpenOCD paths when different
    builds / versions need to be used.

    Note how entry points from the flasher_c class all start with
    underscore. Functions ``__SOMETHING()`` are those that have to be
    called with a ``_expect_mgr`` context taken [see comments
    on ``__send_command`` for the reason.

    :param str board_name: name of the board to use, to select
      proper configuration parameters. Needs to be declared in
      *ttbl.flasher.openocd_c._boards*.

    When starting OpenOCD, run a reset halt immediately after.
    This is used when flashing, as we power cycle before to try
    to have the target in a proper state--we want to avoid it
    running any code that might alter the state again.

    Now, this is used in combination with another setting,
    board specific, that says if the reset has to be done or
    not in method :meth:_power_on_do_openocd_verify().

    But why? Because some Quark SE targets, when put in deep
    sleep mode, OpenOCD is unable to reset halt them, returning
    something like:

      > reset halt
      JTAG tap: quark_se.cltap tap/device found: 0x0e765013 (mfg: 0x009 (Intel), part: 0xe765, ver: 0x0)
      Enabling arc core tap
      JTAG tap: quark_se.arc-em enabled
      Enabling quark core tap
      JTAG tap: quark_se.quark enabled
      target is still running!
      target running, halt it first
      quark_se_target_reset could not write memory
      in procedure 'reset' called at file "command.c", line 787

    So what we are trying to do, and it is a *horrible hack*,
    is to hopefully catch the CPU before it gets into that
    mode, and when it does, it bails out if it fails to reset
    and restarts OpenOCD and maybe (maybe) it at some point
    will get it.

    Now, this is by NO MEANS a proper fix. The right fix would
    be for OpenOCD to be able to reset in any circumstance
    (which it doesn't). An alternative would be to find some
    kind of memory location OpenOCD can write to that will take
    the CPU out of whichever state it gets stuck at which we
    can run when we see that.

    Zephyr's sample samples/board/quark_se/power_mgr is very
    good at making this happen.

    """
    def __init__(self, serial, board, debug = False,
                 openocd_path = "/usr/bin/openocd",
                 openocd_scripts = "/usr/share/openocd/scripts"):
        assert isinstance(serial, str)
        assert isinstance(board, str)
        assert isinstance(debug, bool)
        assert isinstance(openocd_path, str)
        assert isinstance(openocd_scripts, str)

        self.serial = serial

        self.board_name = board_synonyms.get(board, board)
        if not self.board_name in boards:
            raise ValueError("OpenOCD: unknown board '%s' (expected %s %s)" %
                             (self.board_name,
                              " ".join(list(boards.keys())),
                              " ".join(list(board_synonyms.keys()))))
        self.debug = debug
        self.board = boards[self.board_name]
        if 'addrmap' in self.board:
            self.addrmap = addrmaps[boards[self.board_name]['addrmap']]
        else:
            self.addrmap = None

        self.openocd_path = openocd_path
        self.openocd_scripts = openocd_scripts

        self.log = None

        # FIXME: Expose all these tags/fsdb properties too or move
        #        them to config?
        #: FIXME
        self.hard_recover_rest_time = None
        #: FIXME:
        self.hack_reset_after_power_on = False
        #: Inmediately after running the OpenOCD initialization
        #: sequence, reset halt the board.
        #:
        #: This is meant to be used when we know we are power cycling
        #: before flashing. The board will start running as soon as we
        #: power it on, thus we ask OpenOCD to stop it inmediately
        #: after initializing. There is still a big window of time on
        #: which the board can get itself in a bad state by running
        #: its own code.
        #:
        #: (bool, default False)
        self.hack_reset_halt_after_init = 0
        #: Inmediately after running the OpenOCD initialization
        #: sequence, reset the board.
        #:
        #: This is meant to be used for hacking some boards that don't
        #: start properly OpenOCD unless this is done.
        #:
        #: (bool, default False)
        self.hack_reset_after_init = 0

        # the fields openocd-* are set in on() as target properties
        cmdline = [
            openocd_path,
            "--log_output", "%(path)s/%(component)s-%(name)s.log",
            "-c", 'tcl_port %(openocd-tcl-port)d',
            "-c", 'telnet_port %(openocd-telnet-port)d',
            "-c", 'gdb_port %(openocd-gdb-port)d',
            "-s", self.openocd_scripts
        ]
        if debug:
            cmdline += [ "-d" ]
        # add an specific config file for the itnerface
        interface_cfg_file = self.board.get('interface', None)
        if interface_cfg_file != None:
            cmdline += [ "-f", interface_cfg_file ]
        # if board is defined, load OPENOCD_SCRIPTS/board/BOARD.cfg
        board_cfg_file = self.board.get('board', None)
        if board_cfg_file != None:
            openocd_scripts = self.openocd_scripts
            if openocd_scripts == None:
                openocd_scripts = ""
            cmdline += [
                "-f", os.path.join(openocd_scripts, "board",
                                   board_cfg_file + ".cfg")
            ]

        ttbl.power.daemon_c.__init__(self, cmdline = cmdline)
        ttbl.images.impl_c.__init__(self)
        ttbl.debug.impl_c.__init__(self)
        self.upid_set("OpenOCD supported JTAG",
                      usb_serial_number = self.serial)


    class error(Exception):
        # FIXME: rename to exception
        pass


    # Something that went wrong interacting with OpenOCD, not other errors
    class expect_connect_e(error):
        pass

    #
    # Power interface
    #

    def verify(self, target, component, cmdline_expanded):
        self.log = target.log
        # ttbl.power.daemon_c -> verify if the process has started
        # returns *True*, *False*
        #
        # Connect to the Qemu Monitor socket and issue a status command,
        # verify we get 'running', giving it some time to report.
        #
        # :returns: *True* if the QEMU VM is running ok, *False* otherwise
        # :raises: anything on errors

        # DEBUG: check only the logfile exists, third command line field
        # this is the log file name, that has been expanded already by
        # the daemon_c class calling start
        return os.path.exists(cmdline_expanded[2])

def __pending(self):
    if False:
        # Try up to 4 seconds to start properly -- experimentation has
        # shown that if it fails with ECONNREFUSED the first two
        # times, it means the thing has crashed
        timedout = False
        crashed = False

        try:
            # List targets to determine if we have a good
            # initialization
            self.log.action = "init verification (%d/%d)" \
                              % (count + 1, top)
            with self._expect_mgr():
                self.__send_command(
                    "init command JTAG (%d/%d)" % (count + 1, top), "init")

                if self.board.get("hack_reset_after_power_on", False) \
                   and self.hack_reset_after_power_on:
                    # This board needs this hack because we are
                    # power cycling to flash
                    self._power_on_reset_hack(count, top)

                hack_reset_after_init = self.board.get(
                    "hack_reset_after_init", self.hack_reset_after_init)
                for cnt in range(hack_reset_after_init):
                    try:
                        self.__target_reset(
                            "for reset after init [%d/%d]"
                            % (cnt + 1, hack_reset_after_init))
                        break
                    except self.error as e:
                        if cnt >= hack_reset_after_init:
                            raise
                        logging.error(
                            "[%d/%d: error resetting, retrying: %s",
                            cnt, hack_reset_after_init, e)
                else:
                    assert False	# Should never get here

                hack_reset_halt_after_init = self.board.get(
                    "hack_reset_halt_after_init",
                    self.hack_reset_halt_after_init)
                for cnt in range(hack_reset_halt_after_init):
                    try:
                        self.__target_reset_halt(
                            "for reset/halt after init [%d/%d]"
                            % (cnt + 1, hack_reset_halt_after_init))
                        break
                    except self.error as e:
                        if cnt >= hack_reset_halt_after_init:
                            raise
                        logging.error(
                            "[%d/%d: error reset halting, retrying: %s",
                            cnt, hack_reset_halt_after_init, e)
                else:
                    assert False	# Should never get here

                r = self.__send_command(
                    "init verification JTAG (%d/%d)" % (count + 1, top),
                    "targets",
                    [
                        re.compile(
                            r" [0-9]+\* .*(halted|reset|running|unknown)"),
                        # this is bad news
                        re.compile(
                            r" [0-9]+\* .*(tap-disabled)"),
                    ])
                if r == 1:
                    self.log.error("OpenOCD can't connect to the target"
                                   " (tap is disabled)")
                    self._log_output()
                    return False
            return True
        except OSError as e:
            if e.errno == errno.ECONNREFUSED and timedout:
                self.log.error("connection refused afer a timeout; "
                               "crashed?")
                self._log_output()
                return False
            if e.errno == errno.ECONNREFUSED and crashed:
                self.log.error("connection refused afer an EOF; crashed?")
                self._log_output()
                return False
        except self.error_timeout as e:
            timedout = True
            self.log.error("timedout, retrying: %s" % e)
        except self.error_eof as e:
            if crashed == True:
                self.log.error("EOF again, seems crashed?")
                self._log_output()
                return False
            crashed = True
            self.log.error("EOF, retrying: %s" % e)
        except self.error as e:
            self.log.error("retrying: %s" % e)

    def on(self, target, component):
        self.log = target.log
        self.log.action = "openocd start"

        # Well, reusing the TCP port range is creating plenty of
        # problems, as when we kill it and try to restart it, the
        # sockets are lingering and it fails to reopen it...
        #
        # So we'll go random -- if it fails, it'll be restarted
        # with another one
        tcp_port_base = commonl.tcp_port_assigner(
            2 + len(self.board['targets']) - 1,
            ttbl.config.tcp_port_range)

        # these are so the command line can be substituted
        target.fsdb.set("openocd-serial-string", self.serial)
        target.fsdb.set("openocd-tcp-port", tcp_port_base + 1)
        target.fsdb.set("openocd-telnet-port", tcp_port_base)
        target.fsdb.set("openocd-gdb-port", tcp_port_base + 2)

        self.cmdline_extra = []
        # configuration text for the board itself
        #
        # this can be read anytime, but can only be written once we
        # know the target and thus it has to happen in the on() method
        if self.board['config']:
            name = os.path.join(target.state_dir,
                                "openocd-board-%s.cfg" % component)
            with open(name, "w") as cfgf:
                cfgf.write(self.board['config'] % kws)
            self.cmdline_extra += [ "-f", name ]

        ttbl.power.daemon_c.on(self, target, component)



    #
    # Still not tested
    #

    def _pattern_or_str(self, expect):
        if hasattr(expect, "pattern"):
            waiting_for = expect.pattern
        elif isinstance(expect, str):
            waiting_for = expect
        else:	# Iterable?
            try:
                waiting_for = []
                for e in expect:
                    waiting_for.append(self._pattern_or_str(e))
            except:
                waiting_for = expect
        return waiting_for


    @contextlib.contextmanager
    def _expect_mgr(self):
        """
        Open up a socket to the OpenOCD TCL port and start a expect
        object to talk to it.

        This is a context manager; upon return, kill it all.
        """
        def read_nonblocking_patched(self, size = 1, timeout = None):
            try:
                return self.read_nonblocking_original(size, timeout)
            except OSError as e:
                if e.args[0] == errno.EAGAIN:
                    return ""
                raise
            except:
                raise

        self.p = None
        self.sk = None
        self.pid = None
        self.pid_s = None
        tcp_port_base = -1
        try:
            try:
                self.pid_s = self.tt.fsdb.get("openocd.pid")
                if self.pid_s == None:
                    raise self.error("can't find OpenOCD's pid")
                self.pid = int(self.pid_s)
                tcp_port_base = int(self.tt.fsdb.get("openocd.port"))
                self.log.debug("connecting to openocd pid %d port %d"
                               % (self.pid, tcp_port_base + 1))
                self.sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # TCL conection!
                self.sk.settimeout(5)
                self.sk.connect(("localhost", tcp_port_base + 1))
                self.p = pexpect.fdpexpect.fdspawn(
                    self.sk.fileno(),
                    # Open logfile with no codec anything, this seems to
                    # yield the best result to avoid UnicodeErrors; we
                    # open it, however, as utf-8,errors=replace
                    # Append to log file, so we can tell the full story
                    logfile = open(self.log_name + ".expect", "ab"),
                    timeout = 5)
                # FDexpect seems to have a bug where an EAGAIN is just
                # floated up instead of waiting
                self.p.read_nonblocking_original = self.p.read_nonblocking
                self.p.read_nonblocking = types.MethodType(
                    read_nonblocking_patched, self.p)
            except (Exception, OSError) as e:
                s = "expect init (pid %s port %d) failed: %s" \
                    % (self.pid_s, tcp_port_base + 1, e)
                if type(e) == Exception:	# Code BUG?
                    s += "\n" + traceback.format_exc()
                self.log.warning(s)
                raise self.expect_connect_e(s)
            yield
        finally:
            # Make sure the cleanup is always executed no matter what
            if self.p != None:
                # Some pexpect versions don't close this file properly
                if self.p.logfile:
                    del self.p.logfile
                del self.p
            if self.sk != None:
                try:
                    self.sk.shutdown(socket.SHUT_RDWR)
                except Exception as e:
                    self.log.warning("Error shutting down socket: %s", e)
                self.sk.close()
                del self.sk

    def _log_error_output(self, msg = "n/a"):
        self.log.error("Error condition: " + msg)
        if self.p != None:
            for line in self.p.before.splitlines():
                self.log.error("output[before]: "
                               + line.encode('utf-8').strip())
        # FIXME: not really needed, it adds too much blub
        #with codecs.open(self.log_name + ".expect", "r", encoding = 'utf-8',
        #                 errors = 'replace') as inf:
        #    for line in inf:
        #        self.log.error("output: " + line.strip())

    def _log_output(self):
        with codecs.open(self.log_name, "r", encoding = 'utf-8',
                         errors = 'replace') as inf:
            for line in inf:
                self.log.error("log: " + line.strip())

    def __send_command(self, action, command, expect = None,
                       timeout = 3):
        """
        :param str|list|regex expect: what to expect. Don't use open
                      ended regular expressions (eg: "something.*") as
                      that would capture the last character that
                      expect sends (the transmission terminator) and
                      this function would not be able to find it.

        :param int timeout: Default timeout for normal command
           execution; commands that take longer to execute (like
           memory writes, etc), shall increase it

        Note this creates/connects a socket and a expect object which
        each command we send. Sounds (and is) quite a lot of overhead,
        but it has proben to work much more dependably than keeping a
        expect object and socket around.

        Note this has to be called from within a 'with
        self._expect_mgr' block. If you run multiple commands, you
        might want to use a single block for them, otherwise OpenOCD
        runs out of sockets (and doesn't recycle them fast enough) and
        connections are rejected, resulting in EOF
        errors. Annoying. As we kill the OpenOCD process when we power
        off the target, this seems to be good enough to not run out of sockets.

        """
        self.log.action = action
        waiting_for = self._pattern_or_str(expect)
        r = None
        try:
            self.log.debug("running: %s" % command)
            if command:
                self.p.send(('capture "' + command + '"\x1a').encode("utf-8"))
            self.p.timeout = timeout		# spec in the fn does not work
            if expect != None:
                self.log.debug("waiting for response [%.fs]: %s",
                               timeout, expect)
                r = self.p.expect(expect, timeout = timeout)
                self.log.debug("got response: %d", r)
            self.log.debug("waiting for response terminator [%.fs]", timeout)
            waiting_for = "response terminator"
            self.p.expect("\x1a")
            self.log.info("completed, r = %s" % r)
        except pexpect_TIMEOUT as e:
            self.log.error("timeout waiting for '%s'" % waiting_for)
            self._log_error_output()
            raise self.error_timeout("%s: failed (timeout)" % self.log.action)
        except pexpect_EOF as e:
            self.log.error("can't find '%s' (EOF)" % waiting_for)
            self._log_error_output()
            # Is OpenOCD alive at this point?
            try:
                # note __send_command() is only called inside a 'with
                # expect_mgr()' block, which will have initialized self.pid*
                os.kill(self.pid, 0)
            except OSError as e:
                self.log.info("openocd[%d]: might be dead", self.pid)
            raise self.error_eof("%s: failed (EOF)" % self.log.action)
        except Exception as e:
            msg = "unknown error: %s\n%s" % (e, traceback.format_exc())
            self._log_error_output(msg)
            raise RuntimeError("%s: failed (exception): %s"
                               % (self.log.action, e))
        return r


    def _per_target_setup(self, _target, _component):
        # FIXME: not sure we'll really need this anymore
        if self.serial:
            self.log.prefix = "%s[%s]" % (self.board_name, self.serial)
        else:
            self.log.prefix = "%s" % (self.board_name)

    def _to_target_id(self, component):
        # each component is described in the address map and might
        # have a target id assigned; if it is not assigned, we assume
        # it is zero
        return self.addrmap[component].get('target_id', 0)

    def __target_id_select(self, target_id, for_what = ""):
        # This doesn't give good output...
        if 'target_id_names' in self.board:
            target_id_name = self.board['target_id_names'].get(
                target_id, "%d" % target_id)
        else:
            target_id_name = "%d" % target_id
        self.__send_command("set target %s %s" % (target_id, for_what),
                            "targets %s" % target_id_name)
        # ... so we look for TARGET* in the targets output
        # ' 1* quark_se.arc-em    arc32      little quark_se.arc-em    halted'
        self.__send_command(
            "check target %s selected %s" % (target_id_name, for_what),
            "targets",
            re.compile(r" %d\* .*(halted|reset|running)" % target_id))

    def __target_id_halt(self, target_id, for_what = ""):
        try:
            self.__target_id_select(target_id, for_what)
            # This doesn't give good output...
            # ... so we look for halted in the @targets output:
            ##  1* quark_se.arc-em  arc32   little quark_se.arc-em    halted
            self.__send_command("halt target %d %s" % (target_id, for_what),
                                "halt")
            r = self.__send_command(
                "check target %d halted %s" % (target_id, for_what),
                "targets",
                [
                    re.compile(r" %d\* .*(halted|reset)" % target_id),
                    # Bug? it is not timing out, so we catch others here
                    re.compile(r" %d\* .*" % target_id),
                ])
            if r != 0:
                msg = "halt target #%d %s: failed; got r = %d" \
                    % (target_id, for_what, r)
                self._log_error_output(msg)
                raise self.error(msg)
            return True
        except self.error:
            self.log.error("halt target %d %s: failed" % (target_id, for_what))
            raise

    def __target_reset(self, for_what):
        # this is used by the power on sequence, the imaging sequence
        # and the debug reset sequence
        # Expects being in a _expect_mgr() block
        r = self.__send_command("target reset/run %s" % for_what,
                                "reset run",
                                [
                                    "could not halt target",
                                    # Freedom Boards k64f
                                    "MDM: Chip is unsecured. Continuing.",
                                    "target running",
                                    "",   # nucleo-f103rb
                                ])
        if r == 0:
            self._log_error_output()
            raise self.error("Cannot reset %s (r %d)" % (for_what, r))

    def __target_reset_halt(self, for_what = ""):
        # called from _power_on_do_openocd_verify
        # called from _target_reset_halt
        # this assumes we are inside a 'with self._expect_mgr():' block
        self.log.action = "target reset halt init"
        command = self.board.get('reset_halt_command', "reset halt")
        r = self.__send_command(
            "target reset/halt %s" % for_what,
            command,
            [
                "target state: halted",
                "target halted due",
                # ARC (seen w/ EM Starter Kit's) driver reports this
                "JTAG tap: arc-em.cpu tap/device found:",
                # Freedom Boards k64f
                "MDM: Chip is unsecured. Continuing.",
                # Errors
                "could not halt target",
                "timed out while waiting for target halted",
                "Not halted",
            ])
        if r > 3:
            msg = "Cannot reset/halt %s (r %d)" % (for_what, r)
            self._log_error_output(msg)
            raise self.error("Cannot reset/halt %s (r %d)" % (for_what, r))

    def tt_flasher_target_reset_halt(self, target, _components):
        # - called from tt_flasher.images_do_set
        # - FIXME: move self.flasher.target_reset_halt -> _target_reset_halt
        tries = 1
        tries_max = 2
        # FIXME: current limitation, can't access the tags from the
        # constructor as the ones we add in target_add() aren't there
        # yet.
        wait = \
            float(self.tags.get('hard_recover_rest_time', 2))
        while tries <= tries_max:
            # The Arduino101 get's so stuck sometimes
            try:
                self.flasher.target_reset_halt(for_what)
                break
            except self.flasher.error:
                pass
            try_s = "%d/%d" % (tries, tries_max)
            time.sleep(2)
            try:
                self.flasher.target_reset("[recover reset #1 %s] " % try_s
                                          + for_what)
            except self.flasher.error:
                pass
            try:
                self.flasher.target_reset_halt("[retry %s] " % try_s
                                               + for_what)
                break
            except self.flasher.error:
                pass
            # In some targets, this fails because maybe we just
            # power-cycled and the JTAG said it was ready but it
            # is really not ready...when that happens, just
            # power-cycle again.
            # well, that didn't work either; bring the big guns,
            # power cycle it and try the whole thing again
            wait_s = (1 + 2.0 * tries/tries_max) * wait
            self.log.info("Failed to reset/halt, power-cycle (%.2fs) "
                          "and retrying (try %d/%d)"
                          % (wait_s, tries, tries_max))
            self.power_cycle(self.owner_get(), wait_s)
            tries += 1
        else:
            # FIXME: pass the exception we get or the log or something
            raise self.error("Can't reset/halt the target")

    def __target_id_resume(self, target_id, for_what = ""):
        try:
            self.__target_id_select(target_id, for_what)
            # This doesn't give good output...
            r = self.__send_command(
                "target#%d: resume %s" % (target_id, for_what),
                "resume",
                [
                    "",
                    "Target not halted",
                ])
            if r != 0:
                self._log_error_output()
                raise self.error("target#%d: resume %s failed: %s"
                                 % (target_id, for_what, r))
            # ... so we'd look at targets output, but by the time we
            # look it might have transitioned to another state, so
            # we'll just pray it works...
        except self.error:
            self._log_error_output()
            self.log.error("target#%d: cannot resume %s"
                           % (target_id, for_what))
            raise


    #
    # Debugging interface
    #

    def debug_start(self, target, components):
        # not much to do
        pass

    def debug_stop(self, target, components):
        # not much to do
        pass

    def debug_halt(self, target, components):
        self.log = target.log
        self.log.action = "target halt"
        with self._expect_mgr():
            for component in components:
                # this operates on each component
                self.__target_id_halt(self._to_target_id(component),
                                      "debug halt")

    def debug_reset(self, target, _components):
        self.log = target.log
        self.log.action = "target reset"
        if set(_components) != set(self.components):
            raise NotImplementedError(
                "OpenOCD can only reset all components at the same time (%s)"
                % (",".join(self.components)))
        self.log.action = "target reset"
        with self._expect_mgr():
            # this operates on all targets at the same time
            return self.__target_reset("debug reset")

    def debug_reset_halt(self, target, _components):
        self.log = target.log
        self.log.action = "target reset halt"
        if set(_components) != set(self.components):
            raise NotImplementedError(
                "OpenOCD can only reset/halt all components at the same time (%s)"
                % (",".join(self.components)))
        self.log.action = "target reset halt"
        with self._expect_mgr():
            # this operates on all targets at the same time
            return self.__target_reset_halt("debug reset halt")

    def debug_resume(self, target, _components):
        self.log = target.log
        self.log.action = "target resume"
        if set(_components) != set(self.components):
            raise NotImplementedError(
                "OpenOCD can only reset/halt all components at the same time (%s)"
                % (",".join(self.components)))
        self.log.action = "target resume"
        with self._expect_mgr():
            for component in components:
                # this operates on each component
                self.__target_id_resume(self._to_target_id(component),
                                        "debug resume")

    def debug_list(self, target, components):
        # FIXME: self.flasher should be providing this information, this
        # is breaking segmentation
        count = 2   # port #0 is for telnet, #1 for TCL
        tcp_port_base_s = self.fsdb.get("openocd.port")
        if tcp_port_base_s == None:
            return "Debugging information not available, power on?"
        tcp_port_base = int(tcp_port_base_s)
        s = "OpenOCD telnet server: %s %d\n" \
            % (socket.getfqdn('0.0.0.0'), tcp_port_base)
        for target in self.flasher.board['targets']:
            s += "GDB server: %s: tcp:%s:%d\n" % (target,
                                                  socket.getfqdn('0.0.0.0'),
                                                  tcp_port_base + count)
            count +=1
        if self.fsdb.get('powered') != None:
            s += "Debugging available as target is ON"
        else:
            s += "Debugging not available as target is OFF"
        return s

    def debug_command(self, target, component):
        self.log = target.log
        self.log.action = "command run"
        with self._expect_mgr():
            self.__send_command("command from user", cmd)
            return self.p.before

    # Wrap actual reset with retries
    def target_reset(self, for_what = ""):
        tries = 1
        tries_max = 5
        # FIXME: current limitation, can't access the tags from the
        # constructor as the ones we add in target_add() aren't there
        # yet.
        wait = \
            float(self.tags.get('hard_recover_rest_time', 10))
        while tries <= tries_max:
            # The Arduino101 get's so stuck sometimes
            try:
                self.flasher.target_reset(for_what)
                break
            except self.flasher.error:
                pass
            # Try again
            try:
                self.flasher.target_reset(for_what)
                break
            except self.flasher.error:
                pass
            # Bring the big guns, power cycle it
            if wait != None:
                wait_s = tries * wait
                self.log.info("Failed to reset/run, power-cycle (%.2fs) "
                              "and retrying (try %d/%d)"
                              % (wait_s, tries, tries_max))
                self.power_cycle(self.owner_get(), wait_s)
                tries += 1
        else:
            # FIXME: pass the exception we get or the log or something
            raise self.error("Can't reset/run the target")


    #
    # Images interface
    #
    def _image_write(self, image_type, file_name, timeout_factor = 1,
                     verify = True):
        if not image_type in self.addrmap:
            raise ValueError("%s: unknown image type" % image_type)
        load_addr = self.addrmap[image_type].get('load_addr', None)
        target = self.addrmap[image_type].get('target', None)
        fsize = os.stat(file_name).st_size
        timeout = 10 + fsize * 0.001	# Proportional to size
        timeout *= timeout_factor
        self.log.action = "image write init"
        with self._expect_mgr():
            try:
                # Note we assume the targets are already stopped
                if target != None:
                    self.__target_id_select(target, "for writing")
                    # Verify target is halted
                    self.__send_command(
                        "check target %d is halted for writing" % (target),
                        "targets",
                        re.compile(r" %d\* .*(halted|reset)" % target))

                write_command = self.board.get(
                    'write_command', "load_image %(file)s 0x%(address)x")
                # write_image says 'wrote', load_image 'downloaded'
                # Not only that, write_image (for flash) reports
                # rounded up sizes to some blocks, so we can't really
                # match on the size. Or if we are loading ELF, the
                # sizes reported are different. So yeah, just don't
                # worry about them sizes.
                self.__send_command("load image",
                                    write_command % dict(file = file_name,
                                                         address = load_addr),
                                    [ "downloaded [0-9]+ bytes",
                                      "wrote [0-9]+ bytes from file"],
                                    timeout)
                if verify == True and self.board.get("verify", True):
                    # Same comment about sizes here
                    r = self.__send_command(
                        "verify image",
                        'verify_image %s 0x%08x' % (file_name, load_addr),
                        [
                            "verified [0-9]+ bytes",
                            "diff [0-9]+ address 0x[0-9a-z]+\. Was 0x[0-9a-z]+ instead of 0x[0-9a-z]+",
                        ],
                        timeout)
                    if r != 0:
                        raise self.error("Cannot verify image (r %d)" % r)

            except self.error as e:
                self.log.error("can't write image: %s" % e)
                raise

    def images_do_set(self, images):
        # FIXME: current limitation, can't access the tags from the
        # constructor as the ones we add in target_add() aren't there
        # yet.
        wait = \
            float(self.tags.get('hard_recover_rest_time', 10))
        if self.fsdb.get("disable_power_cycle_before_flash") != 'True':
            # Make sure the target is really fresh before flashing it
            try:
                # See the documentation for this on class flasher_c
                # for why we have to do it.
                self.flasher.hack_reset_after_power_on = True
                self.power_cycle(self.owner_get(), wait = wait)
            finally:
                self.flasher.hack_reset_after_power_on = False
            self.log.info("sleeping 2s after power cycle")
            # HACK: For whatever the reason, we need to sleep before
            # resetting/halt, seems some of the targets are not ready
            # inmediately after
            time.sleep(2)
        self.target_reset_halt(for_what = "for image flashing")
        timeout_factor = self.tags.get('slow_flash_factor', 1)
        verify = self.tags.get('flash_verify', 'True') == 'True'
        # FIXME: replace this check for verifying which image types
        # the flasher supports
        for t, n in images.items():
            if t == "kernel-x86":
                it = "x86"
            elif t == "kernel":
                it = "x86"
            elif t == "kernel-arc":
                it = "arc"
            elif t == "kernel-arm":
                it = "arm"
            elif t == "rom":
                it = "rom"
            elif t == "bootloader":
                it = "bootloader"
            else:
                raise self.unsupported_image_e(
                    "%s: Unknown image type (expected "
                    "kernel|kernel-(x86,arc,arm), rom)"
                    % t)
            try:
                self.flasher.image_write(it, n, timeout_factor, verify)
            except ValueError as e:
                self.log.exception("flashing got exception: %s", e)
                raise self.unsupported_image_e(e.message)
