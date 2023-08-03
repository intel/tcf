#! /usr/bin/python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to to manage tunnels to targets
---------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list serial consoles::

    $ tcf console-ls TARGETSPEC

- read a from a serial console::

    $ tcf console-read [-c CONSOLE] [-o FILE] TARGETSPEC

  keep reading as output comes::

    $ tcf console-read --follow [-c CONSOLE] [-o FILE] TARGETSPEC

- setup serial console::

    $ tcf console-setup [-c CONSOLENAME] TARGETSPEC VAR=VALUE [VAR=VALUE [...]]

  reset settings::

    $ tcf console-setup [-c CONSOLENAME] --reset TARGETSPEC

  print current settings::

    $ tcf console-setup [-c CONSOLENAME] TARGETSPEC [-v[v[v[v]]]]


"""

import argparse
import collections
import datetime
import errno
import logging
import math
import os
import sys
import threading
import time

import commonl
import tcfl.tc
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_console")


#
# This file is kinda larger than usual because of the implementation
# of the "terminal emulation" -- scroll down to the bottom for the
# _cmdline_*() that are the entry points for the CLI commands.
#

if sys.platform == "win32":

    def term_flags_get():
        return '\r', 0

    def term_flags_reset(flags):
        pass

    def term_raw_set():
        # FIXME: we need to figure this out
        pass

else:

    # these are fast imports, so no need to on demand-them
    import fcntl
    import termios
    import tty

    def term_flags_get():
        flags = termios.tcgetattr(sys.stdin.fileno())
        if flags[0] & termios.ICRNL:
            nl = '\r'
        else:
            nl = '\n'
        return nl, flags

    def term_flags_reset(flags):
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, flags)

    def term_raw_set():
        tty.setraw(sys.stdin.fileno())
        flags = fcntl.fcntl(sys.stdin.fileno(), fcntl.F_GETFD)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)




def f_write_retry_eagain(fd, data):
    while True:
        try:
            fd.write(data)
            return
        except IOError as e:
            # for those files opened in O_NONBLOCK
            # mode -- yep, prolly a bad idea -- as
            # non elegant as you can find it. But
            # otherwise 'tcf console-write -i' with a
            # large amount of data loose stuff--need
            # to properly root cause FIXME
            if e.errno == errno.EAGAIN:
                time.sleep(0.5)
                continue
            raise

_flags_set = None
_flags_old = None

class _console_reader_c:
    """
    :param bool rawmode: (optional; default *False*) operate the
      stream in raw mode.

      - *rawmode == False*:
         - do not process EOLs (convert CRLF to LF, etc)
         - do not report generation changes (power cycles) to stderr
    """
    def __init__(self, target, console, fd, offset,
                 backoff_wait_max, server_connection_errors_max,
                 timestamp = None, rawmode: bool = False):
        self.target = target
        self.console = console
        self.fd = fd
        self.offset = offset
        self.server_connection_errors = 0
        self.server_connection_errors_max = server_connection_errors_max
        self.backoff_wait = 0.1
        self.backoff_wait_max = backoff_wait_max
        self.generation_prev = None
        self.timestamp = timestamp
        self.rawmode = rawmode

    def read(self, flags_restore = None, timestamp = None):
        """
        :param bool timestamp:
        """
        data_len = 0

        if self.rawmode:

            generation, self.offset, data_len = \
                self.target.console.read_full(
                    self.console, self.offset,
                    # when reading, we are ok with retrying a lot, since
                    # this is an idempotent operation
                    fd = self.fd,
                    retry_backoff = self.backoff_wait,
                    retry_timeout = 60)
        else:
            # Instead of reading and sending directy to the
            # stdout, we need to break it up in chunks; the
            # console is in non-blocking mode (for reading
            # keystrokes) and also in raw mode, so it doesn't do
            # \n to \r\n xlation for us.
            # So we chunk it and add the \r ourselves; there might
            # be a better method to do this.
            generation, self.offset, data = \
                self.target.console.read_full(
                    self.console, self.offset,
                    # when reading, we are ok with retrying a lot, since
                    # this is an idempotent operation
                    retry_backoff = self.backoff_wait,
                    retry_timeout = 60)
            #print(f"DEBUG generation {generation} offset {self.offset}", file = sys.stderr)
            if self.generation_prev != None and self.generation_prev != generation:
                sys.stderr.write(
                    "\n\r\r\nWARNING: console was restarted\r\r\n\n")
                self.offset = len(data)
            self.generation_prev = generation

            if data:
                # add CR, because the console is in raw mode
                for line in data.splitlines(True):
                    # note line is strings, UTF-8 encode, which is
                    # what we get from the protocol
                    if self.timestamp:
                        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S ")
                        self.fd.write(timestamp.encode('utf-8'))
                    f_write_retry_eagain(self.fd, line.encode('utf-8'))
                    if '\n' in line:
                        f_write_retry_eagain(self.fd, b"\r")
            self.fd.flush()
            data_len = len(data)

        if data_len == 0:
            self.backoff_wait *= 2
        else:
            self.backoff_wait = 0.1
        # in interactive mode we want to limit the backoff to
        # one second so we have time to react
        if self.backoff_wait >= self.backoff_wait_max:
            self.backoff_wait = self.backoff_wait_max
        time.sleep(self.backoff_wait)	# no need to bombard the server..
        if self.server_connection_errors > 0:
            self.server_connection_errors = 0	# successful, restart the count
            self.backoff_wait = 0.1

        return data_len


def _console_read_thread_fn(target, console, fd, offset, backoff_wait_max,
                            _flags_restore, timestamp = False,
                            stop = None, rawmode = False):
    # read in the background the target's console output and print it
    # to stdout
    # stop: if it is an iterable and is not empty, stop reading
    offset = target.console.offset_calc(target, console, int(offset))
    with tcfl.msgid_c("cmdline"):
        # limit how much time we keep retrying due to server connection errors
        console_reader = _console_reader_c(target, console, fd, offset,
                                           backoff_wait_max, 10,
                                           timestamp = timestamp,
                                           rawmode = rawmode)
        while stop == None or len(stop) == 0:
            try:
                if stop and len(stop) > 0:
                    break
                console_reader.read(flags_restore = _flags_restore)
            except Exception as e:	# pylint: disable = broad-except
                if _flags_restore:
                    # We only restore when we error out
                    # need to do this before printing--otherwise it
                    # looks staricasey and it is a mess, hence why it
                    # is duplicated
                    term_flags_reset(_flags_restore)
                    _flags_restore = False
                logging.exception(e)
                #print(f"DEBUG reader exitt {e}", file = sys.stderr)
                raise
            finally:
                if _flags_set:
                    term_flags_reset(_flags_old)


if sys.platform.startswith("win"):
    #
    # Translate Windows scan codes to ANSI sequences
    #
    # Thanks to Michael Pratt's gist:
    #
    # https://gist.github.com/mpratt14/e732c474205b317af053a9b14df211bc
    #
    # SPDX-License-Identifier: (GPL-2.0-only OR Apache-2.0)
    #
    # Signed-off-by: Michael Pratt <mcpratt@pm.me>
    #
    # Windows function key scan codes to ANSI escape code dictionary:
    # Pause/Break, Ctrl+Alt+Del, Ctrl+Alt+arrows not mapable
    # Input: ordinal of char from msvcrt.getch()
    # Output: bytes string of ANSI escape sequence for linux/xterm
    #        numerical used over linux specifics for Home and End
    #        VT or CSI escape sequences used when linux has no sequence
    #        something unique for keys without an escape function
    # \x1b == Escape key

    winfnkeys = {
            #Ctrl + Alt + Backspace
            14:     b'\x1b^H',
            #Ctrl + Alt + Enter
            28:     b'\x1b\r',
            # Pause/Break
            29:     b'\x1c',
            # Arrows
            72:     b'\x1b[A',
            80:     b'\x1b[B',
            77:     b'\x1b[C',
            75:     b'\x1b[D',
            # Arrows (Alt)
            152:    b'\x1b[1;3A',
            160:    b'\x1b[1;3B',
            157:    b'\x1b[1;3C',
            155:    b'\x1b[1;3D',
            # Arrows (Ctrl)
            141:    b'\x1b[1;5A',
            145:    b'\x1b[1;5B',
            116:    b'\x1b[1;5C',
            115:    b'\x1b[1;5D',
            #Ctrl + Tab
            148:    b'\x1b[2J',
            # Cursor (Home, Ins, Del...)
            71:     b'\x1b[1~',
            82:     b'\x1b[2~',
            83:     b'\x1b[3~',
            79:     b'\x1b[4~',
            73:     b'\x1b[5~',
            81:     b'\x1b[6~',
            # Cursor + Alt
            151:    b'\x1b[1;3~',
            162:    b'\x1b[2;3~',
            163:    b'\x1b[3;3~',
            159:    b'\x1b[4;3~',
            153:    b'\x1b[5;3~',
            161:    b'\x1b[6;3~',
            # Cursor + Ctrl (xterm)
            119:    b'\x1b[1;5H',
            146:    b'\x1b[2;5~',
            147:    b'\x1b[3;5~',
            117:    b'\x1b[1;5F',
            134:    b'\x1b[5;5~',
            118:    b'\x1b[6;5~',
            # Function Keys (F1 - F12)
            59:     b'\x1b[11~',
            60:     b'\x1b[12~',
            61:     b'\x1b[13~',
            62:     b'\x1b[14~',
            63:     b'\x1b[15~',
            64:     b'\x1b[17~',
            65:     b'\x1b[18~',
            66:     b'\x1b[19~',
            67:     b'\x1b[20~',
            68:     b'\x1b[21~',
            133:    b'\x1b[23~',
            134:    b'\x1b[24~',
            # Function Keys + Shift (F11 - F22)
            84:     b'\x1b[23;2~',
            85:     b'\x1b[24;2~',
            86:     b'\x1b[25~',
            87:     b'\x1b[26~',
            88:     b'\x1b[28~',
            89:     b'\x1b[29~',
            90:     b'\x1b[31~',
            91:     b'\x1b[32~',
            92:     b'\x1b[33~',
            93:     b'\x1b[34~',
            135:    b'\x1b[20;2~',
            136:    b'\x1b[21;2~',
            # Function Keys + Ctrl (xterm)
            94:     b'\x1bOP',
            95:     b'\x1bOQ',
            96:     b'\x1bOR',
            97:     b'\x1bOS',
            98:     b'\x1b[15;2~',
            99:     b'\x1b[17;2~',
            100:    b'\x1b[18;2~',
            101:    b'\x1b[19;2~',
            102:    b'\x1b[20;3~',
            103:    b'\x1b[21;3~',
            137:    b'\x1b[23;3~',
            138:    b'\x1b[24;3~',
            # Function Keys + Alt (xterm)
            104:    b'\x1b[11;5~',
            105:    b'\x1b[12;5~',
            106:    b'\x1b[13;5~',
            107:    b'\x1b[14;5~',
            108:    b'\x1b[15;5~',
            109:    b'\x1b[17;5~',
            110:    b'\x1b[18;5~',
            111:    b'\x1b[19;5~',
            112:    b'\x1b[20;5~',
            113:    b'\x1b[21;5~',
            139:    b'\x1b[23;5~',
            140:    b'\x1b[24;5~',
    }



def _cmdline_console_write_interactive(target, console, crlf,
                                       offset, max_backoff_wait,
                                       windows_use_msvcrt = False,
                                       press_enter = True):

    #
    # Poor mans interactive console
    #
    # spawn a background reader thread to print the console output,
    # capture user's keyboard input and send it to the target.
    #
    # This is harder than it seems
    #
    # - the read thread just reads in a loop and prints to standard
    #   output; however
    #
    #   - the standard output needs to be set to unbuffered mode, so
    #     nothing waits for a CR/LF or both to print a whole string
    #
    #   - for anything supporting enhanced console (cursor moving,
    #     clear screen, position text, colors...) the standard output
    #     must be hanled by a virtual terminal (a descendant of vt100)
    #     This code doesn't do the terminal emulation bit.
    #
    #     Most Unix/Linux/MAC(?) terminal windows do it, interpreting
    #     ANSI sequences (eg: <ESC>[J clears the screen.
    #
    #     Windows didn't until ~10? and still it has to be
    #     enabled [see colorama.init() below].
    #
    # - input is tricky:
    #
    #   - In Linux/Unix/Mac it is easy; just read from standard input,
    #     pass it to the other end and let it handle it.
    #
    #     When both ends are Unixy, ANSI sequences (ASCII) are passed
    #     to the other side, which correctly interprets them and magic
    #     happens.
    #
    #   - In Windows, the default Windows command prompt and everybody
    #     else doesn't work like that.
    #
    #     - if reading from sys.stdin, there is a window-specific
    #       (windows command prompt, PS window, Windows Terminal) semi
    #       half baked attempt at line editing that seems to work when
    #       you are doing command line, but it is all illusion. If you
    #       try to use a visual editor, the cursor keys won't work and
    #       it tries to do line editing of what you typed. A mess
    #
    #     - the thing is to use the MSVCRT functions to get key
    #       presses, which gives you...scan codes. And scan codes need
    #       to be converted to ANSI sequences if you want the other
    #       side to understand them. Which we do because lingua
    #       franca.
    #
    #       Not sure what virtual terminal rendering standard happens
    #       when you SSH into windows anyway.
    #
    #
    # - newlines: are (not) fun; each system has their own standard;
    #   lines are ended with
    #
    #   - CR 0x0d \r: carriage return (most Unixish, Windows with msvcrt)
    #
    #   - NL 0x0a \n: new line
    #
    #   - CR+NL (windows with sys.stdin)
    #
    # So when we read from the input device, we need to recognize the
    # input convention for the local system (newline_input), convert
    # it to the remote (crlf, which comes from the inventory or
    # command line)--if we want it transparent, well specify no crlf.

    # We do all data collection in bytes
    if isinstance(crlf, str):
        crlf = crlf.encode('utf-8', errors = 'surrogateescape')
    else:
        assert isinstance(crlf, bytes), "crlf: must be bytes or str, got {type(str)}"

    # ok, depending on where this is running, what kind of terminal
    # emulator, we are going to get input on one way or another, so
    # here is to those settings

    if 'INSIDE_EMACS' in os.environ:
	# running inside an emacs shell
        #
        # I've given up -- I can't figure out how to ask stty to
        # tell me emacs does \n
        windows = False
        windows_use_msvcrt = False
        if sys.platform.startswith("win"):
            newline_input = b'\r\n'
        else:
            newline_input = b'\n'
        quit_sequence = "C-q ESC C-q ESC ENTER in rapid sequence"

    elif sys.platform.startswith("win"):

        # Using a windows terminal prompt / powershell window
        if windows_use_msvcrt:
            # using msvcrt.getwch()
            #
            #   - arrows don't work (not VT translated?) -> FIXME need
            #     xlation to ANSI sequences
            #
            #   - getch() unicode chars (accented a, eg) don't come
            #     in, so we use getwch()
            newline_input = b"\r"		# Windows, when reading with msvcrt
            import msvcrt

        else:
            # Using sys.stdin to read in Windows:
            #
            #   - Ctrl-C, ESC ESC works meh
            #
            #   - arrows work, but it is because the terminal app is
            #     doing the editing, so the arrows won't work on
            #     editors like vi; the line editing behaviour is
            #     happening in Windows and then it doesn't work properly.
            newline_input = b"\r\n"		# Windows, when reading with sys.stdin

        windows = True
        quit_sequence = "ESC ESC or Control-C four times in rapid sequence"

        # Initialize virtual terminal functionality in Windows (10) --
        # this is needed so that ANSI escape sequences are recognized
        # in the windows prompt
        import colorama
        colorama.init()
        # This hack seems to be working way better at enbling VT mode
        # than colorama.init() for cmd window, PS window, terminal
        # I am sure there is a better way, but they seem to require a lot of work
        # https://stackoverflow.com/questions/51091680/activating-vt100-via-os-system
        os.system('')
        # Clear the screen -- needed because in Windows the
        # "terminals" don't auto-scroll like in Linux and...then
        # things look weird if we are at the bottom of the screen
        print(colorama.ansi.clear_screen())


    else:
        # most Unix platforms

        newline_input = b"\r"
        windows = False
        windows_use_msvcrt = False
        quit_sequence = "ESC twice in rapid sequence"


    # Print a warning banner
    if not windows:
        print("""
