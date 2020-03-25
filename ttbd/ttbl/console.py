#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Access target's serial consoles / bidirectional channels
--------------------------------------------------------

Implemented by :class:`ttbl.console.interface`.
"""

import codecs
import contextlib
import errno
import fcntl
import os
import socket
import stat
import time

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
      serial* command:

      >>> serial0_pc = ttbl.console.ssh_pc(
      >>>     "USER:PASSWORD@LANTRONIXHOSTNAME",
      >>>     command_sequence = [
      >>>       ## Welcome to the Lantronix SLSLP^M$
      >>>       ## Firmware: version 030031, build 38120^M$
      >>>       ## Last login: Thu Jan  1 00:04:20 1970 from 10.24.11.35^M$
      >>>       ## Current time: Thu Jan  1 00:02:03 1970^M$
      >>>       ## For a list of commands, type 'help'^M$

      >>>       # command prompt, 'CR[USERNAME@IP]> '... or not, so just
      >>>       # look for 'SOMETHING> '
      >>>       # ^ will not match because we are getting a Carriage
      >>>       # Return / New Line
      >>>       (
      >>>           # send a disconnect just in case it is connected
      >>>           # and wait for the command prompt
      >>>           "\x1bexit\r\n",
      >>>           # command prompt, 'CR[USERNAME@IP]> '... or not, so just
      >>>           # look for 'SOMETHING> '
      >>>           # ^ will not match because we are getting a CR
      >>>           re.compile("[^>]+> ")
      >>>       ),
      >>>       (
      >>>           "connect serial\r\n",
      >>>           "To exit serial port connection, type 'ESC exit'."
      >>>       ),
      >>>     ],
      >>>     extra_opts = {
      >>>         # old, but that's what the Lantronix server has :/
      >>>         "KexAlgorithms": "diffie-hellman-group1-sha1",
      >>>         "Ciphers" : "aes128-cbc,3des-cbc",
      >>>     })

      This is a list of tupples *( SEND, EXPECT )*; *SEND* is a string
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
    """
    def __init__(self, command_sequence = None, command_timeout = 5):
        assert command_sequence == None \
            or isinstance(command_sequence, list), \
            "command_sequence: expected list of tuples; got %s" \
            % type(command_sequence)
        assert command_timeout > 0
        self.command_sequence = command_sequence
        self.command_timeout = command_timeout
        self.parameters = {}
        ttbl.tt_interface_impl_c.__init__(self)

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
        target.property_set("console-" + component + ".state", "enabled")

    def disable(self, target, component):
        """
        Disable a console

        :param str console: (optional) console to disable; if missing,
          the default one.
        """
        target.property_set("console-" + component + ".state", None)

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
        raise NotImplementedError("%s/%s: console control not implemented"
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
        if isinstance(expect.before, basestring):
            for line in expect.before.splitlines():
                target.log.error("%s: expect output[before]: %s"
                                 % (console, line.strip()))
        else:
            target.log.error("%s: expect output[before]: %s"
                             % (console, expect.before))
        if isinstance(expect.after, basestring):
            for line in expect.after.splitlines():
                target.log.error("%s: expect output[after]: %s"
                                 % (console, line.strip()))
        else:
            target.log.error("%s: expect output[after]: %s"
                             % (console, expect.after))

    def _response(self, target, console, expect, response, timeout,
                  response_str):
        ts0 = time.time()
        ts = ts0
        while ts - ts0 < timeout:
            try:
                r = expect.expect(response, timeout = timeout - (ts - ts0))
                ts = time.time()
                target.log.error("%s: found response: [+%.1fs] #%s: %s"
                                 % (console, ts - ts0, r, response_str))
                return
            except pexpect_TIMEOUT as e:
                self._log_expect_error(target, console, expect, "timeout")
                raise self.timeout_e(
                    "%s: timeout [+%.1fs] waiting for response: %s"
                    % (console, timeout, response_str))
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
                                               timeout = timeout)
            for command, response in self.command_sequence:
                if command:
                    target.log.debug(
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
                                   expect, response, timeout, response_str)
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

      - *serial\**  RS-232C compatible physical Serial port
      - *sol\**     IPMI Serial-Over-Lan
      - *ssh\**     SSH session (may require setup before enabling)

    A *default* console is set by declaring an alias as in the example
    above; however, a preferred console

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


    def _target_setup(self, target):
        # Called when the interface is added to a target to initialize
        # the needed target aspect (such as adding tags/metadata)
        target.tags_update(dict(consoles = self.impls.keys()))
        target.properties_user.add("console-default")
        target.properties_keep_on_release.add("console-default")
        self.instrumentation_publish(target, "console")

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

    def put_setup(self, target, who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        parameters = dict()
        for k, v in args.iteritems():
            parameters[k] = v
        if 'ticket' in parameters:
            del parameters['ticket']
        del parameters['component']
        assert all(isinstance(i, basestring) for i in parameters.values()), \
            'console.setup#parameters should be a dictionary keyed ' \
            'by string, values being strings'
        with target.target_owned_and_locked(who):
            target.timestamp()
            return impl.setup(target, component, parameters)

    def get_list(self, _target, _who, _args, _files, _user_path):
        return dict(
            aliases = self.aliases,
            result = self.aliases.keys() + self.impls.keys())

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

    def get_read(self, target, who, args, _files, _user_path):
        impl, component = self.arg_impl_get(args, "component")
        offset = int(args.get('offset', 0))
        if target.target_is_owned_and_locked(who):
            target.timestamp()	# only if the reader owns it
        r =  impl.read(target, component, offset)
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
            impl.write(target, component,
                       self._arg_get(args, 'data'))
            return {}    

def generation_set(target, console):
    target.fsdb.set("console-" + console + ".generation",
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
      >>>   '\x1b': '\x1b',
      >>>   '~': '\\',
      >>> }

      in this case, when the input string to send to the device
      contains a *\\x1b* (the ESC character), it will be prefixed with
      another one. If it contains a *~*, it will be prefixed with a
      backslash.

    """
    def __init__(self, chunk_size = 0, interchunk_wait = 0.2,
                 command_sequence = None, escape_chars = None):
        assert chunk_size >= 0
        assert interchunk_wait > 0
        assert escape_chars == None or isinstance(escape_chars, dict)

        self.chunk_size = chunk_size
        self.interchunk_wait = interchunk_wait
        impl_c.__init__(self, command_sequence = command_sequence)
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
                "console-%s.generation" % component, 0),
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
        for c in data:
            if c in self.escape_chars:
                _data += self.escape_chars[c] + c
            else:
                _data += c
        return _data


    
    def _write(self, fd, data):
        if self.escape_chars:
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
        if stat.S_ISSOCK(os.stat(file_name).st_mode):
            # consoles whose input is implemented as a socket
            with contextlib.closing(socket.socket(socket.AF_UNIX,
                                                  socket.SOCK_STREAM)) as f:
                f.connect(file_name)
                self._write(f.fileno(), data)
        else:
            while True:
                try:
                    with contextlib.closing(open(file_name, "a")) as f:
                        self._write(f.fileno(), data)
                        break
                except EnvironmentError as e:
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

      >>> serial0_pc = ttbl.console.ssh_pc(
      >>>     "USER:PASSWORD@HOSTNAME",
      >>>     extra_opts = {
      >>>         "Ciphers": "aes128-cbc,3des-cbc",
      >>>         "Compression": "no",
      >>>     })

      Be careful what is changed, since it can break operation.

    See :class:`generic_c` for descriptions on *chunk_size* and
    *interchunk_wait*, :class:`impl_c` for *command_sequence*.

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
    def __init__(self, hostname, port = 22,
                 chunk_size = 0, interchunk_wait = 0.1,
                 extra_opts = None, command_sequence = None):
        assert isinstance(hostname, basestring)
        assert port > 0
        assert extra_opts == None \
            or ( isinstance(extra_opts, dict) \
                 and all(isinstance(k, str) and isinstance(v, str)
                         for k, v in extra_opts.items())), \
            "extra_opts: expected dict of string:string; got %s" \
            % type(extra_opts)

        generic_c.__init__(self,
                           chunk_size = chunk_size,
                           interchunk_wait = interchunk_wait,
                           command_sequence = command_sequence)
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
                for k, v in self.extra_opts.items():
                    _extra_opts += "%s = %s\n" % (k, v)
            cf.write("""\
UserKnownHostsFile = %s/%s-ssh-known_hosts
StrictHostKeyChecking = no
ServerAliveCountMax = 20
ServerAliveInterval = 10
TCPKeepAlive = yes
ForwardX11 = no
ForwardAgent = no
EscapeChar = none
%s""" % (target.state_dir, component, _extra_opts))
        ttbl.power.socat_pc.on(self, target, component)
        generation_set(target, component)
        generic_c.enable(self, target, component)

    def off(self, target, component):
        generic_c.disable(self, target, component)
        ttbl.power.socat_pc.off(self, target, component)

    # console interface; state() is implemented by generic_c
    def setup(self, target, component, parameters):
        if parameters == {}:		# reset
            self.parameters = dict(self.parameters_default)
                # SSHPASS always has to be defined
            self.env_add['SSHPASS'] = self.password if self.password else ""
            self.kws['username'] = self.parameters['user']
            return dict(result = self.parameters)

        # things we allow
        allowed_keys = [ 'user', 'password' ]
        for key in parameters.keys():
            if key not in allowed_keys:
                raise RuntimeError("field '%s' cannot be set" % key)

        # some lame security checks
        for key, value in parameters.iteritems():
            if '\n' in value:		# could be used to enter other fields
                raise RuntimeError(
                    "field '%s': value contains invalid newline" % key)

        # ok, all verify, let's set it
        for key, value in parameters.iteritems():
            if key == 'user':
                self.kws['username'] = value
            elif key == 'password':
                # SSHPASS always has to be defined
                self.env_add['SSHPASS'] = value if value else ""
            else:
                self.parameters[key] = value
        return dict(result = self.parameters)

    def enable(self, target, component):
        self.on(target, component)

    def disable(self, target, component):
        return self.off(target, component)
