#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Raw access to the target's serial consoles
------------------------------------------

This exposes APIs to interface with the target's serial consoles and
the hookups for accessing them form the command line.
"""

import contextlib
import curses.ascii
import errno
import fcntl
import getpass
import logging
import mmap
import os
import re
import sys
import termios
import threading
import time
import traceback
import tty

import requests

import commonl

import tc
from . import msgid_c

def _poll_context(target, console):
    # we are polling from target with role TARGET.WANT_NAME from
    # it's console CONSOLE, so this is our context, so anyone
    # who will capture from that reuses the capture.
    # Note we also use this for naming the collateral file
    return '%s.%s.%s' % (target.want_name, target.id,
                         console if console else "default")

class expect_text_on_console_c(tc.expectation_c):
    """
    Object that expectes to find a string or regex in a target's
    serial console.

    See parameter description in builder :meth:`console.expect_text`
    """
    def __init__(self,
                 text_or_regex,
                 console = None,	# default
                 poll_period = 1,
                 timeout = 30,
                 previous_max = 4096,
                 raise_on_timeout = tc.failed_e,
                 raise_on_found = None,
                 name = None,
                 target = None):
        assert isinstance(target, tc.target_c)	# mandatory
        assert isinstance(text_or_regex, (basestring, re._pattern_type))
        assert console == None or isinstance(console, basestring)
        assert timeout == None or timeout >= 0
        assert poll_period > 0
        assert previous_max > 0
        tc.expectation_c.__init__(self, target, poll_period, timeout,
                                  raise_on_timeout = raise_on_timeout,
                                  raise_on_found = raise_on_found)
        assert name == None or isinstance(name, basestring)

        if isinstance(text_or_regex, basestring):
            self.regex = re.compile(re.escape(text_or_regex),
                                    re.MULTILINE)
        elif isinstance(text_or_regex, re._pattern_type):
            self.regex = text_or_regex
        else:
            raise AssertionError(
                "text_or_regex must be a string or compiled regex, got %s" \
                % type(text_or_regex).__name__)
        if name:
            self.name = name
        else:
            # this might get hairy when a regex is just regex that all
            # gets escaped out (looking like _______________). oh well
            self.name = commonl.name_make_safe(self.regex.pattern)

        self.console = console
        if console:
            self.console_name = console
        else:
            self.console_name = "default"
        self.previous_max = previous_max

    #: Maximum amonut of bytes to read on each read iteration in
    #: :meth:`poll`; this is so that if a (broken) target is spewing
    #: gigabytes of data, we don't get stuck here just reading from it.
    max_size = 65536
        
    def poll_context(self):
        return _poll_context(self.target, self.console)

    def _poll_init(self, testcase, run_name, buffers_poll):
        # NOTE: this is called with target.lock held

        target = self.target
        filename = buffers_poll.get('filename', None)
        if filename:
            target.report_info(
                "%s/%s: existing console capture context %08x/%s" %
                (run_name, self.name, id(buffers_poll), filename), dlevel = 5)
            return	# polling is initialized!
        # this means we never started reading
        #
        # there will be only a single reader state per testcase,
        # no matter how many expectations are pointed to a
        # target's console--see poll() for how we get there.
        #
        # so then, remove the existing collateral file, register it
        filename = target.console.capture_filename(console = self.console)

        with testcase.lock:
            testcase.collateral.add(filename)
        # rename any existing file, we are starting from scratch
        target.report_info(
            "%s/%s: new console capture context %08x/%s" %
            (run_name, self.name, id(buffers_poll), filename), dlevel = 5)
        commonl.rm_f(filename)
        buffers_poll['filename'] = filename

        # how much do we care on previous history? no good way to
        # tell, so we set a sensible default we can alter
        # also, the target could put more data out before we start
        # reading, so this is just an approx
        read_offset = target.console.size()
        if read_offset > self.previous_max:
            read_offset -= self.previous_max
        buffers_poll['read_offset'] = read_offset

        of = open(filename, "a+", 0)
        buffers_poll['of'] = of
        buffers_poll['ofd'] = of.fileno()


    def _poll(self, testcase, run_name, buffers_poll):
        # NOTE: this is called with target.lock held
        target = self.target

        # polling a console happens by reading the remote console into
        # a local file we keep as collateral
        self._poll_init(testcase, run_name, buffers_poll)
        read_offset = buffers_poll['read_offset']
        console_size = target.console.size(self.console)
        # If the target has rebooted, then the console file was
        # truncated to zero and our read offsets changed
        if console_size < read_offset:
            # FIXME: this is a hack until we have a session count
            # here, which monotonically increases in the server each
            # time the thing reboots. Ideally it will be returned as part of
            # read() and size()
            target.report_info(
                "%s/%s: target rebooted (console size %d < read offset %d)"
                " resetting read offset to zero"
                % (run_name, self.name, console_size, read_offset),
                dlevel = 3)
            read_offset = 0
        of = buffers_poll['of']
        ofd = buffers_poll['ofd']

        try:
            ts_start = time.time()
            target.report_info(
                "%s/%s: reading from console %s:%s @%d on %.2fs to %s"
                % (run_name, self.name, target.fullid, self.console_name,
                   read_offset, ts_start, of.name), dlevel = 5)
            # We are dealing with a file as our buffering and accounting
            # system, so because read_to_fd() is bypassing caching, flush
            # first and sync after the read.
            of.flush()
            total_bytes = target.rtb.rest_tb_target_console_read_to_fd(
                ofd, target.rt, self.console,
                read_offset, self.max_size, target.ticket)
            ts_end = time.time()
            of.flush()
            os.fsync(ofd)
            buffers_poll['read_offset'] = read_offset + total_bytes
            target.report_info(
                "%s/%s: read from console %s:%s @%d %dB (total %dB) "
                "on %.2fs (%.2fs) to %s"
                % (run_name, self.name, target.fullid, self.console_name,
                   read_offset, total_bytes, read_offset + total_bytes,
                   ts_end, ts_end - ts_start, of.name),
                dlevel = 4)

        except requests.exceptions.HTTPError as e:
            raise tc.blocked_e(
                "%s/%s: error reading console %s:%s @%dB: %s\n"
                % (run_name, self.name,
                   target.fullid, self.console_name, read_offset, e),
                { "error trace": traceback.format_exc() })

    def poll(self, testcase, run_name, _buffers_poll):
        # polling a console happens by reading the remote console into
        # a local file we keep as collateral

        # We need to make this capture
        # global to all threads in this testcase that might be reading
        # from this target--only deal is that only one at the same
        # time can write to it, shouldn't be a problem--so all the
        # state has to be updated subject to a target specific lock --
        # which now we do not have--so this poll is not specific to
        # the expect() all or to this expectation itself; it is global
        # to the testcase--this is why it uses the testcase buffers,
        # not the buffers provided in the call, to store.

        with testcase.lock:
            context = self.poll_context()
            if context not in testcase.buffers:
                testcase.buffers[context] = dict()
            buffers_poll = testcase.buffers[context]

        target = self.target
        with target.lock:
            return self._poll(testcase, run_name, buffers_poll)

    def detect(self, testcase, run_name, _buffers_poll, buffers):
        """
        See :meth:`expectation_c.detect` for reference on the arguments

        :returns: list of squares detected at different scales in
          relative and absolute coordinates, e.g:
        """
        target = self.target
        of = target.console.text_capture_file(self.console)
        if of == None:
            target.report_info('%s/%s: not detecting, no console data yet'
                               % (run_name, self.name))
            return None
        ofd = of.fileno()
        stat_info = os.fstat(ofd)
        if stat_info.st_size == 0:	# Nothing to read
            return None

        context = self.poll_context()
        # last time we looked and found, we updated the search_offset,
        # so search from there on
        if context + 'search_offset' not in testcase.tls.buffers:
            testcase.tls.buffers[context + 'search_offset'] = 0
        search_offset = testcase.tls.buffers[context + 'search_offset']

        # we mmap because we don't want to (a) read a lot of a huger
        # file line by line and (b) share file pointers -- we'll look
        # to our own offset instead of relying on that. Other
        # expectations might be looking at this file in parallel.
        with contextlib.closing(
                mmap.mmap(ofd, 0, mmap.MAP_PRIVATE, mmap.PROT_READ, 0)) \
                as mapping:
            target.report_info("%s/%s: looking for `%s` in console %s:%s @%d-%d [%s]"
                               % (run_name, self.name, self.regex.pattern,
                                  target.fullid, self.console_name,
                                  search_offset, stat_info.st_size,
                                  of.name), dlevel = 4)
            match = self.regex.search(mapping[search_offset:])
            if match:
                output = unicode(mapping[search_offset
                                         : search_offset + match.end()],
                                 encoding = 'utf-8', errors = 'replace')
                testcase.tls.buffers[context + 'search_offset'] = \
                    search_offset + match.end()
                # take care of printing a meaningful message here, as
                # this is one that many people rely on when doing
                # debugging on the serial line
                if self.name == self.regex.pattern:
                    # unnamed (we used the regex), that means they
                    # didn't care much for it, so dont' use it
                    _name = ""
                else:
                    _name = "/" + self.name
                target.report_info(
                    "%s%s: found '%s' at @%d-%d on console %s:%s [%s]"
                    % (run_name, _name, self.regex.pattern,
                       search_offset + match.start(),
                       search_offset + match.end(),
                       target.fullid, self.console_name, of.name),
                    attachments = { "console output": output },
                    dlevel = 1, alevel = 0)
                return {
                    "pattern": self.regex.pattern,
                    "from": search_offset,
                    "start": search_offset + match.start(),
                    "end": search_offset + match.end(),
                    "console output": output
                }

        return None

    def flush(self, testcase, run_name, buffers_poll, buffers,
              results):
        # we don't have to do anything, the collateral is already
        # generated in buffers['filename'], flushed and synced.
        pass


class entension(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to run methods from the console
    management interface to TTBD targets.

    Use as:

    >>> target.console.read()
    >>> target.console.write()
    >>> target.console.setup()
    >>> target.console.list()

    Consoles might be disabled (because for example, the targer has to
    be on some network for them to be enabled; you can get console
    specific parameters with:

    >>> params = target.console.setup_get()

    You can set them up (and these are implementation specific:)

    >>> target.console.setup(CONSOLENAME, param1 = val1, param2 = val2...)

    Once setup and ready to enable/disable::

    >>> target.console.enable()
    >>> target.console.disable()

    You can set the default console with:

    >>> target.console.default = NAME

    A common pattern is for a system to boot up using a serial console
    and once it is up, SSH is started and the default console is
    switched to an SSH based console, faster and more reliable.

    The targets are supposed to declare the following consoles:

    - *default*: the one we use by default
    - *preferred* (optional): the one to switch for once done booting,
      but might console-specific need setup (like SSH server starting,
      etc)

    When the console is set to another default, the property
    *console-default* will reflect that. It will be reset upon power-on.
    """

    def __init__(self, target):
        interfaces = target.rt.get('interfaces', [])
        if 'console' not in target.rt.get('interfaces', []):
            raise self.unneeded
        self.target = target
        # this won't change runtime, so it is ok to cache it
        self.console_list = self.list()
        # this becomes a ALIAS: REAL-NAME
        r = self.target.ttbd_iface_call("console", "list", method = "GET")
        self.aliases = r['aliases']
        # Which is the default console that was set in runtime?
        # call it only once from here, otherwise everytime we try to
        # get the console to use by default we do a call
        self.default_property = self.target.property_get("console-default",
                                                         None)
        self._default = self.default_property


    def _console_get(self, console):
        #
        # Given a console name or None, return which console to use;
        # if None, take the default, which is 'default' if it exists,
        # otherwise the first one on the list.
        #
        # Translate the alias into a real name; we need to run this
        # here (vs just in the server) because when we are polling in
        # the expect loops we need to know the real console
        # names--otherwise when we switch we don't notice, the offsets
        # are wrong and we override the other consoles.
        assert console == None or isinstance(console, basestring)
        console = self.aliases.get(console, console)
        if console:
            assert console in self.console_list, \
                "%s: console not supported by target" % console
            return console
        if self._default:		# a default is set at client level
            return self._default
        if self.default_property:	# a default is set at target level
            return self.default_property
        if 'default' in self.aliases:	# a default is set at config level
            return self.aliases['default']
        elif self.console_list:
            return self.console_list[0]
        else:
            raise RuntimeError("target lists no consoles")

    @property
    def default(self):
        """
        Return the default console
        """
        return self._default

    @default.setter
    def default(self, new_console = None):
        """
        Set or reset the default console

        :param str new_console: (optional) the new console to set as
          default; must be an existing console. If *None*, the default
          console is reset to one called *default* or the first
          console.
        :returns: current default console
        """
        console_list = self.list()
        assert new_console == None or new_console in console_list, \
            "new default console %s is not an existing console (%s)" \
            % (new_console, " ".join(console_list))
        if self._default != new_console:
            self.target.report_info("default console changed from %s to %s"
                                    % (self._default, new_console))
            self._default = new_console
            self.default_property = new_console
            self.target.property_set("console-default", new_console)
        return new_console

    def select_preferred(self, console = None, shell_setup = True,
                         **console_setup_kwargs):
        """
        Setup, enable and switch as default to the preferred console

        If the target declares a preferred console, then switching to
        it after setting up whatever is needed (eg: SSH daemons in the
        target, etc, paramters in the console) usually yields a faster
        and more reliable console.

        If there is no *preferred* console, then this doesn't change
        anything.

        :param str console: (optional) console name to make preferred;
          default to whatever the target declares (by maybe exporting a
          console called *preferred*).

        :param shell_setup: (optional, default) setup the shell
          up by disabling command line editing (makes it easier for
          the automation) and set up hooks that will raise an
          exception if a shell command fails.

          By default calls target.shell.setup(); if *False*, nothing
          will be called. No arguments are passed, the function needs
          to operate on the default console.

        The rest of the arguments are passed verbatim to
        :func:`target.console.setup
        <tcfl.target_ext_console.extension.setup>` to setup the
        console and are thus console specific.
        """
        assert isinstance(shell_setup, bool) or callable(shell_setup)
        target = self.target
        if console == None:
            if 'preferred' not in self.console_list:
                # nothing? well, this means keep as default whatever is
                # the default now
                return
            # get the name of the preferred console
            parameters = target.console.setup_get('preferred')
            console = parameters['real_name']
        if console == None:
            # nothing? well, this means keep as default whatever is
            # the default now
            return
        else:
            assert console in target.console.console_list, \
                "%s: unknown console (valid: %s)" \
                % (console, " ".join(target.console.console_list))
        target.console.setup(console, **console_setup_kwargs)
        target.console.enable(console)
        target.console.default = console

        # same as target.shell.up()
        if shell_setup == True:    	# passed as a parameter
            target.shell.setup()
        elif callable(shell_setup):
            shell_setup()
        # False, so we don't call shell setup


    def enable(self, console = None):
        """
        Enable a console

        :param str console: (optional) console to enable; if missing,
          the default one.
        """
        console = self._console_get(console)
        self.target.ttbd_iface_call("console", "enable", method = "PUT",
                                    component = console)

    def disable(self, console = None):
        """
        Disable a console

        :param str console: (optional) console to disable; if missing,
          the default one.
        """
        console = self._console_get(console)
        self.target.ttbd_iface_call("console", "disable", method = "PUT",
                                    component = console)

    def state(self, console = None):
        """
        Return the given console's state

        :param str console: (optional) console to enable; if missing,
          the default one
        :returns: *True* if enabled, *False* otherwise
        """
        console = self._console_get(console)
        r = self.target.ttbd_iface_call("console", "state", method = "GET",
                                        component = console)
        return r['result']


    def setup(self, console, **parameters):
        """
        Setup console's parameters

        If no parameters are given, reset to defaults.

        List of current parameters can be obtained with :meth:`setup_get`.
        """
        console = self._console_get(console)
        return self.target.ttbd_iface_call("console", "setup",
                                           component = console,
                                           **parameters)

    def setup_get(self, console):
        """
        Return a dictionary with current parameters.
        """
        console = self._console_get(console)
        r = self.target.ttbd_iface_call("console", "setup", method = "GET",
                                        component = console)
        return r['result']

    def list(self):
        r = self.target.ttbd_iface_call("console", "list", method = "GET")
        return r['result']

    def read(self, console = None, offset = 0, max_size = 0, fd = None):
        """
        Read data received on the target's console

        :param str console: (optional) console to read from
        :param int offset: (optional) offset to read from (defaults to zero)
        :param int fd: (optional) file descriptor to which to write
          the output (in which case, it returns the bytes read).
        :param int max_size: (optional) if *fd* is given, maximum
          amount of data to read
        :returns: data read (or if written to a file descriptor,
          amount of bytes read)
        """
        assert console == None or isinstance(console, basestring)
        assert offset >= 0
        assert max_size >= 0
        #assert fd == None or fd >= 0
        assert fd == None or isinstance(fd, file)

        target = self.target
        console = self._console_get(console)
        if fd:
            target.report_info("%s: reading from @%d"
                               % (console, offset), dlevel = 4)
            # read from the stream, write to a file
            with contextlib.closing(
                    target.ttbd_iface_call(
                        "console", "read", method = "GET",
                        component = console, offset = offset,
                        stream = True, raw = True)) as r:
                # http://docs.python-requests.org/en/master/user/quickstart/#response-content
                chunk_size = 1024
                total = 0
                for chunk in r.iter_content(chunk_size):
                    while True:
                        try:
                            fd.write(chunk)
                            break
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

                    # don't use chunk_size, as it might be less
                    total += len(chunk)
                    if max_size > 0 and total >= max_size:
                        break
                fd.flush()
                ret = total
                l = total
        else:
            # read from the stream, to a stream, return it
            r = target.ttbd_iface_call("console", "read", method = "GET",
                                       component = console, offset = offset,
                                       raw = True)
            ret = r.text
            l = len(ret)
        target.report_info("%s: read %dB from console @%d"
                           % (console, l, offset), dlevel = 3)
        return ret

    def size(self, console = None):
        """
        Return the amount of bytes so far read from the console

        :param str console: (optional) console to read from
        """
        console = self._console_get(console)
        r = self.target.ttbd_iface_call("console", "size", method = "GET",
                                        component = console)
        if r['result'] == None:
            return None
        return int(r['result'])

    def write(self, data, console = None):
        """
        Write data to a console

        :param data: data to write (string or bytes)
        :param str console: (optional) console to write to
        """
        if len(data) > 50:
            data_report = data[:50] + "..."
        else:
            data_report = data
        # escape unprintable chars
        data_report = data_report.encode('unicode-escape', errors = 'replace')
        console = self._console_get(console)
        self.target.report_info("%s: writing %dB to console"
                                % (console, len(data)), dlevel = 3)
        self.target.ttbd_iface_call("console", "write",
                                    component = console, data = data)
        self.target.report_info("%s: wrote %dB (%s) to console"
                                % (console, len(data), data_report))

    def list(self):
        return self.target.rt.get('consoles', [])

    def capture_filename(self, console = None):
        """
        Return the name of the file where this console is being captured to
        """
        return os.path.relpath(
            self.target.testcase.report_file_prefix + "console.%s.txt"
            % _poll_context(self.target, console))

    def text_capture_file(self, console = None):
        """
        Return a descriptor to the file where this console is being
        capture to
        """
        # see poll() above for why we ignore the poll buffers given by
        # the expect system and take the global testcase buffers
        context = self.text_poll_context(console)
        testcase = self.target.testcase
        with testcase.lock:
            buffers_poll = testcase.buffers.get(context, {})
            return buffers_poll.get('of', None)

    def text_poll_context(self, console = None):
        """
        Return the polling context that will be associated with a
        target's console.

        :param str console: (optional) console name or take default
        """
        return _poll_context(self.target, console)

    def text(self, *args, **kwargs):
        """
        Return an object to expect a string or regex in this target's
        console. This can be fed to :meth:`tcfl.tc.tc_c.expect`:

        >>> self.expect(
        >>>     target.console.text(re.compile("DONE.*$"), timeout = 30)
        >>> )

        :param str text_or_regex: string to find; this can also be a
          regular expression.
        :param str console: (optional) name of the target's console from
          which we are to read. Defaults to the default console.

        (other parameters are the same as described in
        :class:`tcfl.tc.expectation_c`.)

        """
        return expect_text_on_console_c(*args, target = self.target, **kwargs)


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


