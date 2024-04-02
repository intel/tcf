#! /usr/bin/python3
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


.. _console_expectation_detect_context:

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
  :meth:`target.shell.setup <tcfl.target_ext_shell.shell.setup>`.

- another detector in any number of threads looking for telltale signs
  of a Kernel Crash message; this would have its own context as it is
  just looking for the right signs in the same serial console that
  potentially is being used to execute commands (as above)

"""

import contextlib
import errno
import io
import mmap
import numbers
import os
import re
import sys
import time
import traceback
import typing

import requests

import commonl

from . import tc

def _poll_context(target, console):
    # we are polling from target with role TARGET.WANT_NAME from
    # it's console CONSOLE, so this is our context, so anyone
    # who will capture from that reuses the capture.
    # Note we also use this for naming the collateral file
    return "console-" + target.want_name + "." + target.id + "." \
        + (console if console else target.console.default)


class expect_text_on_console_c(tc.expectation_c):
    """Object that expects to find a string or regex in a target's
    serial console.

    See parameter description in builder :meth:`target.console.text
    <tcfl.target_ext_console.extension.text>`, as this is meant to be
    used with the expecter engine, :meth:`tcfl.tc.tc_c.expect`.

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
                 detect_context = "", report = None):
        assert isinstance(target, tc.target_c)	# mandatory
        assert isinstance(text_or_regex, (bytes, str, typing.Pattern))
        assert console == None or isinstance(console, str)
        assert timeout == None or timeout >= 0
        assert poll_period > 0
        assert previous_max > 0
        tc.expectation_c.__init__(self, target, poll_period, timeout,
                                  raise_on_timeout = raise_on_timeout,
                                  raise_on_found = raise_on_found)
        assert name == None or isinstance(name, str)

        self.regex_set(text_or_regex)
        if name:
            self.name = name
        else:
            # this might get hairy when a regex is just regex that all
            # gets escaped out (looking like _______________). oh well
            try:
                self.name = commonl.name_make_safe(self.regex.pattern.decode())
            except AttributeError as e:
                raise

        self._console = console
        self.previous_max = previous_max
        self.detect_context = detect_context
        self.report = report

    def regex_set(self, text_or_regex):
        if isinstance(text_or_regex, str):
            # we do out work in bytes, since we don't really know what
            # we get the consoles
            text_or_regex = text_or_regex.encode('utf-8')
            self.regex = re.compile(re.escape(text_or_regex), re.MULTILINE)
            return
        if isinstance(text_or_regex, bytes):
            self.regex = re.compile(re.escape(text_or_regex), re.MULTILINE)
            return

        if isinstance(text_or_regex, typing.Pattern) \
            and isinstance(text_or_regex.pattern, str):
                # see above for isinstance(, str) on why we do this
                pattern = text_or_regex.pattern.encode(	# convert to bytes
                    'utf-8', errors = 'surrogatencode')
                text_or_regex = re.compile(pattern, re.MULTILINE)
                self.regex = text_or_regex
                return

        if isinstance(text_or_regex, typing.Pattern) \
            and isinstance(text_or_regex.pattern, bytes):
                self.regex = text_or_regex
                return

        raise AssertionError(
            "text_or_regex must be a string or compiled regex, got %s" \
            % type(text_or_regex).__name__)


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
        # for opening we open in binary mode, since we read from
        # interfaces that are bytes
        of = open(filename, "ba+")
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
            # the capture must be raw, no translations -- otherwise it
            # is going to be a mess to keep offsets right
            newline = ''
            generation, new_offset, total_bytes = \
                target.console.read_full(self.console, read_offset,
                                         fd = of, newline = newline)
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
                                             fd = of, newline = newline)
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
        See :meth:`tcfl.tc.expectation_c.detect` for reference on the
        arguments

        :returns: dictionary of data describing the match, including
          an interator over the console output

          >>> {
          >>>     'console': CONSOLENAME,
          >>>     'console output': <commonl.generator_factory_c ...>,
          >>>     'groupdict': {},
          >>>     'offset': 0,
          >>>     'offset_match_end': 710,
          >>>     'offset_match_start': 709,
          >>>     'origin': 'FILENAME:LINE',
          >>>     'pattern': 'TEXT_OR_REGEX',
          >>>     'target': TARGETOBJECT,
          >>> }

          The different fields:

          - *target*: :class:`target object <tcfl.tc.target_c>` on
            which console this match happened

          - *console*: name of console where the match happened

          - *pattern* text or regular expression that was being matched

          - *origin* source file and line number where this match was
             called from.

          - *offset*, *offset_match_start* and *offset_match_end*:
             offset where the console was read from, where the match
             starts and where the match ends.

          - *groupdict* is the list of grups returned when matching
            the regular expression
            (:meth:`re.MatchObject.groupdict`). Eg, if
            *TEXT_OR_REGEX* was:

            >>> re.compile("(?P<field_name>[a-z]+)=(?P<field_value>[0-9]+)")

            and the text matched was *length=54*, *groupdict* would be
            returned as:

            >>> { 'field_name': 'lentgh', 'field_value': '54' }

          - *console output*: generator maker to report the console
            output at the offset of the match; initialize the generator
            and then use it as usual (see
            :class:`commonl.generator_factory_c`):

            >>> for line in r['console output'].make_generator():
            >>>     do_something_with_this_line(line)

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

        # if no detect context is given, we default to something
        # called as the console where we are looking
        if not self.detect_context:
            detect_context = self.console
        else:
            detect_context = self.detect_context
        # last time we looked and found, we updated the search_offset,
        # so search from there on -- note this offset is on the
        # capture file we save in the client, not from the server's
        # capture POV.
        if detect_context + 'search_offset' not in buffers_poll:
            buffers_poll[detect_context + 'search_offset'] = 0
        search_offset = buffers_poll[detect_context + 'search_offset']

        # we mmap because we don't want to (a) read a lot of a huger
        # file line by line and (b) share file pointers -- we'll look
        # to our own offset instead of relying on that. Other
        # expectations might be looking at this file in parallel.
        if sys.platform == "win32":
            extra_args = [ None, mmap.ACCESS_READ, 0 ] # just offset
        else:
            extra_args = [ mmap.MAP_PRIVATE, mmap.PROT_READ, 0 ]
        with contextlib.closing(
                mmap.mmap(ofd, 0, *extra_args)) \
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
                buffers_poll[detect_context + 'search_offset_prev'] = \
                    search_offset
                buffers_poll[detect_context + 'search_offset'] = \
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
                if self.report == 0:
                    console_output = None
                elif isinstance(self.report, int):
                    _search_offset = search_offset + match.end() - self.report
                    search_offset = max(search_offset, _search_offset)
                    console_output = "console output (partial)"
                elif self.report == None:
                    console_output = "console output"
                else:
                    raise AssertionError(
                        "self.report: invalid type '%s' or value (%s)"
                        % (type(self.report), self.report))
                if console_output != None:
                    match_data = {
                        # this allows an exception raised when found to
                        # include this iterator as an attachment that can
                        # be reported
                        console_output: target.console.generator_factory(
                            self.console,
                            search_offset, search_offset + match.end()),
                    }
                else:
                    match_data = {}
                target.report_info(
                    "%s%s: found '%s' at @%d-%d on console %s:%s [%s]"
                    % (run_name, _name, self.regex.pattern,
                       search_offset + match.start(),
                       search_offset + match.end(),
                       target.fullid, self.console, of.name),
                    attachments = match_data, dlevel = 1, alevel = 1)
                # make this match on_timeout()'s as much as possible
                match_data["target"] = self.target
                match_data["origin"] = self.origin
                match_data["console"] = self.console
                match_data["pattern"] = self.regex.pattern
                match_data["groupdict"] = match.groupdict()
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
        # if no detect context is given, we default to something
        # called as the console where we are looking
        if not self.detect_context:
            detect_context = self.console
        else:
            detect_context = self.detect_context
        search_offset_prev = \
            buffers_poll.get(detect_context + 'search_offset_prev', 0)
        search_offset = \
            buffers_poll.get(detect_context + 'search_offset', 0)
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

        # this becomes a ALIAS: REAL-NAME
        # r is:
        #
        ## {
        ##     'aliases': { 'default': 'ttyS0', 'preferred': },
        ##     'result': ['default', 'preferred', 'ttyS0', 'ssh0']
        ## }
        ##
        ## self.list() returns ther esult part, basically
        #
        # FIXME: we can remove this call if we do add in the server
        #        inventory:
        #
        #  1. the tag 'preferred: true' on the preferred console,
        #     if any
        #
        #  2. the tag 'default: true' on the current default console
        #
        # this way, for the first initiazation we don't need to call
        # list again, since the info is already coming from the
        # inventory.
        r = self.target.ttbd_iface_call("console", "list", method = "GET",
                                        retry_timeout = 10)
        # this won't change runtime, so it is ok to cache it
        self.console_list = r.get('result', [])
        self.aliases = r['aliases']
        self._set_default()
        #: Default end of line for the different consoles
        #:
        #: Dictionary keyed by console name that specifies the end-of-string
        #: for the console; if there is no entry for a console.
        #:
        #: See :meth:tcfl.tc.target_c.send.
        #:
        #: This can be set with::
        #:
        #:    >> target.console.crlf['my consolename'] = '\r'
        #:
        #: If nothing is specified, it will default to '\n' or no
        #: translation, depending on what needs to be done. Different
        #: consoles of the same machine might have different needs
        #: depending on their transport.
        self.crlf = {}

        # See if the servr declares any CRLF convention to default to;
        # we do this now because this info doesn't change, makes no
        # sense to keep udpating it in tcfl.tc.target_c.send() [main
        # user of it]
        console_iface = target.rt['interfaces']['console']
        for console in self.console_list:
            # Maybe the server declares in the inventory which
            # CRLF convention to use in interfaces.console.CONSOLENAME.crlf
            console_info = console_iface.get(console, {})
            if isinstance(console_info, str):
                # alias for something else, ignore
                continue
            if 'crlf' in console_info:
                self.crlf[console] = console_info['crlf']
            else:
                # for those who don't declare anything, we default to \r
                self.crlf[console] = '\r'

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
        elif self.console_list:		# ensure there are consoles...
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
            new_console = self.aliases.get('default', console_list[0])
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

        :returns bool: *True* if the default console changed, *False*
          otherwise

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
                return False
            # get the name of the preferred console
            parameters = target.console.setup_get('preferred')
            console = parameters['real_name']
        if console == None:
            # nothing? well, this means keep as default whatever is
            # the default now
            return False		# we didn't change
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
        return True			# we changed

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
                                        component = console,
                                        retry_timeout = 10)
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
                                        component = console,
                                        retry_timeout = 10)
        return r['result']

    def list(self):
        r = self.target.ttbd_iface_call("console", "list", method = "GET",
                                        retry_timeout = 10)
        return r['result']

    @staticmethod
    def offset_calc(target, console, offset):
        """
        Calculate offset based on current console size

        :param int offset: if negative, it is calculated relative to
          the end of the console output
        """
        if offset >= 0:
            return offset
        # negative offset, calculate from current size
        size = target.console.size(console)
        if size == None:
            return 0	# disabled console
        # offset larger than current size?
        offset = max(0, size + offset + 1)
        return offset

    # \r+\n is because some transports pile \rs on top of each other...
    _crlf_regex_universal = re.compile("(\r+\n|\r|\n)")
    _crlf_regex_universal_b = re.compile(b"(\r+\n|\r|\n)")

    @classmethod
    def _newline_convert(cls, data, newline):
        # This function handles strings and bytes so we don't need to
        # worry about what it is. Dirty. Bite me.
        # I am sure there is an smarter or more pythonic way to do
        # this...open ears
        if isinstance(data, bytes):
            data_type = bytes
            empty = b''
            new_newline = b'\n'
            regex = cls._crlf_regex_universal_b
            # newline at this point can be None or other stuff, but to
            # avoid complicating it, we do it here)
            if newline != None and isinstance(newline, str):
                newline = newline.encode('utf-8')
        else:
            data_type = str
            empty = ''
            new_newline = '\n'
            regex = cls._crlf_regex_universal
            if newline != None and isinstance(newline, bytes):
                newline = newline.decode('utf-8')
        if newline == empty:
            return data
        if newline == None:
            return re.sub(regex, new_newline, data)
        if isinstance(newline, re.Pattern):
            return re.sub(newline, new_newline, data)
        if isinstance(newline, data_type):
            return data.replace(newline, new_newline)
        raise AssertionError(
            f"can't understand newline of type {type(newline)};"
            f" expected none, empty string, regex, bytes or string"
            f" (data_type {data_type})")


    def _read(self, console = None, offset = 0, _max_size = 0, fd = None,
              newline = None,
              **ttbd_iface_call_kwargs):
        """
        Read data received on the target's console

        :param str console: (optional) console to read from
        :param int offset: (optional) offset to read from (defaults to zero)
        :param int fd: (optional) file descriptor to which to write
          the output (in which case, it returns the bytes read).
        :returns: tuple consisting of:
          - stream generation
          - stream size after reading
          - data read (or if written to a file descriptor,
            amount of bytes read)

        *_max_size* is ignored, it is currently kept for backwards compat.
        """
        assert console == None or isinstance(console, str)
        assert offset >= 0
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
                        stream = True, raw = True,
                        **ttbd_iface_call_kwargs)) as r:
                # http://docs.python-requests.org/en/master/user/quickstart/#response-content
                # when doing raw streaming, the call returns
                # bytes--it's up to the customer to pass the right
                # file descriptor
                chunk_size = 1024
                total = 0
                for chunk in r.iter_content(chunk_size):
                    while True:
                        try:
                            chunk_len = len(chunk)
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
                    total += chunk_len
                fd.flush()
                ret = total
                l = total
        else:
            # read from the stream, to a stream, return it
            r = target.ttbd_iface_call("console", "read", method = "GET",
                                       component = console, offset = offset,
                                       raw = True,
                                       **ttbd_iface_call_kwargs)
            ret = self._newline_convert(r.text, newline)
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


    def read(self, console = None, offset = 0, max_size = 0, fd = None,
             newline = None,
             # when reading, we are ok with retrying a lot, since
             # this is an idempotent operation
             retry_timeout = 60, retry_backoff = 0.1,
             **ttbd_iface_call_kwargs):
        """
        Read data received on the target's console

        :param str console: (optional) console to read from

        :param int offset: (optional) offset to read from (defaults to
          zero)

        :param int fd: (optional) file descriptor to which to write
          the output (in which case, it returns the bytes read).

          This file needs to be opened in binary mode.

        :param int max_size: (ignored)

        :param newline: (optional, defaults to *None*, universal)
          convention for end-of-line characters.

          - *None* any of *\\r*, *\\n*, *\\r\\n* or multile *\\r* followed
            by a *\\n* are considered a newline and replaced with *\\n*

          - *''* (empty string): no translation is done

          - a string: the string is considered an end of line
            character and replaced by a *\\n*. Most common characters
            would be *\\r*, *\\n* or *\\r\\n*.

          - a regular expresion: whatever matches the regular
            expression is replaced with a *\\n*.

        Retry parameters as to :meth:`tcfl.tc.target_c.ttbd_iface_call`.

        :returns: data read (or if written to a file descriptor,
          amount of bytes read)
        """
        return self._read(console = console, offset = offset,
                          fd = fd, newline = newline,
                          retry_timeout = retry_timeout,
                          retry_backoff = retry_backoff,
                          **ttbd_iface_call_kwargs)[2]


    def read_full(self, console = None, offset = 0, max_size = 0, fd = None,
                  newline = None,
                  # when reading, we are ok with retrying a lot, since
                  # this is an idempotent operation
                  retry_timeout = 60, retry_backoff = 0.1,
                  **ttbd_iface_call_kwargs):
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

          This file needs to be opened in binary mode.

        :param int max_size: (ignored) deprecated and not used anymore

        :param newline: (optional, defaults to *None*, universal)
          convention for end-of-line characters.

          - *None* any of *\\r*, *\\n*, *\\r\\n* or multile *\\r* followed
            by a *\\n* are considered a newline and replaced with *\\n*

          - *''* (empty string): no translation is done

          - a string: the string is considered an end of line
            character and replaced by a *\\n*. Most common characters
            would be *\\r*, *\\n* or *\\r\\n*.

          - a regular expresion: whatever matches the regular
            expression is replaced with a *\\n*.

        Retry parameters as to :meth:`tcfl.tc.target_c.ttbd_iface_call`.

        :returns: tuple consisting of:

          - stream generation

          - stream size after reading

          - data read (or if written to a file descriptor,
            amount of bytes read)

        """
        return self._read(console = console, offset = offset,
                          fd = fd, newline = newline,
                          retry_timeout = retry_timeout,
                          retry_backoff = retry_backoff,
                          **ttbd_iface_call_kwargs)

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

    #: Default chunk sizes for the different consoles
    #:
    #: Dictionary keyed by console name that specifies the chunk size
    #: for the console; if there is no entry for a console, it means
    #: no chunking is to be done for it.
    #:
    #: See :meth:write.
    #:
    #: This can be set with::
    #:
    #:    >> target.console.chunk_size['my consolename'] = 32
    chunk_size = {}


    #: Default interchunk wait times (in seconds) for the different consoles
    #:
    #: Dictionary keyed by console name that specifies the time to
    #: wait between sending chunks for each console when chunking is enabled.
    #:
    #: See :meth:write.
    #:
    #: This can be set with::
    #:
    #:    >> target.console.interchunk_wait['my consolename'] = 3.4
    interchunk_wait = {}

    def write(self, data, console = None,
              chunk_size = None, interchunk_wait = None):
        """Write data to a console

        :param data: data to write (string or bytes)

        :param int chunk_size: (optional) break the transimission into
          chunks of this size, with a possible wait of
          *interchunk_wait* seconds between. By default no chunking
          occurs.

          This is useful when the receiving end doesn't have good flow
          control and needs breathers or we want to simulate some
          timing. The server in theory can implement it better, but
          when the server configuration doesn't offer it, this offers
          a way to force it from the client side.

          Global chunking per console can be set in :data:chunk_size.

        :param float interchunk_wait: (optional; default 0) seconds to
          wait in between transmitting chunks when *chunk_size* is
          enabled.

          Note the lag of making the remote request has to be
          considered; thus interchunk waits of less than one second
          might be impractical. Look at doing chunk in the server side
          for those timing needs.

          Global interchunk waits per console can be set in
          :data:interchunk_wait.

        :param str console: (optional) console to write to

        .. warning:: this function does no end-of-line conversions (eg
           \\r to \\r\\n or \\n to \\r\\n, etc). For that, look into
           :meth:`target.send <tcfl.tc.target_c.send>`.
        """
        assert isinstance(data, (str, bytes))
        if isinstance(data, bytes):
            # to send the data over the wire we need to convert it to
            # UTF-8 anyway, so we might as well do it now.
            data = data.encode('utf-8')
        assert chunk_size == None or isinstance(chunk_size, int)
        assert interchunk_wait == None \
            or isinstance(interchunk_wait, numbers.Real)
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
        if chunk_size == None:
            chunk_size = self.chunk_size.get(console, None)
        if interchunk_wait == None:
            interchunk_wait = self.interchunk_wait.get(console, None)

        if chunk_size == None:
            self.target.ttbd_iface_call("console", "write",
                                        component = console, data = data)
        else:
            for i in range(int((len(data) + chunk_size - 1) / chunk_size)):
                chunk = data[chunk_size * i : chunk_size * i + chunk_size]
                self.target.ttbd_iface_call("console", "write",
                                            component = console, data = chunk)
                if interchunk_wait:
                    time.sleep(interchunk_wait)
        self.target.report_info("%s: wrote %dB (%s) to console"
                                % (console, len(data), data_report),
                                dlevel = 1)

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

        :param int report: (optional) how much data to report; when we
          find a match, the report will include all data received until
          the match; sometimes it is too much and uneeded. This allows
          to specify how many bytes of data before the match are going
          to be reported at most. Defaults to *None* (all).

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
        console = self._console_get(console)
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
        # if no detect context is given, we default to something
        # called as the console where we are looking
        if detect_context == "":
            detect_context = console
        with poll_state.lock:
            of = poll_state.buffers.get('of', None)
            if of:
                ofd = of.fileno()
                stat_info = os.fstat(ofd)
                search_offset = stat_info.st_size
            else:
                search_offset = 0
            poll_state.buffers[detect_context + 'search_offset'] = search_offset


    def capture_complete(self, *consoles):
        """Complete the local capture of one or more console--meaning read
        everything extra the server might already have and append it
        to the local capture file (reported by
        :meth:`capture_filename` or :meth:`text_capture_file`).

        :param list(str) consoles: (optional, default all) names of
          the console whose capture has to be completed

        >>> target.console.capture_complete()                  # complete capturing all consoles
        >>> target.console.capture_complete("serial0", "ssh0") # only serial0 and ssh0

        When a console has been used with functions such as
        :meth:`<target.expect> tcfl.target_c.expect`,
        :meth:`target.send <tcfl.target_c.send>',
        :meth:`target.shell.run <tcfl.target_ext_shell.extension.run>,
        etc that involves a console expecter
        (:class:`expect_text_on_console_c`), a local capture of it is
        kept in the system (usually called
        *report-HASHID.console-NAME.TARGETNAMENAME.CONSOLENAME.txt*,
        with the beginning matching
        :data:`tcfl.tc_c.report_file_prefix`.

        This function queries the server for any more output available
        for that console and appending it to the one already captured.

        """
        # The normal reading of a console is done inside the expect
        # flow, that creates a console_expecter using
        # target.console.text(), yielding a expect_text_on_console_c.
        #
        # To poll the console (read) that creates a poll context in
        # the testcase structure [_poll_state] which is indexed by the
        # poll context. The poll context is global to the target and
        # console names, so that multiple expecters readers etc can
        # share the same read data.
        #
        # Once we have that, we just poll a couple times to get the
        # data.
        #
        # Why so complicted? Because the local capture file might have
        # the capture data involving multiple generations of the
        # console (from the console being turned off and on, for
        # example, due to a power-cycle) -- so this respects that and
        # gives you a full capture.
        #
        target = self.target
        if not consoles:
            consoles = self.list()
        for console in consoles:
            if console in [ 'default', 'preferred' ]:
                # these are aliases -- real consoles will be picked up
                continue

            # ensure there is a polling context for this console--just
            # sync, even if we are not going to send anything, since
            # this creates the context
            self.send_expect_sync(console)

            console_expecter = target.console.text(
                "unused", console = console,
                timeout = 0, name = "completing console capture")
            poll_context = console_expecter.poll_context()
            with target.testcase.lock:
                poll_state = target.testcase._poll_state[poll_context]
            # try a couple of times to get more data from the
            # console--don't over do it, in case we have a misbehaving SUT
            # that is spewing Gigs nonstop, we don't want to be reading
            # here for ever.
            console_expecter.poll(
                target, "completing console capture", poll_state.buffers)
            console_expecter.poll(
                target, "completing console capture", poll_state.buffers)


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
                        if not line.endswith(b"\n"):
                            yield "\n"
                        break
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            yield u""

    def captured_chunk(self, console, offset_from = 0, size = -1):
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
        :param int len: (optional) how much to read; if negative
          (default), read the whole file since the offset
        """
        assert console == None or isinstance(console, str)
        #
        # Provide line-based iteration on the last match in the
        # console, as given by information on the buffers.
        #
        target = self.target
        # Open as binary so we don't alter the offset counts if it
        # happens to fix up characters
        with io.open(target.console.capture_filename(console), "rb") as f:
            f.seek(offset_from)
            return f.read()


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
