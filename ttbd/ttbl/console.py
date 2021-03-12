#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Access target's serial consoles / bidirectional channels
--------------------------------------------------------

Implemented by :class:`ttbl.console.interface`.

HTTP protocol description :ref:`<http_target_console>`.
"""

import codecs
import contextlib
import errno
import fcntl
import numbers
import os
import socket
import stat
import struct
import sys
import time
import tty

import commonl
import ttbl
import ttbl.power

import pexpect
try:
    # FIXME: we don't prolly need this anymore
    from pexpect.exceptions import TIMEOUT as pexpect_TIMEOUT
    from pexpect.exceptions import EOF as pexpect_EOF
except ImportError:
    from pexpect import TIMEOUT as pexpect_TIMEOUT
    from pexpect import EOF as pexpect_EOF
try:
    import pexpect.fdpexpect
except ImportError:
    # RHEL 7 -> fdpexpect is a separate module, not a submod of pexpectg    import fdpexpect
    import fdpexpect
    pexpect.fdpexpect = fdpexpect

class impl_c(ttbl.tt_interface_impl_c):
    """
    Implementation interface for a console driver

    The target will list the available consoles in the targets'
    *consoles* tag

    :param list command_sequence: (optional) when the console is
      enabled (from :meth:`target.console.enable
      <tcfl.target_ext_console.extension.enable>` or when powering up
      a target that also enables the console at the same time via
      :meth:`target.power.on <tcfl.target_ext_power.extension.on>`),
      run a sequence of send/expect commands.

      This is commonly used when the serial line is part of a server
      and a set of commands have to be typed before the serial
      connection has to be established. For example, for some
      Lantronix KVM serial servers, when accessing the console over
      SSH we need to wait for the prompt and then issue a *connect
      serial* command; see :class:ttbl.lantronix.console_spider_duo_pc;
      it looks like:

      >>> serial0_pc = ttbl.console.ssh_pc(
      >>>     "USER:PASSWORD@LANTRONIXHOSTNAME",
      >>>     command_sequence = [
      >>>       ## Welcome to the Lantronix SLSLP
      >>>       ## Firmware: version 030031, build 38120
      >>>       ## Last login: Thu Jan  1 00:04:20 1970 from 10.24.11.35
      >>>       ## Current time: Thu Jan  1 00:02:03 1970
      >>>       ## For a list of commands, type 'help'
      >>>
      >>>       # command prompt, 'CR[USERNAME@IP]> '... or not, so just
      >>>       # look for 'SOMETHING> '
      >>>       # ^ will not match because we are getting a Carriage
      >>>       # Return / New Line
      >>>       (
      >>>           # send a disconnect just in case it is connected
      >>>           # and wait for the command prompt
      >>>           "\\x1bexit\\r\\n",
      >>>           # command prompt, 'CR[USERNAME@IP]> '... or not, so just
      >>>           # look for 'SOMETHING> '
      >>>           # ^ will not match because we are getting a CR
      >>>           re.compile("[^>]+> ")
      >>>       ),
      >>>       (
      >>>           "connect serial\\r\\n",
      >>>           "To exit serial port connection, type 'ESC exit'."
      >>>       ),
      >>>     ],
      >>>     extra_opts = {
      >>>         # old, but that's what the Lantronix server has :/
      >>>         "KexAlgorithms": "diffie-hellman-group1-sha1",
      >>>         "Ciphers" : "aes128-cbc,3des-cbc",
      >>>     })

      This list a list of:

      - tupples *( SECONDS, COMMENT )*: wait SECONDs, printing COMMENT
        in the logs

      - tupples *( SEND, EXPECT )*; *SEND* is a string
        sent over to the console (unless the empty string; then nothing
        is sent).  *EXPECT* can be anything that can be fed to Python's
        Expect :meth:`expect <pexpect.spawn.expect>` function:

        - a string

        - a compiled regular expression

        - a list of such

      The timeout for each expectation is hardcoded to five seconds
      (FIXME).

      Note for this to work, the driver that uses this class must call
      the *_command_sequence_run()* method from their
      :meth:`impl_c.enable` methods.

    :param int command_timeout: (optional) number of seconds to wait
      for a response ot a command before declaring a timeout

    :param str crlf: (optional; default *None*) newline convention for
      this console; this is informational for the clients, to know which
      string they need to use as end of line; the only practical
      choices are:

      - ``\\r``: one carriage return
      - ``\\n``: one new line
      - ``\\r\\n``: one carriage return followed by a new line

    """
    def __init__(self, command_sequence = None, command_timeout = 5,
                 crlf = '\r'):
        assert command_sequence == None \
            or isinstance(command_sequence, list), \
            "command_sequence: expected list of tuples; got %s" \
            % type(command_sequence)
        assert command_timeout > 0
        self.command_sequence = command_sequence
        self.command_timeout = command_timeout
        self.parameters = {}
        assert crlf == None or isinstance(crlf, str), \
            "console implementation declares CRLF with" \
            " a type %s; expected string" % type(crlf)
        ttbl.tt_interface_impl_c.__init__(self)
        #: Check if the implementation's link died and it has to be
        #: re-enabled
        #:
        #: Some implementations of console die because their
        #: connections get killed outside of the implementation's
        #: control. Setting this to True allows the console code to
        #: periodically when reading so that if the implementation
        #: reports is disabled because the link died but it should be
        #: enabled, it will be automatically re-enabled.
        self.re_enable_if_dead = False
        self.crlf = crlf

    class exception(Exception):
        """
        General console driver exception
        """
        pass

    class timeout_e(exception):
        """
        Console enablement command sequence timed out
        """
        pass

    def enable(self, target, component):
        """
        Enable a console

        :param str component: console to enable
        """
        if self.command_sequence:
            try:
                self._command_sequence_run(target, component)
            except:
                target.log.info("%s: disabling since command sequence"
                                " for enabling failed" % component)
                self.disable(target, component)
                raise
        target.property_set("interfaces.console." + component + ".state", True)

    def disable(self, target, component):
        """
        Disable a console

        :param str console: (optional) console to disable; if missing,
          the default one.
        """
        target.property_set("interfaces.console." + component + ".state", False)

    def state(self, target, component):
        """
        Return the given console's state

        :param str console: (optional) console to enable; if missing,
          the default one
        :returns: *True* if enabled, *False* otherwise
        """
        raise NotImplementedError("%s/%s: console state not implemented"
                                  % (target.id, component))
        #return False

    def setup(self, target, component, parameters):
        """
        Setup console parameters (implementation specific)

        Check :meth:`impl_c.read` for common parameters

        :param dict parameters: dictionary of implementation specific
          parameters
        :returns: nothing
        """
        raise NotImplementedError("%s/%s: console control not implemented"
                                  % (target.id, component))

    def read(self, target, component, offset):
        """
        Return data read from the console since it started recording
        from a given byte offset.

        Check :meth:`impl_c.read` for common parameters

        :params int offset: offset from which to read

        :returns: data dictionary of values to pass to the client; the
          data is expected to be in a file which will be streamed to
          the client.

          >>> return dict(stream_file = CAPTURE_FILE,
          >>>             stream_generation = MONOTONIC,
          >>>             stream_offset = OFFSET)

          this allows to support large amounts of data automatically;
          the generation is a number that is monotonically increased,
          for example, each time a power cycle happens. This is
          basically when a new file is created.
        """
        raise NotImplementedError("%s/%s: console control not implemented"
                                  % (target.id, component))
        #return dict(stream_file = CAPTURE_FILE, stream_offset = OFFSET,
        #            stream_generation = NUMBER)

    def size(self, target, component):
        """
        Return the amount of data currently read from the console.

        Check :meth:`impl_c.read` for common parameters

        :returns: number of bytes read from the console since the last
          power up.
        """
        raise NotImplementedError("%s/%s: console size not implemented"
                                  % (target.id, component))

    def write(self, target, component, data):
        """
        Write bytes the the console

        Check :meth:`impl_c.read` for common parameters

        :param data: string of bytes or data to write to the console
        """
        raise NotImplementedError("%s/%s: console control not implemented"
                                  % (target.id, component))



    def _log_expect_error(self, target, console, expect, msg):
        target.log.error("%s: expect error: %s" % (console, msg))
        if isinstance(expect.before, str):
            for line in expect.before.splitlines():
                target.log.error("%s: expect output[before]: %s"
                                 % (console, line.strip()))
        else:
            target.log.error("%s: expect output[before]: %s"
                             % (console, expect.before))
        if isinstance(expect.after, str):
            for line in expect.after.splitlines():
                target.log.error("%s: expect output[after]: %s"
                                 % (console, line.strip()))
        else:
            target.log.error("%s: expect output[after]: %s"
                             % (console, expect.after))

    def _response(self, target, console, expect, response, timeout,
                  response_str, count):
        ts0 = time.time()
        ts = ts0
        while ts - ts0 < timeout:
            try:
                r = expect.expect(response, timeout = timeout - (ts - ts0))
                ts = time.time()
                target.log.info("%s: found response: [+%.1fs] #%d r %s: %s"
                                % (console, ts - ts0, count, r, response_str))
                return
            except pexpect_TIMEOUT as e:
                self._log_expect_error(target, console, expect, "timeout")
                # let's try again, if we full timeout, it will be raised below
                time.sleep(0.5)
                continue
            except pexpect_EOF as e:
                ts = time.time()
                offset = os.lseek(expect.fileno(), 0, os.SEEK_CUR)
                self._log_expect_error(target, console, expect,
                                       "EOF at offset %d" % offset)
                time.sleep(0.5)
                continue
            except Exception as e:
                self._log_expect_error(target, console, expect, str(e))
                raise
        if ts - ts0 >= timeout:
            self._log_expect_error(target, console, expect, "timeout")
            raise self.timeout_e(
                "%s: timeout [+%.1fs] waiting for response: %s"
                % (console, timeout, response_str))

    def _command_sequence_run(self, target, component):
        write_file_name = os.path.join(target.state_dir,
                                       "console-%s.write" % component)
        read_file_name = os.path.join(target.state_dir,
                                      "console-%s.read" % component)
        log_file_name = os.path.join(
            target.state_dir, "console-%s.command.log" % component)
        with codecs.open(read_file_name, "r", encoding = 'utf-8') as rf, \
             open(write_file_name, "w") as wf, \
             open(log_file_name, "w+") as logf:
            timeout = self.command_timeout
            rfd = rf.fileno()
            flag = fcntl.fcntl(rfd, fcntl.F_GETFL)
            fcntl.fcntl(rfd, fcntl.F_SETFL, flag | os.O_NONBLOCK)
            expect = pexpect.fdpexpect.fdspawn(rf, logfile = logf,
                                               timeout = timeout,
                                               encoding='utf-8')
            count = 0
            for command, response in self.command_sequence:
                if isinstance(command, (int, float)):
                    target.log.info("%s: waiting %ss for '%s'"
                                    % (component, command, response))
                    time.sleep(command)
                    count += 1
                    continue
                if command:
                    target.log.info(
                        "%s: writing command: %s"
                        % (component, command.encode('unicode-escape',
                                                     errors = 'replace')))
                    wf.write(command)
                if response:
                    if hasattr(response, "pattern"):
                        response_str = "(regex) " + response.pattern
                    else:
                        response_str = response
                    target.log.debug("%s: expecting response: %s"
                                     % (component, response_str))
                    self._response(target, component,
                                   expect, response, timeout, response_str,
                                   count)
                count += 1
        # now that the handshake has been done, kill whatever has been
        # read for it so we don't confuse it as console input
        with codecs.open(read_file_name, "w", encoding = 'utf-8') as rf:
            rf.truncate(0)

class interface(ttbl.tt_interface):
    """Interface to access the target's consoles

    An instance of this gets added as an object to the target object
    with:

    >>> ttbl.test_target.get('qu05a').interface_add(
    >>>     "console",
    >>>     ttbl.console.interface(
    >>>         ttyS0 = ttbl.console.serial_device("/dev/ttyS5")
    >>>         ttyS1 = ttbl.capture.generic("ipmi-sol")
    >>>         default = "ttyS0",
    >>>     )
    >>> )

    Note how *default* has been made an alias of *ttyS0*

    :param dict impls: dictionary keyed by console name and which
      values are instantiation of console drivers inheriting from
      :class:`ttbl.console.impl_c` or names of other consoles (to
      sever as aliases).

      Names have to be valid python symbol names following the
      following convention:

      - *serial\**: RS-232C compatible physical Serial port
      - *sol\**: IPMI Serial-Over-Lan
      - *ssh\**: SSH session (may require setup before enabling and
        *enabling* before using)

    A *default* console is set by declaring an alias as in the example
    above; otherwise the first one listed in
    target.console.impls.keys() is considered the default. A
    *preferred* console is the one that has *preferred* as an alias.

    This interface:

    - supports N > 1 channels per target, of any type (serial,
      network, etc)

    - allows raw traffic (not just pure ASCII), for example for serial
      console escape sequences, etc

    - the client shall not need to be constantly reading to avoid
      loosing data; the read path shall be (can be) implemented to
      buffer everything since power on (by creating a power control
      driver :class:`ttbl.power.impl_c` that records everything; see
      :class:`ttbl.console.serial_pc` for an example

    - allows setting general channel parameters


    """
    def __init__(self, *impls, **kwimpls):
        ttbl.tt_interface.__init__(self)
        # the implementations for the console need to be of type impl_c
        self.impls_set(impls, kwimpls, impl_c)

    def _pre_off_disable_all(self, target):
        for console, impl in self.impls.items():
            target.log.info("%s: disabling console before powering off",
                            console)
            impl.disable(target, console)

    def _target_setup(self, target, iface_name):
        # Called when the interface is added to a target to initialize
        # the needed target aspect (such as adding tags/metadata)
        target.properties_user.add("interfaces.console.default")
        target.properties_keep_on_release.add("interfaces.console.default")
        # When the target is powered off, disable the consoles -- why?
        # because things like consoles over SSH will stop working, no
        # matter what, and we want it to fail early and not seem there
        # is something odd.
        target.power_off_pre_fns.append(self._pre_off_disable_all)
        for console, impl in self.impls.items():
            if impl.crlf:
                # if it declares a CRLF string, publish it
                assert isinstance(impl.crlf, str), \
                    "%s: target declares CRLF for console %s with" \
                    " a type %s; expected string" % (
                        target.id, console, type(impl.crlf))
                target.fsdb.set("interfaces.console." + console + ".crlf",
                                impl.crlf)


    def _release_hook(self, target, _force):
        # nothing to do on target release
        pass

    # called by the daemon when a METHOD request comes to the HTTP path
    # /ttb-vVERSION/targets/TARGET/interface/console/CALL

    def get_setup(self, _target, _who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        parameters = dict(impl.parameters)
        parameters['real_name'] = component
        return dict(result = parameters)

    def get_default_name(self, target):
        """
        Returns the name of the default console

        The default console is defined as:

        - the name of an existing console in a tag called
          *console-default*

        - the name of a console called *default*

        - the first console defined

        :param ttbl.test_target target: target on which to find the
          default console's name

        :returns str: the name of the default console
        :raises: *RuntimeError* if there are no consoles
        """
        console_default = target.property_get("interfaces.console.default", None)
        try:
            _impl, name = self.impl_get_by_name(console_default, "console")
            return default
        except IndexError:
            # invalid default, reset it
            console_default = target.property_set("interfaces.console.default", None)
            # fallthrough
        _impl, name = self.arg_impl_get("default", "console", True)
        if name:
            return name
        consoles = self.impls.keys()
        if not consoles:
            raise RuntimeError("%s: there are no consoles, can't find default"
                               % target.id)
        return consoles[0]

    def put_setup(self, target, who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        parameters = dict()
        for k in list(args.keys()):
            # get the argument with arg_get, since some of it might be
            # JSON encoded
            parameters[k] = self.arg_get(args, k, arg_type = None)
        if 'ticket' in parameters:
            del parameters['ticket']
        del parameters['component']
        assert all(isinstance(i, str) for i in list(parameters.values())), \
            'console.setup#parameters should be a dictionary keyed ' \
            'by string, values being strings'
        with target.target_owned_and_locked(who):
            target.timestamp()
            return impl.setup(target, component, parameters)

    def get_list(self, _target, _who, _args, _files, _user_path):
        return dict(
            aliases = self.aliases,
            result = list(self.aliases.keys()) + list(self.impls.keys()))

    def put_enable(self, target, who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        with target.target_owned_and_locked(who):
            target.timestamp()
            state = impl.state(target, component)
            if not state:
                impl.enable(target, component)
            return dict()

    def put_disable(self, target, who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        with target.target_owned_and_locked(who):
            target.timestamp()
            state = impl.state(target, component)
            if state:
                impl.disable(target, component)
            return dict()

    def get_state(self, target, _who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        state = impl.state(target, component)
        self.assert_return_type(state, bool, target,
                                component, "console.state")
        return dict(result = state)

    @staticmethod
    def _maybe_re_enable(target, component, impl):
        # Some implementations have the bad habit of dying for no good
        # reason:
        #
        #  - IPMIs SOLs close the connections
        #  - ssh tunnels get killed without timing out
        #  - dog eat the homework
        #
        # and there is nothing we can do about it but just try to
        # restart it if it reports disabled (because the link is dead)
        # but we recorded it shall be enabled (because the property
        # console-COMPONENT.state is True)
        if impl.re_enable_if_dead == False:
            return False
        shall_be_enabled = target.property_get("interfaces.console." + component + ".state", None)
        is_enabled = impl.state(target, component)
        if shall_be_enabled and is_enabled == False:
            # so it died, let's re-enable and retry
            target.log.warning("%s: console disabled on its own, re-enabling"
                               % component)
            impl.enable(target, component)
            return True
        return False

    def get_read(self, target, who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        offset = int(args.get('offset', 0))
        if target.target_is_owned_and_locked(who):
            target.timestamp()	# only if the reader owns it
        last_enable_check = target.property_get("interfaces.console." + component + ".check_ts", 0)
        ts_now = time.time()
        if ts_now - last_enable_check > 5:
            # every five secs check if the implementation's link has
            # been closed and renable it if so
            self._maybe_re_enable(target, component, impl)
            target.property_set("interfaces.console." + component + ".check_ts", ts_now)
        r = impl.read(target, component, offset)
        stream_file = r.get('stream_file', None)
        if stream_file and not os.path.exists(stream_file):
            # no file yet, no console output
            return {
                'stream_file': '/dev/null',
                'stream_generation': 0,
                'stream_offset': 0
            }
        return r

    def get_size(self, target, _who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        size = impl.size(target, component)
        self.assert_return_type(size, int, target,
                                component, "console.size", none_ok = True)
        return dict(result = size)

    def put_write(self, target, who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        with target.target_owned_and_locked(who):
            target.timestamp()
            while True:
                try:
                    impl.write(target, component,
                               self.arg_get(args, 'data', str, False))
                    break
                except OSError:
                    # sometimes many of these errors happen because the
                    # implementation dies -- for IPMIs SOL, for example,
                    # the other end closes the connection, so we try to
                    # restart it
                    if self._maybe_re_enable(target, component, impl):
                        continue
                    raise
            return {}

def generation_set(target, console):
    target.fsdb.set("interfaces.console." + console + ".generation",
                    # trunc the time and make it a string
                    str(int(time.time())))

class generic_c(impl_c):
    """General base console implementation

    This object will implement a base console driver that reads from a
    file in the (the read file) and writes to a file (the write file)
    in the local filesystem.

    The read / write files are named
    ``console-CONSOLENAME.{read,write}`` and are located in the
    target's state directory. Thus there is no need for state, since
    the parameters are available in the call.

    The idea is that another piece (normally a power control unit that
    starts a background daemon) will be reading from the console in
    the target system and dumping data to the read file. For writing,
    the same piece takes whatever data is being provided and passes it
    on, or it can be written directly.

    See :class:`serial_pc` for an example of this model implemented
    over a tranditional serial port and
    :class:`ttbl.ipmi.sol_console_pc` for implementing an IPMI
    Serial-Over-Lan console. :class:`ssh_pc` for implementing a
    console simulated over an SSH connection.

    :param int chunk_size: (optional) when writing, break the writing
      in chunks of this size and wait *interchunk_wait* in between
      sending each chunk. By default is 0, which is disabled.

    :param float interchunk_wait: (optional) if *chunk_size* is
      enabled, time to wait in seconds in between each chunk.

    :param dict escape_chars: (optional) dictionary of escape
      sequences for given characters to prefix in input stream.

      If given, this is a dictionary of characters to strings, eg:

      >>> escape_chars = {
      >>>   '\\x1b': '\\x1b',
      >>>   '~': '\\',
      >>> }

      in this case, when the input string to send to the device
      contains a *\\x1b* (the ESC character), it will be prefixed with
      another one. If it contains a *~*, it will be prefixed with a
      backslash.

    """
    def __init__(self, chunk_size = 0, interchunk_wait = 0.2,
                 command_sequence = None, escape_chars = None,
                 crlf = '\r'):
        assert chunk_size >= 0
        assert interchunk_wait > 0
        assert escape_chars == None or isinstance(escape_chars, dict)

        self.chunk_size = chunk_size
        self.interchunk_wait = interchunk_wait
        impl_c.__init__(self, command_sequence = command_sequence,
                        crlf = crlf)
        if escape_chars == None:
            self.escape_chars = {}
        else:
            self.escape_chars = escape_chars

    def state(self, target, component):
        # if the write file is gone, most times this means the thing
        # is disabled
        # we conifigure socat -- or whatever -- to kill this file when
        # stopped
        return os.path.exists(os.path.join(target.state_dir,
                                           "console-%s.write" % component))

    def read(self, target, component, offset):
        return dict(
            stream_file = os.path.join(target.state_dir,
                                       "console-%s.read" % component),
            stream_generation = target.fsdb.get(
                "interfaces.console." + component + ".generation", 0),
            stream_offset = offset
        )


    def size(self, target, component):
        state = self.state(target, component)
        if not self.state(target, component):
            return None
        try:
            file_name = os.path.join(target.state_dir,
                                     "console-%s.read" % component)
            return os.stat(file_name).st_size
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            # not even existing, so empty
            return 0

    def _escape(self, data):
        _data = type(data)()
        if isinstance(data, bytes):
            for c in data:
                if c in self.escape_chars:
                    _data += self.escape_chars[c] + struct.pack('B', c)
                else:
                    _data += struct.pack('B', c)
        else:
            for c in data:
                if c in self.escape_chars:
                    _data += self.escape_chars[c] + c
                else:
                    _data += c
        return _data



    def _write(self, fd, data):
        # this is meant for an smallish chunk of data; FIXME: make
        # data an iterator and encode/escape on the run? esp as we
        # might have to chunk anyway

        # os.write expects a byestring, so convert data to bytes
        if not isinstance(data, bytes):
            data = data.encode('utf-8')
        if self.escape_chars:	# if we have to escape, escape
            data = self._escape(data)
        if self.chunk_size:
            # somethings have no flow control and you need to make
            # it happen like...this
            # yeh, I know an iterator in python..yadah--this is
            # quite clear
            # Chunking is needed to feed to things like VMs console
            # inputs and some things whose flow control is not really
            # working as it should.
            left = len(data)
            itr = 0
            while left > 0:
                _chunk_size = min(left, self.chunk_size)
                os.write(fd, data[itr : itr + _chunk_size])
                time.sleep(self.interchunk_wait)
                itr += _chunk_size
                left -= _chunk_size
        else:
            os.write(fd, data)

    def write(self, target, component, data):
        file_name = os.path.join(target.state_dir,
                                 "console-%s.write" % component)
        target.log.debug("%s: writing %dB to console (%s)",
                         component, len(data), data.encode('unicode-escape'))
        stat_info = os.stat(file_name)
        if stat.S_ISSOCK(stat_info.st_mode):
            # consoles whose input is implemented as a socket
            with contextlib.closing(socket.socket(socket.AF_UNIX,
                                                  socket.SOCK_STREAM)) as f:
                f.connect(file_name)
                self._write(f.fileno(), data)
        else:
            mode = "a"
            while True:
                try:
                    with contextlib.closing(open(file_name, mode)) as f:
                        if stat.S_ISCHR(stat_info.st_mode):
                            # if we are writing to a terminal, disable
                            # all translations and buffering, we'll do
                            # them
                            tty.setraw(f.fileno())
                        self._write(f.fileno(), data)
                        break
                except EnvironmentError as e:
                    # Open in write mode if the file does not allow seeking
                    if e.errno == errno.ESPIPE:
                        target.log.warning(
                            "console %s: changing open mode to 'w'", component)
                        mode = "w"
                        continue
                    if e.errno == errno.ENOENT \
                       and target.property_get(
                           "console-" + component + ".state"):
                        target.log.error(
                            "console %s: console died? restarting", component)
                        self.enable(target, component)
                        continue
                    else:
                        raise

class serial_pc(ttbl.power.socat_pc, generic_c):
    """
    Implement a serial port console and data recorder

    This class implements two interfaces:

    - power interface: to start a serial port recorder in the
      background as soon as the target is powered on. Anything read
      form the serial port is written to the *console-NAME.read* file
      and anything written to it is written to *console-NAME.write*
      file, which is sent to the serial port.

      The power interface is implemented by subclassing
      :class:`ttbl.power.socat_pc`, which starts *socat* as daemon to
      serve as a data recorder and to pass data to the serial port
      from the read file.

    - console interface: interacts with the console interface by
      exposing the data recorded in *console-NAME.read* file and
      writing to the *console-NAME.write* file.

    :params str serial_file_name: (optional) name of the serial port
      file, which can be templated with *%(FIELD)s* as per
      class:`ttbl.power.socat_pc` (the low level implementation).

      By default, it uses */dev/tty-TARGETNAME*, which makes it easier
      to configure. The tty name linked to the target can be set with
      :ref:`udev <usb_tty>`.

    For example, create a serial port recoder power control / console
    driver and insert it into the power rail and the console of a
    target:

    >>> serial0_pc = ttbl.console.serial_pc(console_file_name)
    >>>
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "power",
    >>>     ttbl.power.interface(
    >>>         ...
    >>>         serial0_pc,
    >>>         ...
    >>>     )
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "console",
    >>>     ttbl.console.interface(
    >>>         serial0 = serial0_pc,
    >>>         default = "serial0",
    >>>     )
    >>> )

    """
    def __init__(self, serial_file_name = None):
        generic_c.__init__(self)
        if serial_file_name == None:
            serial_file_name = "/dev/tty-%(id)s"
        else:
            serial_file_name = serial_file_name
        ttbl.power.socat_pc.__init__(
            self,
            # note it is important to do the rawer first thing, then
            # do the settings; rawer resets to raw state
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            "%s,creat=0,rawer,b115200,parenb=0,cs8,bs1" % serial_file_name)
        self.upid_set("RS-232C serial port @%s" % serial_file_name,
                      name = "RS-232C serial port",
                      baud_rate = 115200,
                      data_bits = 8,
                      stop_bits = 1,
                      serial_port = serial_file_name,
        )

    # console interface; state() is implemented by generic_c
    def on(self, target, component):
        ttbl.power.socat_pc.on(self, target, component)
        generation_set(target, component)
        generic_c.enable(self, target, component)

    def off(self, target, component):
        generic_c.disable(self, target, component)
        ttbl.power.socat_pc.off(self, target, component)

    def enable(self, target, component):
        self.on(target, component)

    def disable(self, target, component):
        return self.off(target, component)

    def state(self, target, component):
        # we want to use this to gather state, since the generic_c
        # implementation relies on the console-NAME.write file
        # existing; this can linger if a process dies or not...
        # but the ttbl.power.socat_pc.get() implementation checks if
        # the process is alive looking at the PIDFILE
        # COMPONENT-socat.pid and verifying that thing is still running
        return ttbl.power.socat_pc.get(self, target, component)


class general_pc(ttbl.power.socat_pc, generic_c):
    """Implement a general console/data recorder

    When an implementation creates a file we can write to to get data
    into a console (represented as *STATEDIR/console-NAME.write*),
    this implementation will write to said file on *write()* and
    whatever is read from said file, will be recorded to
    *STATEDIR/console-NAME.read*).

    This class is different to similarly name
    :class:`ttbl.console.generic_c` in that this implements a full
    console and *generic_c* is a building block.

    Use cases:

    - QEMU/virtualized target which represents its console via a
      Unix socket or PTY -- the driver target, before starting the
      serial console symlinks *STATEDIR/console-NAME.write* to
      */dev/pts/XYZ*, (see ttbl.qemu._qemu_console_on() as an
      example).

    Do not use this for:

    - Serial port consoles (use :class:`serial_pc`)

    - Consoles over SSH or telnet (use :class:`ssh_pc` or
      :class:`telnet_pc`)

    - Exposing logfiles (use :class:`logfile_c`)

    This class, given a file where to capture from, implements two
    interfaces:

    - power interface: starts a a recorder in the background on power
      on which will write to *console-NAME.read* anything read from
      file *console-NAME.write*, which is assumed to exist.

      The power interface is implemented by subclassing
      :class:`ttbl.power.socat_pc`, which starts *socat* as daemon to
      serve as a data recorder.

    - console interface: interacts with the console interface by
      exposing the data recorded in *console-NAME.read* file and
      writing to the *console-NAME.write* file.

    :params str file_name: (optional) name of file to use as source of
      data and sink. Defaults to *console-NAME.write*, where *NAME*
      is the name under which the console is registered.

    For example, create a serial port recoder power control / console
    driver and insert it into the power rail and the console of a
    target:

    >>> console_pc = ttbl.console.general_pc()
    >>>
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "power",
    >>>     ttbl.power.interface(
    >>>         ...
    >>>         console_pc,
    >>>         ...
    >>>     )
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "console",
    >>>     ttbl.console.interface(
    >>>         serial0 = console_pc,
    >>>         default = "serial0",
    >>>     )
    >>> )

    """
    def __init__(self, file_name = None, **kwargs):
        generic_c.__init__(self, **kwargs)
        assert file_name == None or isinstance(file_name, str)
        if file_name == None:
            self.file_name = "console-%(component)s.write"
        else:
            self.file_name = file_name
        ttbl.power.socat_pc.__init__(
            self,
            f"GOPEN:{self.file_name},rawer",
            "CREATE:console-%(component)s.read",
            # make it unidirectional; we only need to capture whatever
            # comes in the .write file to the read file.
            extra_cmdline = [ "-u" ])
        if file_name:
            self.upid_set(f"General console @{file_name}",
                          name = f"general-console{file_name}",
                          file_name = file_name,)
        else:
            self.upid_set("General console",
                          name = "general-console")

    # console interface; state() is implemented by generic_c
    def on(self, target, component):
        ttbl.power.socat_pc.on(self, target, component)
        generation_set(target, component)
        generic_c.enable(self, target, component)

    def off(self, target, component):
        generic_c.disable(self, target, component)
        ttbl.power.socat_pc.off(self, target, component)

    def enable(self, target, component):
        self.on(target, component)

    def disable(self, target, component):
        return self.off(target, component)

    def state(self, target, component):
        # we want to use this to gather state, since the generic_c
        # implementation relies on the console-NAME.write file
        # existing; this can linger if a process dies or not...
        # but the ttbl.power.socat_pc.get() implementation checks if
        # the process is alive looking at the PIDFILE
        # COMPONENT-socat.pid and verifying that thing is still running
        return ttbl.power.socat_pc.get(self, target, component)


class ssh_pc(ttbl.power.socat_pc, generic_c):
    """Implement a serial port over an SSH connection

    This class implements two interfaces:

    - power interface: to start an SSH connection recorder in the
      background as soon as the target is powered on.

      The power interface is implemented by subclassing
      :class:`ttbl.power.socat_pc`, which starts *socat* as daemon to
      serve as a data recorder and to pass data to the connection
      from the read file.

      Anything read form the SSH connection is written to the
      *console-NAME.read* file and anything written to it is written
      to *console-NAME.write* file, which is sent to the serial port.

    - console interface: interacts with the console interface by
      exposing the data recorded in *console-NAME.read* file and
      writing to the *console-NAME.write* file.

    :params str hostname: *USER[:PASSWORD]@HOSTNAME* for the SSH server

    :param int port: (optional) port to connect to (defaults to 22)

    :param dict exta_ports: (optional) dictionary of extra SSH options
      and values to set in the SSH configuration (as described in
      :manpage:`ssh_config(5)`.

      Note they all have to be strings; e.g.:

      >>> ssh0_pc = ttbl.console.ssh_pc(
      >>>     "USER:PASSWORD@HOSTNAME",
      >>>     extra_opts = {
      >>>         "Ciphers": "aes128-cbc,3des-cbc",
      >>>         "Compression": "no",
      >>>     })

      Be careful what is changed, since it can break operation.

    See :class:`generic_c` for descriptions on *chunk_size* and
    *interchunk_wait*, :class:`impl_c` for *command_sequence*.

    Other parameters as to :class:ttbl.console.generic_c

    For example:

    >>> ssh0_pc = ttbl.console.ssh_pc("USERNAME:PASSWORD@HOSTNAME")
    >>>
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "power",
    >>>     ttbl.power.interface(
    >>>         ...
    >>>         ssh0_pc,
    >>>         ...
    >>>     )
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "console",
    >>>     ttbl.console.interface(
    >>>         ssh0 = ssh0_pc,
    >>>     )
    >>> )

    FIXME:
     - pass password via agent? file descriptor?

    """
    def __init__(self, hostname, port = 22, crlf = '\r',
                 chunk_size = 0, interchunk_wait = 0.1,
                 extra_opts = None, command_sequence = None,
                 **kwargs):
        assert isinstance(hostname, str)
        assert port > 0
        assert extra_opts == None \
            or ( isinstance(extra_opts, dict) \
                 and all(isinstance(k, str) and isinstance(v, str)
                         for k, v in list(extra_opts.items()))), \
            "extra_opts: expected dict of string:string; got %s" \
            % type(extra_opts)

        generic_c.__init__(self,
                           chunk_size = chunk_size,
                           interchunk_wait = interchunk_wait,
                           command_sequence = command_sequence,
                           crlf = crlf, **kwargs)
        ttbl.power.socat_pc.__init__(
            self,
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            # Configuf file is generated during on().
            # -tt: (yeah, double) force TTY allocation even w/o
            # controlly TTY
            "EXEC:'sshpass -e ssh -v -F %(component)s-ssh-config -tt"
            # don't use ssh://USER@HOST:PORT, some versions do not grok it
            "  -p %(port)s %(username)s@%(hostname)s'"
            ",sighup,sigint,sigquit"
        )
        user, password, hostname = commonl.split_user_pwd_hostname(hostname)
        self.parameters_default = {
            'user': user,
        }
        self.parameters.update(self.parameters_default)
        # pass those fields to the socat_pc templating engine
        self.kws['hostname'] = hostname
        self.kws['username'] = user
        self.kws['port'] = port
        # this is used for sshpass to send the password; we dont' keep
        # the password in the default parameters because then it'd
        # leak easily to anyone
        self.password = password
        # SSHPASS always has to be defined
        self.env_add['SSHPASS'] = password if password else ""
        self.extra_opts = extra_opts
        self.paranoid_get_samples = 1

    def on(self, target, component):
        # generate configuration file from parameters
        with open(os.path.join(target.state_dir, component + "-ssh-config"),
                  "w+") as cf:
            _extra_opts = ""
            if self.extra_opts:
                for k, v in list(self.extra_opts.items()):
                    _extra_opts += "%s = %s\n" % (k, v)
            # CheckHostIP=no and StrictHostKeyChecking=no are needed
            # because we'll change IPs and reformat a lot, so we dont'
            # really care for the signature.
            # that's also why we just send the known hosts files to null
            cf.write("""\