def _console_read_thread_fn(target, console, fd, offset):
    # read in the background the target's console output and print it
    # to stdout
    with msgid_c("cmdline"):
        if offset == -1:
            offset = target.console.size(console)
            if offset == None:	# disabled console? fine
                offset = 0
        else:
            offset = 0
        while True:
            try:
                size = target.console.size(console)
                if size == None or size == 0:
                    time.sleep(0.5)	# Give the port some time
                    continue
                elif size < offset:	# target power cycled?
                    sys.stderr.write(
                        "\n\r\r\nWARNING: target power cycled\r\r\n\n")
                    offset = 0
                # Instead of reading and sending directy to the
                # stdout, we need to break it up in chunks; the
                # console is in non-blocking mode (for reading
                # keystrokes) and also in raw mode, so it doesn't do
                # \n to \r\n xlation for us.
                # So we chunk it and add the \r ourselves; there might
                # be a better method to do this.
                data = target.console.read(console, offset = offset,
                                           max_size = 4096)
                if data:
                    # add CR, because the console is in raw mode
                    for line in data.splitlines(True):
                        f_write_retry_eagain(fd, line)
                        if '\n' in line:
                            f_write_retry_eagain(fd, "\r")
                    time.sleep(0.1)
                    fd.flush()
                else:
                    time.sleep(0.5)	# Give the port some time

                offset += len(data)
            except Exception as e:	# pylint: disable = broad-except
                logging.exception(e)
                raise

            
