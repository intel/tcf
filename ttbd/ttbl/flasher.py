#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# FIXME: clarify the whole target vs target_id in the addrmap, it is
# currently a mess
# FIXME: add a configuration methodology for
# .addrmap_add()
# .board_add()

import codecs
import contextlib
import errno
import hashlib
import logging
import os
import re
import signal
import socket
import subprocess
import tempfile
import time
import traceback
import types

import pexpect
import pexpect.fdpexpect

import commonl
import ttbl
import ttbl.cm_serial
try:
    from pexpect.exceptions import TIMEOUT as pexpect_TIMEOUT
    from pexpect.exceptions import EOF as pexpect_EOF
except ImportError:
    from pexpect import TIMEOUT as pexpect_TIMEOUT
    from pexpect import EOF as pexpect_EOF


class flasher_c(object):

    def _target_reset(self, for_what = ""):
        raise NotImplementedError

    def _target_reset_halt(self, for_what = ""):
        raise NotImplementedError

    def _target_halt(self, targets = None, for_what = ""):
        raise NotImplementedError

    def _target_resume(self, targets = None, for_what = ""):
        raise NotImplementedError

    def _image_write(self, image_type, file_name, timeout_factor = 1,
                     verify = True):
        raise NotImplementedError

    def _image_hash(self, image_type, size, timeout_factor = 1):
        raise NotImplementedError

    def _image_erase(self, image_type, size):
        raise NotImplementedError

    def _test_target_link(self, tt):
        raise NotImplementedError

    class error(RuntimeError):
        pass

    # Implement these functions
    def __init__(self):
        """
        Interface to flash and debug a target

        Implementations shall derive from here to provide the actual
        functionality, such as for example,
        :class:`openocd_c`.
        """
        #! (note this data is declared by this class, but used
        #! currently only by a subclass, :class:openocd_c)
        #!
        #! When starting OpenOCD, run a reset halt immediately after.
        #! This is used when flashing, as we power cycle before to try
        #! to have the target in a proper state--we want to avoid it
        #! running any code that might alter the state again.
        #!
        #! Now, this is used in combination with another setting,
        #! board specific, that says if the reset has to be done or
        #! not in method :meth:_power_on_do_openocd_verify().
        #!
        #! But why? Because some Quark SE targets, when put in deep
        #! sleep mode, OpenOCD is unable to reset halt them, returning
        #! something like:
        #!
        #!   > reset halt
        #!   JTAG tap: quark_se.cltap tap/device found: 0x0e765013 (mfg: 0x009 (Intel), part: 0xe765, ver: 0x0)
        #!   Enabling arc core tap
        #!   JTAG tap: quark_se.arc-em enabled
        #!   Enabling quark core tap
        #!   JTAG tap: quark_se.quark enabled
        #!   target is still running!
        #!   target running, halt it first
        #!   quark_se_target_reset could not write memory
        #!   in procedure 'reset' called at file "command.c", line 787
        #!
        #! So what we are trying to do, and it is a *horrible hack*,
        #! is to hopefully catch the CPU before it gets into that
        #! mode, and when it does, it bails out if it fails to reset
        #! and restarts OpenOCD and maybe (maybe) it at some point
        #! will get it.
        #!
        #! Now, this is by NO MEANS a proper fix. The right fix would
        #! be for OpenOCD to be able to reset in any circumstance
        #! (which it doesn't). An alternative would be to find some
        #! kind of memory location OpenOCD can write to that will take
        #! the CPU out of whichever state it gets stuck at which we
        #! can run when we see that.
        #!
        #! Zephyr's sample samples/board/quark_se/power_mgr is very
        #! good at making this happen.
        #!
        self.hack_reset_after_power_on = False
        self.hard_recover_rest_time = None

    # Start physical connections to the device
    def _start(self):
        raise NotImplementedError

    def _stop(self):
        raise NotImplementedError

    def start(self):
        self._start()

    def stop(self):
        self._stop()

    def image_write(self, image_type, file_name, timeout_factor = 1,
                    verify = True):
        assert isinstance(image_type, str)
        assert isinstance(file_name, str)
        self._image_write(image_type, file_name, timeout_factor, verify)

    def image_erase(self, image_type, size):
        assert isinstance(image_type, str)
        assert isinstance(size, int)
        self._image_erase(image_type, size)

    def image_hash(self, image_type, size, timeout_factor = 1):
        assert isinstance(image_type, str)
        assert isinstance(size, int)
        return self._image_hash(image_type, size, timeout_factor)

    def target_halt(self, targets = None, for_what = ""):
        if targets:
            assert isinstance(targets, list) or isinstance(targets, str)
        return self._target_halt(targets, for_what)

    def target_reset(self, for_what = ""):
        return self._target_reset(for_what)

    def target_reset_halt(self, for_what = ""):
        return self._target_reset_halt(for_what)

    def target_resume(self, targets = None, for_what = ""):
        if targets:
            assert isinstance(targets, list) or isinstance(targets, str)
        return self._target_resume(targets, for_what)

    def debug(self):
        # print info
        # reset halt
        raise NotImplementedError

    @staticmethod
    def openocd_cmd(cmd):
        return "This target does not support OpenOCD"

    def test_target_link(self, tt):
        """
        Tell this flasher who is our target -- we can't do that in
        __init__() because we don't necessarily know it at the time,
        so the class that uses us must do it.

        The implementation might use it or not, their choice.
        """
        assert isinstance(tt, ttbl.test_target)
        self.log = action_logadapter_c(tt.log, None)
        self.log.action = "(no action)"
        self.tt = tt
        self._test_target_link(tt)

    def __del__(self):
        # run
        # kill the process
        pass