WARNING: This is a very limited interactive console

    To exit: %s.
    [console '%s', CRLF input %s output %s]

"""
                  % (quit_sequence, console, repr(newline_input), repr(crlf)))

    else:

        print("""
WARNING: Running 'console-write -i' under MS Windows

   MS Windows terminals lack features needed to properly emulate consoles.
   Cursor control, escape sequences, function keys, etc might not work.
   It is recommended to run on a Linux terminal (WSL or native)

   To exit: %s.
   [console '%s', CRLF input %s output %s]

"""
                  % (quit_sequence, console, repr(newline_input), repr(crlf)))

    # wait for user to acknowledge
    if press_enter:
        input("Press [enter] to continue <<<<<<")

    class _done_c(Exception):
        pass

    # ask the terminal what does it consider a line feed and current
    # flags; save them so we can restore them on the way out (linux
    # only)
    nl, _flags_old = term_flags_get()
    if sys.stdin.isatty():
        _flags_set = True
    else:
        _flags_set = False
    try:
        one_escape = False
        if _flags_set:
            term_raw_set()

        # let the read thread loose
        fd = os.fdopen(sys.stdout.fileno(), "wb")
        console_read_thread = threading.Thread(
            target = _console_read_thread_fn,
            args = ( target, console, fd, offset, max_backoff_wait,
                     _flags_old ),
            kwargs = { "rawmode": False }
        )
        console_read_thread.daemon = True
        console_read_thread.start()

        newline_sequence = b""  # track a newline sequence being received
        chars = b""             # what characters have been received so far
        cancel_chars = 0	# How many Ctrl-Cs in sequence have been received

        def _translate(chars):
            # translates the chars sequence
            # - replace input newline [newline_input] sequence with output's [crlf]
            # - detect double escape (and abort)
            # - convert to UTF-8 string
            nonlocal crlf
            nonlocal newline_input
            nonlocal newline_sequence
            nonlocal one_escape
            #print(f"DEBUG translating {chars}", file = sys.stderr)
            _chars = b""
            for char_int in chars:
                char = bytes([ char_int ])   # why iteration is converting it to an int, unknown
                #print(f"DEBUG for loop checking {type(char)} {char}", file = sys.stderr)
                if char == b'\x1b':
                    if one_escape:
                        raise _done_c()
                    one_escape = True
                else:
                    one_escape = False
                # newline detection logic (conver input newline convention to output; disable with crlf == None)
                if crlf and char_int == newline_input[len(newline_sequence)]:
                    # this char matches the sequence of input newline
                    # characters, accumulate and move on--unless we
                    # complete the sequence, then translate it, reset
                    # and move on
                    newline_sequence += char
                    #print(f"DEBUG newline detecting at {newline_sequence}", file = sys.stderr)
                    if newline_sequence == newline_input:
                        _chars += crlf
                        newline_sequence = b""
                    continue
		# we don't match the newline detector, accumulate and reset the detector
                _chars += char
                newline_sequence = b""

            #print(f"DEBUG translated {_chars}", file = sys.stderr)
            return _chars.decode('utf-8', errors = "surrogateescape")

        # our basic loop -- note we get user input as long as we are
        # reading, so if the read thread dies, we stop too.
        #
        # we'll get input depending on the platform (windows w/ msvcrt
        # or sys.stdin, linux with stdin), which will give us scan
        # codes or ANSI escape sequences when dealing with civilized
        # systems. If it is scan codes, we need to translate. We also
        # translate newline conventions from the input system (where
        # we run) to the destination system [crlf argument].
        #
        # Tricky: Ctrl-C -- each system does it in a slightly
        # different way; so in general we catch KeyboardInterrupt
        # exceptions mostly everywhere, conver them to \x03 and if
        # four in a row are recevied, we re-raise. Whenever we see one
        # of those, BTW, we need to transmit right away to flush the
        # pipeline. Mind you, outer KeyboardInterrupt excepts might be
        # catching the inner one
        #
        # Note before sending the input, it has to be _translate()d
        while console_read_thread.is_alive():
            # the transport plane takes UTF-8 and accepts
            # surrogateencoding for bytes > 128 (U+DC80 - U+DCFF) see
            # Python's PEP383.
            try:
                # Take some user input.

                # In general, read no more than 30 chars -- this is
                # meant mostly for interactive use; rarely someone
                # types more than 30chars that fast
                if windows_use_msvcrt:
                    try:
                        # keep reading until we don't -- getch() is
                        # blocking and it is more responsive to block
                        # and check than to check and read
                        while len(chars) < 30:
                            # special chars (arrows, fn keys...) are
                            # going to come as 0x0 <CODE> or 0xe0
                            # <CODE>, so if we detect one of this,
                            # read a second char and if it is in the
                            # translation table, translate it,
                            # otherwise just append it
                            c = msvcrt.getwch()
                            if c in ( '\x00', '\xe0' ):
                                c2 = msvcrt.getwch()
                                c2_ord = ord(c2[0])
                                if c2_ord in winfnkeys:
                                    # xlate https://gist.github.com/mpratt14/e732c474205b317af053a9b14df211bc
                                    c2 = winfnkeys[c2_ord]
                                    chars += c2
                                else:
                                    chars += c
                                    chars += c2
                            else:
                                chars += c.encode('utf-8')
                            if not msvcrt.kbhit():
                                break
                    except KeyboardInterrupt as e:
                        chars += b'\x03'
                else:
                    chars += os.read(sys.stdin.fileno(), 30)
                #print(f'DEBUG sending standard {chars}', file = sys.stderr)
                target.console.write(_translate(chars), console = console)
                chars = b""
                cancel_chars = 0
            except _done_c:			# thrown by _translate on ESC-ESC
                break
            except KeyboardInterrupt as e:
                chars += b'\x03'
                cancel_chars += 1
                #print(f'DEBUG sending top level interrupt {chars}', file = sys.stderr)
                if cancel_chars > 4:
                    raise
                target.console.write(_translate(chars), console = console)
                chars = b""
                cancel_chars = 0
            except IOError as e:
                if e.errno != errno.EAGAIN:
                    raise
            # If no data ready, wait a wee, try again
            if not windows_use_msvcrt:
                try:
                    time.sleep(0.1)
                except KeyboardInterrupt as e:
                    #print(f"DEBUG on sleep interrupt")
                    chars += b'\x03'
                    cancel_chars += 1
                    if cancel_chars > 4:
                        raise
                    #print(f'DEBUG sending sleep interrupt {chars}', file = sys.stderr)
                    target.console.write(_translate(chars), console = console)
                    chars = b""
                    cancel_chars = 0
    finally:
        if _flags_set:
            term_flags_reset(_flags_old)



def _console_write(target, console: str,
                   data: list,	# COMPAT: pre3.8, not using list[str]
                   offset: int, crlf: str, max_backoff_wait: int,
                   interactive: bool, press_enter: bool, msvcrt: bool):
    if offset == None:
        # if interactive, give us just a little bit of the
        # previous output; all of it becomes really confusing;
        # none also...so just a little.
        if interactive:
            offset = -300
        else:
            offset = 0
    if console == None:
        console = target.console.default
    # _console_get() translates aliases into a real console name
    console = target.console._console_get(console)
    if crlf == None:
        # get the CRLF the server says, otherwise default to \n,
        # which seems to work best for most
        crlf = target.rt['interfaces']['console']\
            [console].get('crlf', "\n")
    if interactive:
        _cmdline_console_write_interactive(
            target, console, crlf, offset, max_backoff_wait,
            windows_use_msvcrt = msvcrt, press_enter = press_enter)
    elif data == []:	# no data given, so get from stdin
        import getpass
        while True:
            line = getpass.getpass("")
            if line:
                # FIXME: this is attemptring to strip \r\n, but is
                # also taking spacing...
                target.console.write(line.rstrip() + crlf, console)
    else:
        for line in data:
            target.console.write(line + crlf, console)

def _cmdline_console_write(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_write, cli_args,
        cli_args.console, cli_args.data,
        cli_args.offset, cli_args.crlf, cli_args.max_backoff_wait,
        cli_args.interactive, cli_args.press_enter, cli_args.msvcrt,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _console_read(target, console: str, offset: int, output: str,
                  follow: bool, max_backoff_wait: int, timestamp: bool):
    console = target.console._console_get(console)
    offset = target.console.offset_calc(target, console, offset)
    if output == None:
        fd = sys.stdout.buffer
        rawmode = False
    else:
        fd = open(output, "wb")
        rawmode = True
    try:
        # limit how much time we keep retrying due to server connection errors
        if follow:
            _console_read_thread_fn(target, console, fd, offset,
                                    max_backoff_wait, False,
                                    timestamp = timestamp,
                                    rawmode = rawmode)
        else:
            console_reader = _console_reader_c(
                target, console, fd, offset,
                max_backoff_wait, 10, timestamp = timestamp,
                rawmode = rawmode)
            console_reader.read()
    finally:
        if fd != sys.stdout.buffer:
            fd.close()

def _cmdline_console_read(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_read, cli_args,
        cli_args.console, cli_args.offset, cli_args.output, cli_args.follow,
        cli_args.max_backoff_wait, cli_args.timestamp,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _cmdline_console_wall(cli_args: argparse.Namespace):
    verbosity = cli_args.verbosity - cli_args.quietosity
    # for all the targets in args.targets, query the consoles they
    # offer and display them in a grid in the current terminal using
    # GNU screen to divide it in a mesh of sub-windows; then keep
    # updating each window with the console's output

    if cli_args.name == None:
        if cli_args.target == []:
            cli_args.name = "TCF Wall"
        else:
            cli_args.name = "TCF Wall: " + " ".join(cli_args.target)

    # for each target/console, create a console_descr_c object,
    # which will keep the state of the console reading now.
    class console_descr_c(object):
        def __init__(self):
            self.fd = None
            self.write_name = None
            self.generation = None
            self.offset = 0
            self.backoff_wait = 0.1
            self.target = None
            self.console = None

    tcfl.targets.setup_by_spec(
        cli_args.target, verbosity = verbosity,
        targets_all = cli_args.all,
        project = {
            'id', 'disabled', 'type', 'interfaces.console',
        })
    targets = {}
    consolel = collections.defaultdict(console_descr_c)
    for targetid in tcfl.targets.discovery_agent.rts_fullid_sorted:
        targets[targetid] = target = tcfl.tc.target_c.create(
            targetid,
            iface = "console", extensions_only = [ "console" ],
            target_discovery_agent = tcfl.targets.discovery_agent)

        for console in target.console.console_list:
            if console in target.console.aliases:
                continue
            if cli_args.console and console not in cli_args.console:
                continue
            name = target.fullid + "|" + console
            consolel[name].target = target
            consolel[name].console = console
            print("Collected info for console " + name)

    if not consolel:
        print("No targets supporting console interface found")
        return

    # Compute how many rows and columns we'll need to host all the
    # consoles
    if cli_args.rows and cli_args.columns:
        raise RuntimeError("can't specify rows and columns")
    if cli_args.rows != None:
        rows = cli_args.rows
        columns = (len(consolel) + rows - 1) // rows
    elif cli_args.columns != None:
        columns = cli_args.columns
        rows = len(consolel) // cli_args.columns
    else:
        rows = int(math.sqrt(len(consolel)))
        columns = (len(consolel) + rows - 1) // rows

    # Write the GNU screen config file that will divide the window
    # in sub-windows (screens in GNU screen parlance and run the
    # console-reading script on each.
    #
    # do not chdir somehwere else, as we rely on the
    # configuration being here
    cf_name = os.path.join(tcfl.tc.tc_c.tmpdir, "screen.rc")

    with open(cf_name, "w") as cf:
        cf.write('# %d rows, %d columns\n'
                 'hardstatus on\n'
                 'hardstatus string "%%S"\n' % (rows, columns))
        for _row in range(rows - 1):
            cf.write('split\n')
        cf.write('focus top\n')

        console_names = sorted(consolel.keys())
        item_iter = iter(console_names)
        done = False
        for _row in range(rows):
            for col in range(columns):
                try:
                    item = next(item_iter)
                except StopIteration:
                    done = True
                descr = consolel[item]
                if cli_args.interactive:
                    subcommand = "console-write -i --disable-press-enter"
                else:
                    subcommand = "console-read --follow"
                # we add -a since at this point we know we NEED the
                # unit and if it is disabled, that's ok
                cf.write(
                    'screen -c %s %s %s'
                    ' --max-backoff-wait %f -a -c %s\n'
                    'title %s\n\n' % (
                        sys.argv[0], subcommand,
                        descr.target.fullid, cli_args.max_backoff_wait, descr.console, item
                    ))
                if done or item == console_names[-1]:
                    break
                if col == columns - 1:
                    cf.write("focus down\n")
                else:
                    cf.write('split -v\n'
                             'focus right\n')
            if done:
                break
        cf.flush()

    # exec screen
    #
    # So now this is a really dirty hack; FIXME; this needs to
    # evolve to have screen either:
    #
    # - tail -f a file per target/console in the tmpdir
    # - socat a pipe per target/console in the tmpdir (socat PTY,link=%s)
    # and then have a bunch of threads in the tcf console-wall
    # process update those
    #
    # but then it makes sense to leave the tcf process in the
    # foreground so it is easy to Ctrl-C it and it removes the
    # tmpdir; screen doesn't need control, but it doesn't like not
    # being started in a controlly tty.
    os.execvp("screen", [ "screen", "-c", cf.name, "-S", cli_args.name ])



def _console_ls(target):
    for console in target.console.list():
        if console in target.console.aliases:
            real_name = "|" + target.console.aliases[console]
        else:
            real_name = ""
        size = target.console.size(console)
        if size != None:
            print("%s%s: %d" % (console, real_name, size))
        else:
            print("%s%s: disabled" % (console, real_name))


def _cmdline_console_ls(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_ls, cli_args,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _console_disable(target, console):
    target.console.disable(console)

def _cmdline_console_disable(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_disable, cli_args, cli_args.console,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _console_enable(target, console):
    target.console.enable(console)

def _cmdline_console_enable(cli_args: argparse.Namespace):

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_enable, cli_args, cli_args.console,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _console_setup(target, console: str, reset: bool, cli_parameters,
                   verbosity: int):

    if reset:
        logger.info("%s: reseting settings for console %s",
                    target.id, console)
        r = target.console.setup(console)

    elif cli_parameters == []:
        logger.info("%s: getting settings for console %s",
                    target.id, console)
        r = target.console.setup_get(console)

        if verbosity in ( 0, 1 ):
            for key, value in r.items():
                print(f"{key}: {value}")
        elif verbosity == 2:
            commonl.data_dump_recursive(r)
        elif verbosity == 3:
            import pprint		# pylint: disable = import-outside-toplevel
            pprint.pprint(r, indent = True)
        elif verbosity > 3:
            import json		# pylint: disable = import-outside-toplevel
            json.dump(r, sys.stdout, skipkeys = True, indent = 4)
            print()

        r = 0

    else:
        import pprint
        parameters = {}
        for parameter in cli_parameters:
            if '=' in parameter:
                key, value = parameter.split("=", 1)
                value = commonl.cmdline_str_to_value(value)
            else:
                key = parameter
                value = True
            parameters[key] = value
        logger.info("%s: applying settings for console %s: %s",
                    target.id, console, pprint.pformat(parameters))
        target.console.setup(console, **parameters)

    return 0


def _cmdline_console_setup(cli_args: argparse.Namespace):

    verbosity = cli_args.verbosity - cli_args.quietosity

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _console_setup, cli_args,
        cli_args.console, cli_args.reset, cli_args.parameters, verbosity,
        only_one = True,
        iface = "console", extensions_only = [ "console" ])



def _cmdline_setup(arg_subparser):
    ap = arg_subparser.add_parser(
        "console-ls",
        help = "list consoles this target exposes")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.set_defaults(func = _cmdline_console_ls)


    ap = arg_subparser.add_parser(
        "console-read",
        help = "Read from a target's console (pipe to `cat -A` to"
        " remove control chars")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "-s", "--offset", action = "store",
        dest = "offset", type = int,
        help = "Read the console output starting from "
        "offset (some targets might or not support this)")
    ap.add_argument(
        "-o", "--output", action = "store", default = None,
        metavar = "FILENAME",
        help = "Write output to FILENAME")
    ap.add_argument(
        "--console", "-c", metavar = "CONSOLE",
        action = "store", default = None,
        help = "Console to read from")
    ap.add_argument(
        "--follow",
        action = "store_true", default = False,
        help = "Continue reading in a loop until Ctrl-C is "
        "pressed")
    ap.add_argument(
        "--timestamp",
        action = "store_true", default = False,
        help = "Add a client-side UTC timestamp to the"
        " beginning of each line (this timestamp reflects"
        " when the data was read)")
    ap.add_argument(
        "--max-backoff-wait",
        action = "store", type = float, metavar = "SECONDS", default = 2,
        help = "Maximum number of seconds to backoff wait for"
        " data (%(default)ss)")
    ap.set_defaults(func = _cmdline_console_read, offset = 0)

    ap = arg_subparser.add_parser(
        "console-write",
        help = "Write to a target's console")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "--console", "-c", metavar = "CONSOLE",
        action = "store", default = None,
        help = "Console to write to")
    ap.add_argument(
        "--interactive", "-i",
        action = "store_true", default = False,
        help = "Print back responses")
    ap.add_argument(
        "--disable-press-enter",
        dest = "press_enter",
        action = "store_false", default = True,
        help = "Require pressing enter before starting"
        " (to force reading the informational message)")
    ap.add_argument(
        "--msvcrt",
        action = "store_true", default = True,
        help = "On Windows, use MSVCRT's getch()"
        " function for key input; this makes somethings"
        " better, others not--check source code for details")
    ap.add_argument(
        "--local-echo", "-e",
        action = "store_true", default = True,
        help = "Do local echo (%(default)s)")
    ap.add_argument(
        "--no-local-echo", "-E",
        action = "store_false", default = True,
        help = "Do not local echo (%(default)s)")
    ap.add_argument(
        "-r", dest = "crlf",
        action = "store_const", const = "\r",
        help = "end lines with \\r")
    ap.add_argument(
        "-n", dest = "crlf",
        action = "store_const", const = "\n",
        help = "end lines with \\n"
        " (defaults to this if the server does not declare "
        " the interfaces.console.CONSOLE.crlf property)")
    ap.add_argument(
        "-R", dest = "crlf",
        action = "store_const", const = "\r\n",
        help = "end lines with \\r\\n")
    ap.add_argument(
        "-N", dest = "crlf",
        action = "store_const", const = "",
        help = "Don't add any CRLF to lines")
    ap.add_argument(
        "data", metavar = "DATA",
        action = "store", default = None, nargs = '*',
        help = "Data to write; if none given, "
        "read from stdin")
    ap.add_argument(
        "-s", "--offset", action = "store",
        dest = "offset", type = int, default = None,
        help = "read the console from the given offset, "
        " negative to start from the end, -1 for last"
        " (defaults to 0 or -1 if -i is active)")
    ap.add_argument(
        "--max-backoff-wait",
        action = "store", type = float, metavar = "SECONDS", default = 2,
        help = "Maximum number of seconds to backoff wait for"
        " data (%(default)ss)")
    ap.set_defaults(func = _cmdline_console_write, crlf = None)

    def _check_positive(value):
        try:
            value = int(value)
        except TypeError as e:
            raise argparse.ArgumentTypeError(
                f"{value}: expected integer; got {type(value)}") from e
        if not value > 0:
            raise argparse.ArgumentTypeError(
                f"{value}: expected non-zero positive integer")
        return value

    ap = arg_subparser.add_parser(
        "console-wall",
        help = "Display multiple serial consoles in a tiled terminal"
        " window using GNU screen (type 'Ctrl-a : quit' to stop it)")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "--name", "-n", metavar = "NAME",
        action = "store", default = None,
        help = "name to set for this wall (defaults to "
        "the target specification")
    ap.add_argument(
        "--rows", "-r", metavar = "ROWS",
        action = "store", type = _check_positive, default = None,
        help = "fix rows to ROWS (default auto)"
        " incompatible with -o|--columns")
    ap.add_argument(
        "--columns", "-o", metavar = "COLUMNS",
        action = "store", type = int, default = None,
        help = "fix rows to COLUMNS (default auto);"
        " incompatible with -r|--rows")
    ap.add_argument(
        "-c", "--console", metavar = "CONSOLE",
        action = "append", default = None,
        help = "Read only from the named consoles (default: all)")
    ap.add_argument(
        "--interactive", "-i",
        action = "store_true", default = False,
        help = "Start interactive console instead of just reading")
    ap.add_argument(
        "--max-backoff-wait",
        action = "store", type = float, metavar = "SECONDS", default = 2,
        help = "Maximum number of seconds to backoff wait for"
        " data (%(default)ss)")
    ap.set_defaults(func = _cmdline_console_wall)



def _cmdline_setup_advanced(arg_subparser):

    ap = arg_subparser.add_parser(
        "console-disable",
        help = "Disable a console")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "-c", "--console", metavar = "CONSOLE",
        action = "store", default = None,
        help = "name of console to disable")
    ap.set_defaults(func = _cmdline_console_disable)

    ap = arg_subparser.add_parser(
        "console-enable",
        help = "Enable a console")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "-c", "--console", metavar = "CONSOLE",
        action = "store", default = None,
        help = "name of console to enable")
    ap.set_defaults(func = _cmdline_console_enable)

    ap = arg_subparser.add_parser(
        "console-setup",
        help = "Setup a console")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, targetspec_n = 1)
    ap.add_argument(
        "-c", "--console", metavar = "CONSOLE",
        action = "store", default = None,
        help = "name of console to setup (default console if not specified")
    ap.add_argument(
        "--reset", "-r",
        action = "store_true", default = False,
        help = "reset to default values")
    ap.add_argument(
        "parameters", metavar = "KEY=[TYPE:]VALUE", nargs = "*",
        help = "Parameters to set in KEY=[TYPE:]VALUE format; "
        "TYPE can be b(ool), i(nteger), f(loat), s(string), "
        " defaulting to string if not specified")
    ap.set_defaults(func = _cmdline_console_setup)