def _cmdline_console_write_interactive(target, console, crlf, offset):
    #
    # Poor mans interactive console
    #
    # spawn a background reader thread to print the console output,
    # capture user's keyboard input and send it to the target.
    print """\
WARNING: This is a very limited interactive console
         Escape character twice ^[^[ to exit; CRLF is '%s'
""" % crlf.encode('unicode-escape')
    time.sleep(1)
    fd = os.fdopen(sys.stdout.fileno(), "w+")
    console_read_thread = threading.Thread(
        target = _console_read_thread_fn,
        args = (target, console, fd, offset))
    console_read_thread.daemon = True
    console_read_thread.start()

    class _done_c(Exception):
        pass

    try:
        one_escape = False
        old_flags = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
        flags = fcntl.fcntl(sys.stdin.fileno(), fcntl.F_GETFD)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
        while True and console_read_thread.is_alive():
            try:
                chars = sys.stdin.read()
                if not chars:
                    continue
                _chars = ''
                for char in chars:
                    # if the terminal sends a \r (user hit enter),
                    # translate to crlf
                    if crlf and char == "\r":
                        _chars += crlf
                    else:
                        _chars += char
                    if char == '\x1b':
                        if one_escape:
                            raise _done_c()
                        one_escape = True
                    else:
                        one_escape = False
                target.console.write(_chars, console = console)
            except _done_c:
                break
            except IOError as e:
                if e.errno != errno.EAGAIN:
                    raise
                # If no data ready, wait a wee, try again
                time.sleep(0.25)
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_flags)


