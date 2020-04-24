#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""Raw access to the target's serial consoles
------------------------------------------

This exposes APIs to interface with the target's serial consoles and
the hookups for accessing them form the command line.


Text expectations
^^^^^^^^^^^^^^^^^

:class:`expect_text_on_console_c` implements an object that can poll
consoles and look for text on them.


.. _console_expectation_detect_context::

Console Expectation: Detect context
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The detection context is a string which is used to help identify how
to keep track of where we are looking for things (detecting)
in a console's output.

When we are, for example, running shell commands, we expect to send a
command, see the response (echo) and then expect an output from the
command and expect another prompt.

Each time we *expect* we are actually, after reading, searching
starting at a certain past offset (*offset0*) until the last data
available for the text we are looking for (our expectation)--at the
end of where we find this text is *offset1*.

The next time we run the process, we don't need to look from
*offset0*, but from *offset1*, since all the output from our command
execution will be reported after that.

These offsets are what is considered the *detect context*.

It becomes important to have multiple because you might have multiple
detectors looking for different things in the same console output,
that is read only once from the remote target--each of these actors
would need a different context:

- one or more parallel flows in one or more threads running shell
  commands (sequence above) on a serial console (in out case this are
  :meth:`target.send <tcfl.tc.target_c.send>`/:meth:`target.expect
  <tcfl.tc.target_c.expect>` and companions, which use the empty
  (default) *detect_context*.

- a global detector in the same number of threads as above looking for
  signs of a shell command that caused an error in the console; this
  also uses the *detect_context* and is done by
  :meth:`target.shell.setup
  <tcfl.tc.target_ext_shell.extension.setup>`.

- another detector in any number of threads looking for telltale signs
  of a Kernel Crash message; this would have its own context as it is
  just looking for the right signs in the same serial console that
  potentially is being used to execute commands (as above)

"""

import collections
import contextlib
import curses.ascii
import errno
import fcntl
import getpass
import io
import logging
import math
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

from . import tc
from . import msgid_c

def _poll_context(target, console):
    # we are polling from target with role TARGET.WANT_NAME from
    # it's console CONSOLE, so this is our context, so anyone
    # who will capture from that reuses the capture.
    # Note we also use this for naming the collateral file
    return "console-" + target.want_name + "." + target.id + "." \
        + (console if console else target.console.default)


class expect_text_on_console_c(tc.expectation_c):
    """
    Object that expects to find a string or regex in a target's
    serial console.

    See parameter description in builder :meth:`console.expect_text`,
    as this is meant to be used with the expecter engine,
    :meth:`tcfl.tc.tc_c.expect`.
    """
    def __init__(self,
                 text_or_regex,
                 console = None,	# default
                 poll_period = 0.25,
                 timeout = 30,
                 previous_max = 4096,
                 raise_on_timeout = tc.failed_e,
                 raise_on_found = None,
                 name = None,
                 target = None,
                 detect_context = ""):
        assert isinstance(target, tc.target_c)	# mandatory
        assert isinstance(text_or_regex, (str, re._pattern_type))
        assert console == None or isinstance(console, str)
        assert timeout == None or timeout >= 0
        assert poll_period > 0
        assert previous_max > 0
        tc.expectation_c.__init__(self, target, poll_period, timeout,
                                  raise_on_timeout = raise_on_timeout,
                                  raise_on_found = raise_on_found)
        assert name == None or isinstance(name, str)

        if isinstance(text_or_regex, str):
            self.regex = re.compile(re.escape(text_or_regex), re.MULTILINE)
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

        self._console = console
        self.previous_max = previous_max
        self.detect_context = detect_context

    @property
    def console(self):
        """
        Console this expectation is attached to

        Note that if initialized with the default console, we'll
        always resolve which one is it--since it is needed to keep
        track of where to store things.
        """
        if self._console == None:
            return self.target.console.default
        else:
            return self._console

    #: Maximum amount of bytes to read on each read iteration in
    #: :meth:`poll`; this is so that if a (broken) target is spewing
    #: gigabytes of data, we don't get stuck here just reading from it.
    max_size = 65536

    def poll_context(self):
        return _poll_context(self.target, self.console)

    @staticmethod
    def _poll_context_init(buffers_poll, target, console, lookback_max):
        # Initialize a reading context from this target/console
        #
        # We need to do it early so we have an offset from which where
        # to start looking, so target.console.write() might call this
        # (thus, it needs to be static).
        #
        # There will be only a single reader state per testcase and
        # thread, no matter how many expectations are pointed to a
        # target's console--see poll() for how we get there.
        #
        # so then, remove the existing collateral file, register it
        #
        testcase = target.testcase
        # Assumes _testcase.lock is taken
        assert 'read_offset' not in buffers_poll, \
            "buffers_poll %08xd DOUBLE INIT" % id(buffers_poll)
        filename = target.console.capture_filename(console)
        testcase = target.testcase
        testcase.collateral.add(filename)
        # rename any existing file, we are starting from scratch
        commonl.rm_f(filename)
        of = open(filename, "a+", 0)
        # Initialize the offset
        # how much do we care on previous history? no good way to
        # tell, so we set a sensible default we can alter
        # also, the target could put more data out before we start
        # reading, so this is just an approx
        # Will be adjusted in the first read
        read_offset = target.console.size(console)
        if read_offset == None:
            read_offset = 0	# happens when the console is disabled
        read_offset -= lookback_max
        if read_offset < 0:
            read_offset = 0
        buffers_poll['read_offset'] = read_offset
        buffers_poll['of'] = of
        return buffers_poll

    @staticmethod
    def _poll_context_init_maybe(target, console, lookback_max):
        testcase = target.testcase
        buffers_poll = expect_text_on_console_c._poll_buffers_get_global(
            testcase, target, console)
        if not 'of' in buffers_poll:
            expect_text_on_console_c._poll_context_init(
                buffers_poll, target, console, lookback_max)

    # FIXME: this will be a global pattern, so move it to def tc.expect()
    @staticmethod
    def _poll_buffers_get_global(testcase, target, console):
        # with testcase.lock!!
        context = _poll_context(target, console)
        if context not in testcase.buffers:
            testcase.buffers[context] = dict()
        return testcase.buffers[context]

    def _poll(self, testcase, run_name, buffers_poll):
        # NOTE: this is called with target.lock held because
        # buffers_poll needs to be accessed under that (FIXME: move to
        # buffers_poll['lock'])
        target = self.target

        # polling a console happens by reading the remote console into
        # a local file we keep as collateral
        read_offset = buffers_poll.get('read_offset', 0)
        of = buffers_poll['of']
        ofd = of.fileno()

        try:
            ts_start = time.time()
            target.report_info(
                "%s/%s: reading from console %s:%s @%d on %.2fs to %s"
                % (run_name, self.name, target.fullid, self.console,
                   read_offset, ts_start, of.name), dlevel = 5)
            # We are dealing with a file as our buffering and accounting
            # system, so because read_to_fd() is bypassing caching, flush
            # first and sync after the read.
            # Note we get the new_offset straight() from the read
            # call, which is the most accurate from the server standpoint
            of.flush()
            generation, new_offset, total_bytes = \
                target.console.read_full(self.console, read_offset,
                                         self.max_size, of)
            generation_prev = buffers_poll.get('generation', None)
            if generation_prev == None:
                buffers_poll['generation'] = generation
            elif generation_prev < generation:
                # ops, the console was restarted, so the offsets are
                # no longer valid, retry with offset zero--this
                # usually happens when the target power cycles or the
                # console switches off/on
                target.report_info(
                    "%s/%s: console %s:%s restarted, re-reading from start"
                    % (run_name, self.name, target.fullid, self.console),
                    dlevel = 5)
                generation, new_offset, total_bytes = \
                    target.console.read_full(self.console, 0,
                                             self.max_size, of)
                buffers_poll['generation'] = generation
            ts_end = time.time()
            of.flush()
            os.fsync(ofd)
            buffers_poll['read_offset'] = new_offset
            target.report_info(
                "%s/%s: read from console %s:%s @%d %dB (new offset @%d) "
                "on %.2fs (%.2fs) to %s"
                % (run_name, self.name, target.fullid, self.console,
                   read_offset, total_bytes, new_offset,
                   ts_end, ts_end - ts_start, of.name),
                dlevel = 4)

        except requests.exceptions.HTTPError as e:
            raise tc.blocked_e(
                "%s/%s: error reading console %s:%s @%dB: %s\n"
                % (run_name, self.name,
                   target.fullid, self.console, read_offset, e),
                { "error trace": traceback.format_exc() })

    def poll(self, testcase, run_name, buffers_poll):
        # polling a console happens by reading the remote console into
        # a local file we keep as collateral

        # the polling is always call under the lock for this specific
        # poll context (thus for all the threads and expectations, so
        # we only poll once at the same time from each source, as
        # given by the poll context)

        target = self.target
        if 'of' in buffers_poll:
            filename = buffers_poll['of'].name
            target.report_info(
                "%s/%s: existing console capture context %08x/%s" %
                (run_name, self.name, id(buffers_poll), filename),
                dlevel = 5)
        else:
            self._poll_context_init(buffers_poll, target,
                                    self.console, self.previous_max)
            filename = buffers_poll['of'].name
            target.report_info(
                "%s/%s: new console capture context %08x/%s" %
                (run_name, self.name, id(buffers_poll), filename),
                dlevel = 5)

        return self._poll(testcase, run_name, buffers_poll)

    def detect(self, testcase, run_name, buffers_poll, _buffers):
        """
        See :meth:`expectation_c.detect` for reference on the arguments

        :returns: dictionary of data describing the match, including
          an interator over the console output
        """

        target = self.target
        of = buffers_poll.get('of', None)
        if of == None:
            target.report_info('%s/%s: not detecting, no console data yet'
                               % (run_name, self.name))
            return None
        ofd = of.fileno()
        stat_info = os.fstat(ofd)
        if stat_info.st_size == 0:	# Nothing to read
            return None

        # last time we looked and found, we updated the search_offset,
        # so search from there on -- note this offset is on the
        # capture file we save in the client, not from the server's
        # capture POV.
        if self.detect_context + 'search_offset' not in buffers_poll:
            buffers_poll[self.detect_context + 'search_offset'] = 0
        search_offset = buffers_poll[self.detect_context + 'search_offset']

        # we mmap because we don't want to (a) read a lot of a huger
        # file line by line and (b) share file pointers -- we'll look
        # to our own offset instead of relying on that. Other
        # expectations might be looking at this file in parallel.
        with contextlib.closing(
                mmap.mmap(ofd, 0, mmap.MAP_PRIVATE, mmap.PROT_READ, 0)) \
                as mapping:
            target.report_info(
                "%s/%s: looking for `%s` in console %s:%s @%d-%d [%s]"
                % (run_name, self.name, self.regex.pattern,
                   target.fullid, self.console,
                   search_offset, stat_info.st_size, of.name), dlevel = 4)
            match = self.regex.search(mapping[search_offset:])
            if match:
                # this allows us later to pick up stuff in report
                # handlers without having to have context knowledge
                buffers_poll[self.detect_context + 'search_offset_prev'] = \
                    search_offset
                buffers_poll[self.detect_context + 'search_offset'] = \
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
                match_data = {
                    # this allows an exception raised when found to
                    # include this iterator as an attachment that can
                    # be reported
                    "console output": target.console.generator_factory(
                        self.console,
                        search_offset, search_offset + match.end()),
                }
                target.report_info(
                    "%s%s: found '%s' at @%d-%d on console %s:%s [%s]"
                    % (run_name, _name, self.regex.pattern,
                       search_offset + match.start(),
                       search_offset + match.end(),
                       target.fullid, self.console, of.name),
                    attachments = match_data, dlevel = 1, alevel = 0)
                # make this match on_timeout()'s as much as possible
                match_data["target"] = self.target
                match_data["origin"] = self.origin
                match_data["console"] = self.console
                match_data["pattern"] = self.regex.pattern
                match_data["offset"] = search_offset
                match_data["offset_match_start"] = \
                    search_offset + match.start()
                match_data["offset_match_end"] = search_offset + match.end()
                return match_data
        return None

    def on_timeout(self, run_name, poll_context, buffers_poll, buffers,
                   ellapsed, timeout):
        testcase = self.target.testcase
        # If no previous search, that'd be the beginning...
        search_offset_prev = \
            buffers_poll.get(self.detect_context + 'search_offset_prev', 0)
        search_offset = \
            buffers_poll.get(self.detect_context + 'search_offset', 0)
        raise self.raise_on_timeout(
            "%s/%s: timed out finding text '%s' in "
            "console '%s:%s' @%.1f/%.1fs/%.1fs)"
            % (run_name, self.name, self.regex.pattern,
               self.target.fullid, self.console,
               ellapsed, timeout, self.timeout),
            {
                # make this match detect()'s as much as possible
                "target": self.target,
                "origin": self.origin,
                "console": self.console,
                "pattern": self.regex.pattern,
                "offset": search_offset,
                "offset prev": search_offset_prev,
                "console output": self.target.console.generator_factory(
                    self.console,
                    search_offset_prev, search_offset),
            }
        )

    def flush(self, testcase, run_name, buffers_poll, buffers,
              results):
        # we don't have to do anything, the collateral is already
        # generated in buffers_poll['of'], flushed and synced.
        pass

class extension(tc.target_extension_c):
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
        if 'console' not in target.rt.get('interfaces', []):
            raise self.unneeded
        self.target = target
        # this won't change runtime, so it is ok to cache it
        self.console_list = self.list()
        # this becomes a ALIAS: REAL-NAME
        r = self.target.ttbd_iface_call("console", "list", method = "GET")
        self.aliases = r['aliases']
        self._set_default()

    def _set_default(self):
        # Which is the default console that was set in the server?
        # call it only once from here, otherwise everytime we try to
        # get the console to use by default we do a call
        self.default_property = self.target.property_get(
            "interfaces.console.default", None)
        if self.default_property:
            self._default = self.default_property
        elif 'default' in self.aliases:
            self._default = self.aliases['default']
        else:
            self._default = self.console_list[0]

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
        assert console == None or isinstance(console, str)
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
        if new_console == None:
            new_console = self.aliases['default']
        if self._default != new_console:
            self.target.report_info("default console changed from %s to %s"
                                    % (self._default, new_console))
            self._default = new_console
            self.default_property = new_console
            self.target.property_set("interfaces.console.default", new_console)
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
            if 'preferred' not in self.aliases:
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
            target.shell.setup(console)
        elif callable(shell_setup):
            shell_setup(console)
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

    def _read(self, console = None, offset = 0, max_size = 0, fd = None):
        """
        Read data received on the target's console

        :param str console: (optional) console to read from
        :param int offset: (optional) offset to read from (defaults to zero)
        :param int fd: (optional) file descriptor to which to write
          the output (in which case, it returns the bytes read).
        :param int max_size: (optional) if *fd* is given, maximum
          amount of data to read
        :returns: tuple consisting of:
          - stream generation
          - stream size after reading
          - data read (or if written to a file descriptor,
            amount of bytes read)
        """
        assert console == None or isinstance(console, str)
        assert offset >= 0
        assert max_size >= 0
        #assert fd == None or fd >= 0
        assert fd == None or isinstance(fd, io.IOBase)

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
                            # we want to write verbatim, no encodings
                            fd.buffer.write(chunk)
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
        generation_s, offset_s = \
            r.headers.get('X-Stream-Gen-Offset', "0 0").split()
        generation = int(generation_s)
        new_offset = \
            int(offset_s) \
            + int(r.headers.get('Content-Length', 0))
        return generation, new_offset, ret

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
        return self._read(console = console, offset = offset,
                          max_size = max_size, fd = fd)[2]

    def read_full(self, console = None, offset = 0, max_size = 0, fd = None):
        """
        Like :meth:`read`, reads data received on the target's console
        returning also the stream generation and offset at which to
        read the next time to get new data.

        Stream generation is a monotonically increasing number that
        is incrased every time the target is power cycled.

        :param str console: (optional) console to read from

        :param int offset: (optional) offset to read from (defaults to
          zero)

        :param int fd: (optional) file descriptor to which to write
          the output (in which case, it returns the bytes read).

        :param int max_size: (optional) if *fd* is given, maximum
          amount of data to read

        :returns: tuple consisting of:
          - stream generation
          - stream size after reading
          - data read (or if written to a file descriptor,
            amount of bytes read)
        """
        return self._read(console = console, offset = offset,
                          max_size = max_size, fd = fd)

    def size(self, console = None):
        """
        Return the amount of bytes so far read from the console

        :param str console: (optional) console to read from
        """
        console = self._console_get(console)
        r = self.target.ttbd_iface_call("console", "size", method = "GET",
                                        component = console)
        if r['result'] == None:
            return None			# console disabled
        return int(r['result'])

    def write(self, data, console = None):
        """
        Write data to a console

        :param data: data to write (string or bytes)

        :param str console: (optional) console to write to
        """
        # the reporting of unprintable is left to the report driver;
        # however, for readability in the reporting, we'll replace \n
        # (0x0d) with <N>
        if len(data) > 50:
            data_report = data[:50] + "..."
        else:
            data_report = data
        # fuuuugly...Python3 will make this easier
        data_report = data_report.replace("\n", r"<NL>")
        console = self._console_get(console)
        testcase = self.target.testcase
        self.target.report_info("%s: writing %dB to console"
                                % (console, len(data)), dlevel = 3)
        self.target.ttbd_iface_call("console", "write",
                                    component = console, data = data)
        self.target.report_info("%s: wrote %dB (%s) to console"
                                % (console, len(data), data_report))

    def capture_filename(self, console = None):
        """
        Return the name of the file where this console is being captured to
        """
        return os.path.relpath(
            # _poll_context already adds 'console-', so we don't need
            # to add more
            self.target.testcase.report_file_prefix + "%s.txt"
            % _poll_context(self.target, console))

    def text_capture_file(self, console = None, context = None):
        """
        Return a descriptor to the file where this console is being
        captured to

        :return: file descriptor to the open file where data is being
          captured; might be empty if nothing has been captured yet or
          *None* if capturing has not started.
        """
        # see poll() above for why we ignore the poll buffers given by
        # the expect system and take the global testcase buffers
        if context == None:
            context = self.text_poll_context(console)
        testcase = self.target.testcase
        with testcase.lock:
            poll_state = testcase._poll_state.get(context, None)
        if poll_state == None:
            return None
        with poll_state.lock:
            return poll_state.buffers.get('of', None)

    def text_poll_context(self, console = None):
        """
        Return the polling context that will be associated with a
        target's console.

        :param str console: (optional) console name or take default
        """
        return _poll_context(self.target, console)

    def text(self, *args, **kwargs):
        """Return an object to expect a string or regex in this target's
        console. This can be fed to :meth:`tcfl.tc.tc_c.expect`:

        >>> self.expect(
        >>>     target.console.text(re.compile("DONE.*$"), timeout = 30)
        >>> )

        or for leaving it permanently installed as a hook to, eg,
        raise an exception if a non-wanted string is found:

        >>> testcase.expect_global_append(
        >>>     target.console.text(
        >>>         "Kernel Panic",
        >>>         timeout = 0, poll_period = 1,
        >>>         raise_on_found = tc.error_e("kernel panicked"),
        >>>     )
        >>> )

        :param str text_or_regex: string to find; this can also be a
          regular expression.
        :param str console: (optional) name of the target's console from
          which we are to read. Defaults to the default console.

        :param str detect_context: (optional) the detection context is
          a string which is used to help identify how to keep track of
          where we are looking for things (detecting) in a console's
          output. Further info :ref:`here
          <console_expectation_detect_context>`

        (other parameters are the same as described in
        :class:`tcfl.tc.expectation_c`.)

        """
        return expect_text_on_console_c(*args, target = self.target, **kwargs)

    def send_expect_sync(self, console, detect_context = ""):
        """
        Before executing a send/expect sequence, sync so that the
        expect sequence starts looking after the data we are about to
        send--otherwise the expect engine might be looking at data
        returned way before back then.

        :param str console: name of the target's console on which to sync.

        :param str detect_context: (optional) the detection context is
          a string which is used to help identify how to keep track of
          where we are looking for things (detecting) in a console's
          output. Further info :ref:`here
          <console_expectation_detect_context>`

        """
        # If we are sending something, the next expect we want to
        # start searching from the output of that something. So we set
        # the output to the current size of the capture file so we
        # start seaching only off what came next.
        testcase = self.target.testcase
        with testcase.lock:
            context = self.text_poll_context(console)
            if context not in testcase._poll_state:
                testcase._poll_state[context] = testcase._poll_state_c()
            poll_state = testcase._poll_state[context]
        with poll_state.lock:
            of = poll_state.buffers.get('of', None)
            if of:
                ofd = of.fileno()
                stat_info = os.fstat(ofd)
                search_offset = stat_info.st_size
            else:
                search_offset = 0
            poll_state.buffers[detect_context + 'search_offset'] = search_offset

    def capture_iterator(self, console, offset_from = 0, offset_to = 0):
        """
        Iterate over the captured contents of the console

        :class:`expect_text_on_console_c.poll` has created a file
        where it has written all the contents read from the console;
        this function is a generator that iterates over it, yielding
        safe UTF-8 strings.

        Note these are not reseteable, so to use in
        attachments with multiple report drivers, use instead a
        :meth:generator_factory.

        :param str console: name of console on which to operate
        :param int offset_from: (optional) offset where to start
          (default from beginning)
        :param int offset_to: (optional) offset where to finish
          (default to end)
        """
        assert console == None or isinstance(console, str)
        #
        # Provide line-based iteration on the last match in the
        # console, as given by information on the buffers.
        #
        target = self.target
        # Open as binary so we don't alter the offset counts if it
        # happens to fix up characters; yield then as safe UTF-8
        try:
            with io.open(target.console.capture_filename(console), "rb") as f:
                f.seek(offset_from)
                offset = offset_from
                for line in f:
                    try:
                        _line = line.decode(encoding = 'utf-8',
                                            errors = 'backslashreplace')
                    except TypeError:
                        # Per https://bugs.python.org/msg113734, this
                        # might happen as
                        #
                        ## TypeError: don't know how to handle UnicodeDecodeError in error callback
                        #
                        # since we are opening as binary--we will fall
                        # back to a 'replace' encoding.
                        _line = line.decode(encoding = 'utf-8',
                                            errors = 'replace')
                    yield _line
                    offset += len(line)
                    if offset_to > 0 and offset >= offset_to:
                        # read only until the final offset, more or less
                        if not line.endswith("\n"):
                            yield u"\n"
                        break
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            yield u""

    def generator_factory(self, console, offset_from = 0, offset_to = 0):
        """
        Return a generator factory that creates iterators to dump
        console's received data

        :param str console: name of console on which to operate
        :param int offset_from: (optional) offset where to start
          (default from beginning)
        :param int offset_to: (optional) offset where to finish
          (default to end)
        """
        return commonl.generator_factory_c(
            self.capture_iterator, console, offset_from, offset_to)


def f_write_retry_eagain(fd, data):
    while True:
        try:
            fd.buffer.write(data)
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
        generation = 0
        generation_prev = None
        backoff_wait = 0.1
        while True:
            try:
                # Instead of reading and sending directy to the
                # stdout, we need to break it up in chunks; the
                # console is in non-blocking mode (for reading
                # keystrokes) and also in raw mode, so it doesn't do
                # \n to \r\n xlation for us.
                # So we chunk it and add the \r ourselves; there might
                # be a better method to do this.
                generation, offset, data = \
                    target.console.read_full(console, offset, 4096)
                if generation_prev != None and generation_prev != generation:
                    sys.stderr.write(
                        "\n\r\r\nWARNING: console was restarted\r\r\n\n")
                generation_prev = generation

                if data:
                    # add CR, because the console is in raw mode
                    for line in data.splitlines(True):
                        f_write_retry_eagain(fd, line)
                        if '\n' in line:
                            f_write_retry_eagain(fd, "\r")
                    fd.flush()

                if len(data) == 0:
                    backoff_wait *= 2
                else:
                    backoff_wait = 0.1
                # in interactive mode we want to limit the backoff to
                # one second so we have time to react
                if backoff_wait >= 0.7:
                    backoff_wait = 0.7
                time.sleep(backoff_wait)	# no need to bombard the server..
            except Exception as e:	# pylint: disable = broad-except
                logging.exception(e)
                raise


def _cmdline_console_write_interactive(target, console, crlf, offset):
    #
    # Poor mans interactive console
    #
    # spawn a background reader thread to print the console output,
    # capture user's keyboard input and send it to the target.
    print("""\
WARNING: This is a very limited interactive console
         Escape character twice ^[^[ to exit; CRLF is '%s'
""" % crlf.encode('unicode-escape'))
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
            generation = 0
            generation_prev = None
            backoff_wait = 0.1
            while True:
                generation, offset, data_len = \
                    target.console.read_full(console, offset, max_size, fd)
                if generation_prev != None and generation_prev != generation:
                    sys.stderr.write(
                        "\n\r\r\nWARNING: target power cycled\r\r\n\n")
                generation_prev = generation
                if not args.follow:
                    break
                if data_len == 0:
                    backoff_wait *= 2
                else:
                    backoff_wait = 0.1
                if backoff_wait >= 4:
                    backoff_wait = 4

                time.sleep(backoff_wait)	# no need to bombard the server..
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
                print("%s%s: %d" % (console, real_name, size))
            else:
                print("%s%s: disabled" % (console, real_name))


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
        for key, value in result.items():
            print("%s: %s" % (key, value))

def _cmdline_console_enable(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args)
        target.console.enable(args.console)


def _cmdline_console_disable(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(
            args,
            extensions_only = "console")
        target.console.disable(args.console)

def _cmdline_console_wall(args):
    # for all the targets in args.targets, query the consoles they
    # offer and display them in a grid in the current terminal using
    # GNU screen to divide it in a mesh of sub-windows; then keep
    # updating each window with the console's output

    if args.name == None:
        if args.target == []:
            args.name = "TCF Wall"
        else:
            args.name = "TCF Wall: " + " ".join(args.target)

    with msgid_c("cmdline"):
        rtl = tc.ttb_client.cmdline_list(args.target, args.all)

        # Collect information about which targets we want to display
        # on the wall
        #
        # We create tc.target_c objects for each; instantiate target
        # objects in parallel, much faster, since it has to query the
        # servers for console info
        def _mk_target(args, target_name):
            with msgid_c("cmdline"):
                return tc.target_c.create_from_cmdline_args(
                    args, target_name, iface = "console",
                    extensions_only = ['console'])

        thread_pool = tc._multiprocessing_method_pool_c(processes = 10)
        threads = {}
        for rt in rtl:
            if 'console' not in rt.get('interfaces', []):
                continue
            target_name = rt['fullid']
            threads[target_name] = thread_pool.apply_async(
                _mk_target,
                ( args, target_name ),
            )
        thread_pool.close()
        thread_pool.join()

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

        consolel = collections.defaultdict(console_descr_c)

        for thread in threads.values():
            target = thread.get()
            for console in target.console.console_list:
                if console in target.console.aliases:
                    continue
                if args.console and console not in args.console:
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
        rows = int(math.sqrt(len(consolel)))
        columns = (len(consolel) + rows - 1) // rows

        # Write the GNU screen config file that will divide the window
        # in sub-windows (screens in GNU screen parlance and run the
        # console-reading script on each.
        #
        # do not chdir somehwere else, as we rely on the
        # configuration being here
        cf_name = os.path.join(tc.tc_c.tmpdir, "screen.rc")

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
                    cf.write(
                        'screen -c %s console-read %s -c %s --follow\n'
                        'title %s\n\n' % (
                            sys.argv[0],
                            descr.target.fullid, descr.console, item
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
        os.execvp("screen", [ "screen", "-c", cf.name, "-S", args.name ])


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
        "console-ls",
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


    ap = arg_subparser.add_parser(
        "console-wall",
        help = "Display multiple serial consoles in a tiled terminal"
        " window using GNU screen (type 'Ctrl-a : quit' to stop it)") 
    ap.add_argument(
        "-a", "--all", action = "store_true", default = False,
        help = "List also disabled targets")
    ap.add_argument("--name", "-n", metavar = "NAME",
                    action = "store", default = None,
                    help = "name to set for this wall (defaults to "
                    "the target specification")
    ap.add_argument("--console", "-c", metavar = "CONSOLE",
                    action = "append", default = None,
                    help = "Read only from the named consoles (default: all)")
    ap.add_argument(
        "target", metavar = "TARGETSPEC", nargs = "*",
        action = "store", default = [],
        help = "Target name or expressions to determine which target(s) "
        "to list (like those given to 'tcf run -t'). For example: "
        "'owner:\"john\"' would show the consoles of all the targets "
        "owned by a user whose user id contains the word *john*; "
        "'type:\"qemu\"' would show that of all the targets with "
        "*qemu* on the type")
    ap.set_defaults(func = _cmdline_console_wall)