UserKnownHostsFile = /dev/null
CheckHostIP = no
StrictHostKeyChecking = no
ServerAliveCountMax = 20
ServerAliveInterval = 10
TCPKeepAlive = yes
ForwardX11 = no
ForwardAgent = no
EscapeChar = none
%s""" % _extra_opts)
        ssh_user = target.fsdb.get(
            "interfaces.console." + component + ".parameter_user", None)
        ssh_port = target.fsdb.get(
            "interfaces.console." + component + ".parameter_port", None)
        ssh_password = target.fsdb.get(
            "interfaces.console." + component + ".parameter_password", None)
        # FIXME: validate port, username basic format
        if ssh_user:
            self.kws['username'] = ssh_user
        if ssh_port:
            self.kws['port'] = ssh_port
        if ssh_password:
            # if one was specified, use it
            self.env_add['SSHPASS'] = ssh_password
        ttbl.power.socat_pc.on(self, target, component)
        generation_set(target, component)
        generic_c.enable(self, target, component)

    def off(self, target, component):
        generic_c.disable(self, target, component)
        ttbl.power.socat_pc.off(self, target, component)

    # console interface
    def setup(self, target, component, parameters):
        # For SSH, all the paremeters are in FSDB
        if parameters == {}:		# reset
            # wipe existing parameters
            for param_key in target.fsdb.keys("interfaces.console."
                                              + component + ".parameter_*"):
                target.fsdb.set(param_key, None, True)
            for key, value in self.parameters_default.items():
                target.fsdb.set("interfaces.console."
                                + component + ".parameter_" + key, value, True)
            return {}

        # things we allow
        allowed_keys = [ 'user', 'password' ]
        for key in list(parameters.keys()):
            if key not in allowed_keys:
                raise RuntimeError("field '%s' cannot be set" % key)

        # some lame security checks
        for key, value in parameters.items():
            if '\n' in value:		# could be used to enter other fields
                raise RuntimeError(
                    "field '%s': value contains invalid newline" % key)

        # ok, all verify, let's set it
        for key, value in parameters.items():
            target.fsdb.set("interfaces.console."
                            + component + ".parameter_" + key, value, True)
        return {}

    def enable(self, target, component):
        self.on(target, component)

    def disable(self, target, component):
        return self.off(target, component)

    def state(self, target, component):
        # we want to use this to gather state, since the generic_c
        # implementation relies on the console-NAME.write file
        # existing; this can linger if a process dies or not...
        # but the ttbl.power.socat_pc.get() implementation checks if
        # the process is alive looking at the PIDFILE
        # COMPONENT-socat.pid and verifying that thing is still running
        return ttbl.power.socat_pc.get(self, target, component)


class netconsole_pc(ttbl.power.socat_pc, generic_c):
    """Receive Linux's netconsole data over a console

    The linux kernel can forward kernel messages over IP as soon as
    the network is initialized, which this driver can pick up and
    register. The target's kernel needs to be configured to output its
    netconsole to the server's IP, matching the port given to this
    driver; for example, the kernel command line::

      netconsole=@/,6666@192.168.98.1

    or as a module (see other methods `here
    <https://www.kernel.org/doc/Documentation/networking/netconsole.txt>`_)::

      # modprobe netconsole netconsole=@/,6666@192.168.98.1

    will send netconsole output to *UDP:192.168.98.1:666*

    The driver implements two interfaces:

    - power interface: to start a console record as soon as the target
      is powered on. Anything read from the console is written to file
      *console-NAME.read* file.

      The power interface is implemented by subclassing
      :class:`ttbl.power.socat_pc`, which starts *socat* as daemon to
      serve as a data recorder.

    - console interface: interacts with the console interface by
      exposing the data recorded in the file *console-NAME.read* file.
      Writing is not supported, since *netconsole* is read only.

    :params str ip_addr: (optional) IP address or hostname of the
      target.

    :params int port: (optional) port number to which to receive;
      defaults to *6666* (netconsole's default).

    For example, create a serial port recoder power control / console
    driver and insert it into the power rail and the console of a
    target:

    target.console.impl_add("netconsole0", netconsole_pc())
    >>> netconsole_pc = ttbl.console.netconsole_c("192.168.98.2")
    >>>
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "power",
    >>>     ttbl.power.interface(
    >>>         ...
    >>>         ( "netconsole", netconsole_pc, )
    >>>         ...
    >>>     )
    >>> ttbl.test_target.get(name).interface_add(
    >>>     "console",
    >>>     ttbl.console.interface(
    >>>         ...
    >>>         netconsole = netconsole_pc,
    >>>         ...
    >>>     )
    >>> )

    """
    def __init__(self, ip_addr, port = 6666):
        assert isinstance(port, numbers.Integer)
        generic_c.__init__(self)
        ttbl.power.socat_pc.__init__(
            self,
            # fork?
            "UDP-LISTEN:%d,range=%s" % (port, ip_addr),
            "CREATE:console-%(component)s.read",
            extra_cmdline = [ "-u" ])	# unidirectional, UDP:6666 -> file

    def on(self, target, component):
        ttbl.power.socat_pc.on(self, target, component)
        generation_set(target, component)
        generic_c.enable(self, target, component)

    def off(self, target, component):
        generic_c.disable(self, target, component)
        ttbl.power.socat_pc.off(self, target, component)

    # console interface)
    def write(self, target, component, data):
        raise RuntimeError("%s: (net)console is read only" % component)

    def enable(self, target, component):
        self.on(target, component)

    def disable(self, target, component):
        return self.off(target, component)

    def state(self, target, component):
        # we want to use this to gather state, since the generic_c
        # implementation relies on the console-NAME.write file
        # existing; this can linger if a process dies or not...
        # but the ttbl.power.socat_pc.get() implementation checks if
        # the process is alive looking at the PIDFILE
        # COMPONENT-socat.pid and verifying that thing is still running
        return ttbl.power.socat_pc.get(self, target, component)



class telnet_pc(ttbl.power.socat_pc, generic_c):
    """Implement a serial port over a telnet connection

    A telnet connection is open to the remote end, anything written to
    the console is sent there, anything read is received and recorded
    for the console interface to send to clients.

    This class implements two interfaces:

    - power interface: to start a telnet connection recorder in the
      background as soon as the target is powered on.

      The power interface is implemented by subclassing
      :class:`ttbl.power.socat_pc`, which starts *socat* as daemon to
      serve as a data recorder and to pass data to the connection
      from the read file.

      Anything read form the telnet connection is written to the
      *console-NAME.read* file and anything written to it is written
      to *console-NAME.write* file, which is sent to the remote
      machine.

    - console interface: interacts with the console interface by
      exposing the data recorded in *console-NAME.read* file and
      writing to the *console-NAME.write* file.

    :params str hostname: IP address or hostname of the
      target. A username can be specified with *username@hostname*;
      passwords are not yet supported.

    :params int port: (optional; default *23*) port number to connect
      to.

    Other parameters as to :class:`generic_c`.

    FIXME: passwords are still not supported
    """
    def __init__(self, hostname, port = 23, crlf = '\r',
                 socat_pc_kwargs = None,
                 **kwargs):
        assert isinstance(port, int)
        generic_c.__init__(self)
        username, password, _hostname = commonl.split_user_pwd_hostname(hostname)
        self.hostname = _hostname
        ttbl.power.socat_pc.__init__(
            self,
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            # -a: try automatic login, pullin the user from the USER
            #     env variable
            # -c: no ~/.telnetrc
            # -L -8: 8bit binary path on input and output, no translations
            # -E: no escape characters
            "EXEC:'telnet -a -c -L -8 -E %(hostname)s %(port)s'"
            ",sighup,sigint,sigquit",
            **socat_pc_kwargs
        )
        self.parameters_default = {
            'user': username,
        }
        self.parameters.update(self.parameters_default)
        # pass those fields to the socat_pc templating engine
        self.kws['hostname'] = _hostname
        self.kws['username'] = username
        self.kws['port'] = port
        self.paranoid_get_samples = 1
        self.upid_set(f"console over telnet to {username}@{_hostname}:{port}",
                      name = f"telnet:{username}@{_hostname}:{port}",
                      username = username,
                      hostname = _hostname,
                      port = port)

    def on(self, target, component):
        telnet_user = target.fsdb.get(
            "interfaces.console." + component + ".parameter_user", None)
        telnet_port = target.fsdb.get(
            "interfaces.console." + component + ".parameter_port", None)
        telnet_password = target.fsdb.get(
            "interfaces.console." + component + ".parameter_password", None)
        # FIXME: validate port, username basic format
        if telnet_user:
            self.kws['username'] = telnet_user
        if telnet_port:
            self.kws['port'] = telnet_port
        if telnet_password:
            # if one was specified, use it
            self.env_add['SSHPASS'] = telnet_password
        ttbl.power.socat_pc.on(self, target, component)
        generation_set(target, component)
        generic_c.enable(self, target, component)

    def off(self, target, component):
        generic_c.disable(self, target, component)
        ttbl.power.socat_pc.off(self, target, component)

    def enable(self, target, component):
        self.on(target, component)

    def disable(self, target, component):
        return self.off(target, component)

    def state(self, target, component):
        # we want to use this to gather state, since the generic_c
        # implementation relies on the console-NAME.write file
        # existing; this can linger if a process dies or not...
        # but the ttbl.power.socat_pc.get() implementation checks if
        # the process is alive looking at the PIDFILE
        # COMPONENT-socat.pid and verifying that thing is still running
        return ttbl.power.socat_pc.get(self, target, component)


class logfile_c(impl_c):
    """
    A console that streams a logfile in the server

    :params str logfile_name: Name of the log file to stream; if
      relative, this file must be present in the target's state
      directory. If absolute, it can be any file in the file system
      the daemon has access to.

      .. warning:: Make sure publishing the log file does not open
                   users to internals from the system's operation

    This console can be read from but not written; the driver makes a
    weak attempt at deciding if the file has been removed and
    recreated by looking at the size. See the discussion on
    generations in :class:ttbl.console.impl_c.

    This console will report it is disabled if the file is not
    present, enabled otherwise. Attempts to enable it at will be
    ignored; disabling it removes the logfile.

    >>> target.console.impl_add(
    >>>     "debugger_log",
    >>>     ttbl.console.logfile_c("debugger.log")
    >>> )

    """
    def __init__(self, logfile_name, **kwargs):
        assert isinstance(logfile_name, str)
        impl_c.__init__(self, **kwargs)
        self.logfile_name = logfile_name
        self.upid_set(f"console for logfile {logfile_name}",
                      name = logfile_name,
        )

    # console interface)
    def _size(self, target, component, file_name):
        # read the file; however, let's do a basic attempt at
        # detecting if it has been removed and created new  since the
        # last time we read it -- ideally we'd use the creation time,
        # but Linux keeps not.
        # If the file's size is smaller than the last file_size we
        # recorded, then we assume is a new file and thus set a new
        # generation.
        # This might work because most people reading it will be
        # reading in a loop so the likelyhood of changes detected
        # comes up.
        try:
            s = os.stat(file_name)
            last_size = target.fsdb.get(
                "interfaces.console." + component + ".last_size", 0)
            if s.st_size > 0 and s.st_size < last_size:
                generation_set(target, component)
                target.fsdb.set("interfaces.console." + component + ".last_size",
                                s.st_size)
            return s.st_size
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            return None		# API way for saying "disabled"

    def size(self, target, component):
        if not os.path.isabs(self.logfile_name):
            file_name = os.path.join(target.state_dir, self.logfile_name)
        else:
            file_name = self.logfile_name
        return self._size(target, component, file_name)

    def setup(self, target, component, parameters):
        # we use the setup call to wipe the log file
        if not os.path.isabs(self.logfile_name):
            file_name = os.path.join(target.state_dir, self.logfile_name)
        else:
            file_name = self.logfile_name
        try:
            os.unlink(file_name)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def read(self, target, component, offset):
        # read the file; however, let's do a basic attempt at
        # detecting if it has been removed and created new  since the
        # last time we read it -- ideally we'd use the creation time,
        # but Linux keeps not.
        # If the file's size is smaller than the last file_size we
        # recorded, then we assume is a new file and thus set a new
        # generation.
        # This might work because most people reading it will be
        # reading in a loop so the likelyhood of changes detected
        # comes up.
        if not os.path.isabs(self.logfile_name):
            file_name = os.path.join(target.state_dir, self.logfile_name)
        else:
            file_name = self.logfile_name
        size = self._size(target, component, file_name)
        if size == None:
            return dict(
                stream_file = "/dev/null",
                stream_generation = 0,
                stream_offset = 0
            )
        return dict(
            stream_file = file_name,
            stream_generation = target.fsdb.get(
                "interfaces.console." + component + ".generation", 0),
            stream_offset = offset
        )

    @staticmethod
    def write(_target, component, _data):
        raise RuntimeError("%s: logfile console is read only" % component)

    # we do not touch the logfile when we enable/disable, since these
    # paths are very common during normal execution and we don't want
    # that to (for example) remove the log file, since we would loose
    # access to its contents.
    def enable(self, _target, _component):
        pass

    def disable(self, target, _component):
        pass

    # power and console interface
    def state(self, target, component):
        if not os.path.isabs(self.logfile_name):
            file_name = os.path.join(target.state_dir, self.logfile_name)
        else:
            file_name = self.logfile_name
        return self._size(target, component, file_name) != None