def _cmdline_console_write(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        if args.interactive:
            _cmdline_console_write_interactive(target, args.console,
                                               args.crlf, args.offset)
        elif args.data == []:	# no data given, so get from stdin
            while True:
                line = getpass.getpass("")
                if line:
                    target.console.write(line.strip() + args.crlf,
                                         console = args.console)
        else:
            for line in args.data:
                target.console.write(line + args.crlf,
                                     console = args.console)


def _cmdline_console_read(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        console = args.console
        offset = int(args.offset)
        max_size = int(args.max_size)
        if args.output == None:
            fd = sys.stdout
        else:
            fd = open(args.output, "wb")
        try:
            while True:
                size = target.console.size(console)
                if size and size > 0:
                    # If zero, it hasn't even started printing, so
                    # don't bother
                    if size < offset:	# target power cycled?
                        offset = 0
                    offset += target.console.read(console, offset,
                                                  max_size, fd)
                if not args.follow:
                    break
                time.sleep(0.25)	# no need to bombard the server..
        finally:
            if fd != sys.stdout:
                fd.close()


def _cmdline_console_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        for console in target.console.list():
            if console in target.console.aliases:
                real_name = "|" + target.console.aliases[console]
            else:
                real_name = ""
            size = target.console.size(console)
            if size != None:
                print "%s%s: %d" % (console, real_name, size)
            else:
                print "%s%s: disabled" % (console, real_name)


def _cmdline_console_setup(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        if args.reset:
            r = target.console.setup(args.console)
        elif args.parameters == []:
            r = target.console.setup_get(args.console)
        else:
            parameters = {}
            for parameter in args.parameters:
                if ':' in parameter:
                    key, value = parameter.split(":", 1)
                    # try to convert to int/float or keep as string
                    while True:
                        try:
                            value = int(value)
                            break
                        except ValueError:
                            pass
                        try:
                            value = float(value)
                            break
                        except ValueError:
                            pass
                        break	# just a string or whatever it reps as                        
                else:
                    key = parameter
                    value = True
                parameters[key] = value
            r = target.console.setup(args.console, **parameters)
        result = r.get('result', {})
        for key, value in result.iteritems():
            print "%s: %s" % (key, value)

def _cmdline_console_enable(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        target.console.enable(args.console)


def _cmdline_console_disable(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        target.console.disable(args.console)


def _cmdline_setup(arg_subparser):
    ap = arg_subparser.add_parser(
        "console-read",
        help = "Read from a target's console (pipe to `cat -A` to"
        " remove control chars")
    ap.add_argument("-s", "--offset", action = "store",
                    dest = "offset", type = int,
                    help = "Read the console output starting from "
                    "offset (some targets might or not support this)")
    ap.add_argument("-m", "--max-size", action = "store",
                    dest = "max_size", default = 0,
                    help = "Read as much bytes (approx) [only available with "
                    "-o]")
    ap.add_argument("-o", "--output", action = "store", default = None,
                    metavar = "FILENAME",
                    help = "Write output to FILENAME")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name")
    ap.add_argument("--console", "-c", metavar = "CONSOLE",
                    action = "store", default = None,
                    help = "Console to read from")
    ap.add_argument("--follow",
                    action = "store_true", default = False,
                    help = "Continue reading in a loop until Ctrl-C is "
                    "pressed")
    ap.set_defaults(func = _cmdline_console_read, offset = 0)

    ap = arg_subparser.add_parser(
        "console-list",
        help = "List consoles")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.set_defaults(func = _cmdline_console_list)

    ap = arg_subparser.add_parser(
        "console-write",
        help = "Write to a target's console")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name or URL")
    ap.add_argument("--console", "-c", metavar = "CONSOLE",
                    action = "store", default = None,
                    help = "Console to write to")
    ap.add_argument("--interactive", "-i",
                    action = "store_true", default = False,
                    help = "Print back responses")
    ap.add_argument("--local-echo", "-e",
                    action = "store_true", default = True,
                    help = "Do local echo (%(default)s)")
    ap.add_argument("--no-local-echo", "-E",
                    action = "store_false", default = True,
                    help = "Do not local echo (%(default)s)")
    ap.add_argument("-r", dest = "crlf",
                    action = "store_const", const = "\r",
                    help = "CRLF lines with \\r")
    ap.add_argument("-n", dest = "crlf",
                    action = "store_const", const = "\n",
                    help = "CRLF lines with \\n (default)")
    ap.add_argument("-R", dest = "crlf",
                    action = "store_const", const = "\r\n",
                    help = "CRLF lines with \\r\\n")
    ap.add_argument("-N", dest = "crlf",
                    action = "store_const", const = "",
                    help = "Don't add any CRLF to lines")
    ap.add_argument("data", metavar = "DATA",
                    action = "store", default = None, nargs = '*',
                    help = "Data to write; if none given, "
                    "read from stdin")
    ap.add_argument("-s", "--offset", action = "store",
                    dest = "offset", type = int, default = 0,
                    help = "(for interfactive) read the console "
                    "output starting from (-1 for last)")
    ap.set_defaults(func = _cmdline_console_write, crlf = "\n")


    ap = arg_subparser.add_parser("console-setup",
                                  help = "Setup a console")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.add_argument("--console", "-c", metavar = "CONSOLE",
                    action = "store", default = None,
                    help = "name of console to setup, or default")
    ap.add_argument("--reset", "-r",
                    action = "store_true", default = False,
                    help = "reset to default values")
    ap.add_argument("parameters", metavar = "KEY:VALUE", #action = "append",
                    nargs = "*",
                    help = "Parameters to set (KEY:VALUE)")
    ap.set_defaults(func = _cmdline_console_setup)


    ap = arg_subparser.add_parser("console-disable",
                                  help = "Disable a console")
    ap.add_argument("--console", "-c", metavar = "CONSOLE",
                    action = "store", default = None,
                    help = "name of console to disable")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.set_defaults(func = _cmdline_console_disable)

    ap = arg_subparser.add_parser("console-enable",
                                  help = "Enable a console")
    ap.add_argument("--console", "-c", metavar = "CONSOLE",
                    action = "store", default = None,
                    help = "name of console to enable")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.set_defaults(func = _cmdline_console_enable)