class action_logadapter_c(logging.LoggerAdapter):
    """
    """
    def __init__(self, logger, extra):
        logging.LoggerAdapter.__init__(self, logger, extra)
        # this will be set later by the _test_target_link() method
        self.prefix = ""

    def process(self, msg, kwargs):
        return 'OpenOCD/%s: %s: %s ' % (self.prefix, self.action, msg), kwargs


class openocd_c(flasher_c, ttbl.tt_power_control_impl):

    # Something that went wrong interacting with OpenOCD, not other errors
    class error(flasher_c.error):
        pass

    class error_eof(error):
        pass

    class error_timeout(error):
        pass

    _addrmaps = {
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

    _board_synonyms = {
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
    _boards = {
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


    def __init__(self, _board_name, serial = None,
                 openocd_path = 'openocd',
                 openocd_scripts = '/usr/share/openocd/scripts',
                 debug = False):
        """This is a flasher object that uses OpenOCD to provide flashing
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

        """
        flasher_c.__init__(self)
        ttbl.tt_power_control_impl.__init__(self)
        if _board_name in self._board_synonyms:
            self.board_name = self._board_synonyms[_board_name]
        else:
            self.board_name = _board_name
        if not self.board_name in self._boards:
            raise ValueError("Unknown board '%s' (expected %s %s)" %
                             (self.board_name,
                              " ".join(list(self._boards.keys())),
                              " ".join(list(self._board_synonyms.keys()))))
        self.debug = debug
        self.board = self._boards[self.board_name]
        if 'addrmap' in self.board:
            self.addrmap = self._addrmaps[self._boards[self.board_name]['addrmap']]
        else:
            self.addrmap = None
        self.max_target = len(self.board['targets']) - 1
        self.serial = serial
        self.log = logging
        self.cfg_name = None
        self.log_name = None
        self.openocd_path = openocd_path
        self.openocd_scripts = openocd_scripts
        self.pid = None
        self.pid_s = None
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

    def _test_target_link(self, tt):
        if self.serial:
            self.log.prefix = "%s[%s]" % (self.board_name, self.serial)
        else:
            self.log.prefix = "%s" % (self.board_name)
        self.cfg_name = os.path.join(tt.state_dir, "openocd.cfg")
        self.log_name = os.path.join(tt.state_dir, "openocd.log")

    # Something that went wrong interacting with OpenOCD, not other errors
    class expect_connect_e(error):
        pass


    # Power control implementation
    #
    # Methods we implement: power_{off,on,get}_do to stop/start/query
    # if openocd is running.
    # This is to be used as part of the power rail that a target that
    # uses the openocd_c class.

    def _power_on_do_openocd_start(self):
        self.log.action = "openocd start"
        kws = {}
        if self.serial != None:
            kws["serial_string"] = self.serial
        else:
            kws["serial_string"] = "MISCONFIGURATION? SERIAL-NUMBER NOT SPECIFIED"
        # Well, reusing the TCP port range is creating plenty of
        # problems, as when we kill it and try to restart it, the
        # sockets are lingering and it fails to reopen it...
        #tcp_port_base = ttbl.tcp_port_assigner(2 + self.max_target)
        # Schew it, let's go random -- if it fails, it'll be restarted
        # with another one
        tcp_port_base = commonl.tcp_port_assigner(2 + self.max_target,
                                                  ttbl.config.tcp_port_range)
        self.log.debug("port base %d" % tcp_port_base)
        self.tt.fsdb.set("openocd.port", "%d" % tcp_port_base)
        self.log.debug("port base read: %s" % self.tt.fsdb.get("openocd.port"))
        args = [ self.openocd_path,
                 "-c", 'tcl_port %d' % (tcp_port_base + 1),
                 "-c", 'telnet_port %d' % tcp_port_base,
                 "--log_output", self.log_name,
                 "-c", 'gdb_port %d' % (tcp_port_base + 2) ]
        if self.debug:
            args.append("-d")
        if self.openocd_scripts:
            args += [ "-s", self.openocd_scripts ]
        if 'interface' in self.board and self.board['interface'] != None:
            args += [ "-f", self.board['interface'] ]
        if 'board' in self.board and self.board['board'] != None:
            if self.openocd_scripts == None:
                self.openocd_scripts = ""
            args += [ "-f", os.path.join(self.openocd_scripts, "board",
                                         self.board['board'] + ".cfg")]
        if self.board['config']:
            with open(os.path.join(self.tt.state_dir, "openocd.cfg"), "w") \
                 as cfgf:
                cfgf.write(self.board['config'] % kws)
                args += [ "-f", cfgf.name ]

        self.log.info("OpenOCD command line %s" % " ".join(args))
        self.tt.fsdb.set("openocd.path", commonl.which(self.openocd_path))
        p = subprocess.Popen(args, shell = False, cwd = self.tt.state_dir,
                             close_fds = True)
        # loop for a while until we can connect to it, to prove it's
        # done initializing
        self.pid = p.pid
        self.pid_s = "%d" % p.pid
        ttbl.daemon_pid_add(self.pid)	# FIXME: race condition if it died?
        # Write a pidfile, as openocd can't do it himself :/ [daemon 101]
        self.tt.fsdb.set("openocd.pid", self.pid_s)

    def _power_on_reset_hack(self, count, top):
        r = self.__send_command(
            "init reset run hack (%d/%d)" % (count + 1, top),
            "reset run",
            [
                # Errors, check on them first
                "could not halt target",
                "quark_se_target_reset could not write memory",
                "target running",
            ])
        if r != 2:
            self._log_error_output()
            raise self.error("Can't reset/run after init (r %d)" % r)
        r = self.__send_command(
            "init reset halt hack (%d/%d)" % (count + 1, top),
            "reset halt",
            [
                # Errors, check on them first
                "could not halt target",
                "timed out while waiting for target halted",
                "Not halted",
                "quark_se_target_reset could not write memory",
                # Successes
                "target state: halted",
                "target halted due",
                # EMSK prints this only :/
                "JTAG tap: arc-em.cpu tap/device found:",
            ])
        if r <= 4:
            self._log_error_output()
            raise self.error("Can't reset/halt after init (r %d)" % r)

    def _power_on_do_openocd_verify(self):
        # Try up to 4 seconds to start properly -- experimentation has
        # shown that if it fails with ECONNREFUSED the first two
        # times, it means the thing has crashed
        top = 8
        timedout = False
        crashed = False
        for count in range(top):
            time.sleep(0.5)	# Give it time to start
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
        else:
            self.log.error("retries expired (%d/%d)", count + 1, top)
            self._log_output()
            if self.tt.fsdb.get("openocd-relaxed", "").lower() == "true":
                return True
            return False

    def power_on_do(self, target):
        powered = self.power_get_do(target)
        if powered:
            return
        # power_get_do() has filled self.pid
        # start openocd if not running, try a few times
        top = 4
        for count in range(top):
            try:
                self._power_on_do_openocd_start()
                if self._power_on_do_openocd_verify():
                    break
                self.log.error("openocd (%d/%d) not responding",
                               count + 1, top)
            except self.error as e:
                # Sometimes openocd fails to open the device with a
                # -EINTR, so we are going to just retry
                self.log.error("openocd (%d/%d) init error: %s",
                               count + 1, top, e)
            if self.pid and commonl.process_alive(self.pid, self.openocd_path):
                self._power_off_do_kill()
            time.sleep(0.5)
        else:
            raise RuntimeError("openocd failed to start")

    def reset_do(self, target):
        pass

    def _power_off_do_kill(self):
        if self.pid == 0 or self.pid == None:
            self.log.error("BUG: OpenOCD pid %s found" % self.pid_s)
            return
        commonl.process_terminate(self.pid, None, "openocd[%d]" % self.pid)

    def power_off_do(self, target):
        powered = self.power_get_do(target)
        if not powered:
            return

        self.log.action = "openocd stop"
        self._power_off_do_kill()
        self.tt.fsdb.set("openocd.path", None)
        self.tt.fsdb.set("openocd.pid", None)
        self.tt.fsdb.set("openocd.port", None)

    def openocd_cmd(self, cmd):
        self.log.action = "running command from user"
        with self._expect_mgr():
            self.__send_command("command from user", cmd)
            return self.p.before

    def power_get_do(self, target):
        self.pid = None
        self.pid_s = None
        # Gather the PID for OpenOCD
        pid_s = target.fsdb.get("openocd.pid")
        if pid_s == None:
            return False
        try:
            pid = int(pid_s)
        except ValueError as e:
            # Invalid format, wipe
            target.fsdb.put("openocd.pid", None)
            return False

        openocd_path = target.fsdb.get("openocd.path")
        pid = commonl.process_alive(pid, openocd_path)
        if pid:
            self.pid = pid
            self.pid_s = pid_s
            return True
        return False

    def _start(self):
        pass

    def _stop(self):
        pass

    def _image_erase(self, image_type, size): # pylint: disable = no-self-use
        raise RuntimeError("OpenOCD doesn't support erasing flash")

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

    def _image_hash(self, image_type, size, timeout_factor = 1):
        #FIXME: make sure exception paths are handled properly
        if not image_type in self.addrmap:
            raise ValueError("%s: unknown image type" % image_type)
        tf = tempfile.NamedTemporaryFile()
        tf_name = tf.name
        load_addr = self.addrmap[image_type]['load_addr']
        target = self.addrmap[image_type].get('target', None)
        timeout = 10 + size * 0.001	# Proportional to size
        timeout *= timeout_factor
        self.log.action = "image hash init"
        with self._expect_mgr():
            try:
                if target:
                    self.__target_id_select(target, "for hashing")
                self.__send_command(
                    "read image",
                    'dump_image %s 0x%08x %d' % (tf_name, load_addr, size),
                    "dumped %d bytes" % size,
                    timeout)
                hash_object = hashlib.sha256()
            except self.error as e:
                self.log.error("can't read image for hashing: %s" % e)
                raise
        with open(tf_name, "r") as tf:
            for chunk in iter(lambda: tf.read(8 * 1024), b''):
                hash_object.update(chunk)
        return hash_object.hexdigest()

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
            if target_id == None:
                target_id = 0
            else:
                self.__target_id_select(target_id, for_what)
            # This doesn't give good output...
            self.__send_command(
                "halt target %d %s" % (target_id, for_what), "halt")
            # ... so we look for halted in the @targets output
            # ' 1* quark_se.arc-em  arc32   little quark_se.arc-em    halted'
            r = self.__send_command(
                "check target %d halted %s" % (target_id, for_what),
                "targets",
                [
                    re.compile(r" %d\* .*(halted|reset)" % target_id),
                    # Bug? it is not timing out, so we catch others here
                    re.compile(r" %d\* .*" % target_id),
                ])
            if r != 0:
                msg = "cannot halt target #%d for %s: got r = %d" \
                    % (target_id, for_what, r)
                self._log_error_output(msg)
                raise self.error(msg)
            return True
        except self.error:
            self.log.error("cannot halt target %d %s" % (target_id, for_what))
            raise

    def _target_halt(self, targets = None, for_what = ""):
        if not targets:
            targets = self.board['targets']
        elif isinstance(targets, str):
            targets = [ targets ]
        self.log.action = "target halt init"
        with self._expect_mgr():
            for target in targets:
                self.__target_id_halt(
                    self.addrmap[target].get('target_id', None),
                    for_what)

    def __target_reset_halt(self, for_what = "", command = "reset halt"):
        # this assumes we are inside a 'with self._expect_mgr():' block
        self.log.action = "target reset halt init"
        command = self.board.get('reset_halt_command', command)
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

    def _target_reset_halt(self, for_what = ""):
        # this assumes we are outside a 'with self._expect_mgr():' block
        with self._expect_mgr():
            return self.__target_reset_halt(for_what = for_what)

    def __target_reset(self, for_what = ""):
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

    def _target_reset(self, for_what = ""):
        self.log.action = "target reset init"
        # this assumes we are outside a 'with self._expect_mgr():' block
        with self._expect_mgr():
            return self.__target_reset(for_what = for_what)

    def __target_id_resume(self, target_id, for_what = ""):
        try:
            if target_id == None:
                target_id = 0
            else:
                self.__target_id_select(target_id, for_what)
            # This doesn't give good output...
            r = self.__send_command(
                "resume target %d %s" % (target_id, for_what),
                "resume",
                [
                    "",
                    "Target not halted",
                ])
            if r != 0:
                self._log_error_output()
                raise self.error("Cannot resume %s (r %d)" % (for_what, r))
            # ... so we'd look at targets output, but by the time we
            # look it might have transitioned to another state, so
            # we'll just pray it works...
        except self.error:
            self._log_error_output()
            self.log.error("cannot resume target %d %s"
                           % (target_id, for_what))
            raise

    def _target_resume(self, targets = None, for_what = ""):
        self.log.action = "target resume"
        with self._expect_mgr():
            if not targets:
                targets = reversed(self.board['targets'])
            elif isinstance(targets, str):
                targets = [ targets ]
            for target in targets:
                self.__target_id_resume(
                    self.addrmap[target].get('target_id', None),
                    for_what)

