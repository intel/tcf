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
import logging
import numbers
import os
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
import tty


try:
    import setproctitle
except ImportError:
    logging.warning(
        "module `setproctitle` not available;"
        " doing without")
    class setproctitle:
        def setproctitle(s: str):
            pass


import commonl
import commonl.keys
import ttbl
import ttbl.config
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


    :param re.Pattern stderr_restart_regex: (optional; default
      *None*). While reading or writing, the
      :class:`ttbl.console.generic_c` code will check if the low level
      implementation of the console has died; if this is set to a
      regular expression, it will also check against the contents of the
      *.stderr* file that captures the output of a process that
      implements the console looking for errors and if found, restart the
      console driver.

      Basically used to fix badly broken things that fail frequently and
      there is nothing we an do about it (IPMI, looking at you); look at
      :class:`ttbl.ipmi.sol_console_pc` for an example.

    :param int rfc2217_tcp_port: (optional; default *None*) if given,
      an integer describing which TCP port to use to serve RFC2217
      serial port protocol.

      When the console is enabled, the port will be open and receive
      connections from any number of clients to interact with the
      console; depending on the implementation (eg: if it has a serial
      port as a backend), serial lines will be available or not.

      *Security considerations:* Note the argument *rfc2217_host*
       mandates to which network interfaces this binds to; there are no
       provisions for security in RFC2217, so anyone can connect.

       To properly secure this in a hostile environment, multiple
       options are available:

       - set *rfc2217_host* to `127.0.0.1` and use the tunneling
         facilities to creaate a tunnel associated to the target's
         allocation; this allows clients that know nothing about
         SSL. However, for it to be properly safe, it need to use
         tunnels that start inside the client.

       - FIXME: enable creating the socket with SSL wrapping using the
         cert interface; needs client that speak SSL.

    :param int rfc2217_host: (optional; default *0.0.0.0*) if given,
      interfaces were to bind.

    """
    def __init__(self, command_sequence = None, command_timeout = 5,
                 crlf = '\r', stderr_restart_regex: re.Pattern = None,
                 rfc2217_tcp_port: int = None,
                 rfc2217_host: str = "0.0.0.0"):
        assert command_sequence == None \
            or isinstance(command_sequence, list), \
            "command_sequence: expected list of tuples; got %s" \
            % type(command_sequence)
        assert command_timeout > 0
        assert stderr_restart_regex == None \
            or isinstance(stderr_restart_regex, re.Pattern), \
            "stderr_restart_regex: expected None or re.Pattern," \
            f" got {type(stderr_restart_regex)}"
        assert rfc2217_tcp_port == None \
            or (isinstance(rfc2217_tcp_port, int)
                and rfc2217_tcp_port > 1), \
            "rfc2217_tcp_port: expected None or > 1 integer;" \
            " got '{rfc2217_tcp_port}'"
        assert isinstance(rfc2217_host, str), \
            "rfc2217_host: expected str IP address; got '{rfc2217_host}'"

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
        self.stderr_restart_regex = stderr_restart_regex
        self.rfc2217_tcp_port = rfc2217_tcp_port
        self.rfc2217_host = rfc2217_host



    def target_setup(self, target, iface_name, component):
        # if it declares a CRLF string, publish it
        if self.crlf:
            assert isinstance(self.crlf, str), \
                f"{target.id}: target declares CRLF for console '{component}' with" \
                f" type '{type(self.crlf)}; expected string"
            target.fsdb.set("interfaces.console." + component + ".crlf",
                            self.crlf)
        else:
            target.fsdb.set("interfaces.console." + component + ".crlf", None)


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
        if self.rfc2217_tcp_port:
            # We have specified we want an RFC2217 server; these run
            # as a separate process listening for connections;
            #
            # kill any possible left overs, if any running before and
            # create a new object that represents the server and run
            # it; see the class info on why this is an standalone
            # object.

            # Do we have a real serial port? if a driver provides
            # access to a real serial port, it did resolve it and
            # place it in self.kws['device'], then pass it so we can
            # do modem line control
            serial_port = self.kws.get('device', None)

            ttbl.console.rfc2217_server_c.server_stop(target, component)
            rfc2217_server = ttbl.console.rfc2217_server_c(
                target, component, self,
                self.rfc2217_host, self.rfc2217_tcp_port,
                serial_port = serial_port,
            )
            # start the server; this forks a separate process1
            rfc2217_server.server_start()


    def disable(self, target, component):
        """
        Disable a console

        :param str console: (optional) console to disable; if missing,
          the default one.
        """
        target.property_set("interfaces.console." + component + ".state", False)
        if self.rfc2217_tcp_port:
            ttbl.console.rfc2217_server_c.server_stop(target, component)



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
        # FIXME: don't do this for log consoles?
        target.power_off_pre_fns.append(self._pre_off_disable_all)


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
        if impl.stderr_restart_regex != None:
            try:
                with open(f"{target.state_dir}/{component}-socat.stderr") as f:
                    data = f.read()
                    m = impl.stderr_restart_regex.search(data)
                    if m:
                        target.log.warning(
                            "%s: restarting since we found %s in %s",
                            component, impl.stderr_restart_regex.pattern,
                            f.name)
                        impl.disable(target, component)
                        impl.enable(target, component)
                        return True
            except FileNotFoundError:
                pass

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
        re_enable_if_dead = target.property_get(
            "interfaces.console." + component + ".re_enable_if_dead",
            impl.re_enable_if_dead)
        if not re_enable_if_dead:
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
                 escape_chars = None,
                 **kwargs):
        assert chunk_size >= 0
        assert interchunk_wait > 0
        assert escape_chars == None or isinstance(escape_chars, dict)
        self.chunk_size = chunk_size
        self.interchunk_wait = interchunk_wait
        impl_c.__init__(self, **kwargs)
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
            # the transport plane takes UTF-8 and accepts
            # surrogateencoding for bytes > 128 (U+DC80 - U+DCFF) see
            # Python's PEP383, so we can pipe binary over the "text"
            # based HTTP JSON interface.
            data = data.encode('utf-8', errors = 'surrogateescape')
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
                itr += _chunk_size
                left -= _chunk_size
                if left:
                    # only wait if we have data left -- ideally this
                    # shall wait if we have sent chunk_size B after
                    # the last wait we might -- but we need to store
                    # that in disk
                    time.sleep(self.interchunk_wait)

        else:
            os.write(fd, data)

    def write(self, target, component, data):
        file_name = os.path.join(target.state_dir,
                                 "console-%s.write" % component)
        if target.log.getEffectiveLevel() == logging.DEBUG:
            if isinstance(data, str):
                data_debug = data.encode('unicode-escape')
            elif isinstance(data, bytes):
                data_debug = data.decode('unicode-escape')
            else:
                data_debug = str(data).encode('unicode-escape')

                target.log.debug("%s: writing %dB to console (%s)",
                                 component, len(data), data_debug)
        try:
            stat_info = os.stat(file_name)
        except FileNotFoundError as e:
            raise RuntimeError(
                f"console '{component}' is disabled;"
                " enable it before writing") from e
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



class local_c(ttbl.power.socat_pc, generic_c):
    """
    Run a console to the local system

    Note when the process implementing the console dies, the console
    gets disabled and needs to be enabled again.

    :param str shell_command: (optional; default *bash --login*)
      command to get to a console/shell

      Examples:

      - to start a console in a given container image:

        >>> shell_command = "podman run -ti --network=none registry.fedoraproject.org/fedora:34 /bin/bash")

      - to start a console in a given python venv:

        >>> shell_command = "bash --init-file SOMEDIR/bin/activate -i"
        >>> shell_command = "venvdir=SOMEDIR; rm -rf $venvdir; cp -al ${venvdir}.orig $venvdir; bash --init-file $venvdir/bin/activate -i"

    Rest of arguments are the same as to :class:`ttbl.console.generic_c`
    """

    def __init__(self, *args,
                 shell_command: str = "bash --login",
                 **kwargs):
        generic_c.__init__(self, *args, **kwargs)
        ttbl.power.socat_pc.__init__(
            self,
            # note it is important to do the rawer first thing, then
            # do the settings; rawer resets to raw state
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            # pty: needed for bash to behave as if we were typing
            # cty: needed for job control
            f"SHELL:'{shell_command}',stderr,pty,ctty"
        )
        self.upid_set("local console")


    def target_setup(self, target, iface_name, component):
        generic_c.target_setup(self, target, iface_name, component)
        ttbl.power.socat_pc.target_setup(self, target, iface_name, component)


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



class serial_pc(ttbl.power.socat_pc, generic_c):
    """Implement a serial port console and data recorder

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

    :params str usb_serial_number: (optional) device specification
      (see :class:`ttbl.device_resolver_c`), eg a USB serial number

      >>> usb_serial_number = "3211123"

      a USB path:

      >>> usb_serial_number = "usb,idVendor=34d2,idProduct=131d,bInterfaceNumber=4"

      or more complex specifications are possible

    :params str serial_file_name: (optional) name of the serial port
      file, which can be templated with *%(FIELD)s* as per
      class:`ttbl.power.socat_pc` (the low level implementation).

      By default, it uses */dev/tty-TARGETNAME*, which makes it easier
      to configure. The tty name linked to the target can be set with
      :ref:`udev <usb_tty>`.

    :param int baudrate: (optional, default *115200*) baurdate to use
      to open the serial port

      FIXME: implement switching it in runtime

    :param int crtscts: (optional, default 0) port implements
      hardware flow control; valid is 0 or 1 per socat man page (DATA VALUES)

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
    def __init__(self, serial_file_name = None, usb_serial_number = None,
                 baudrate = 115200, crtscts: int = 0,
                 **kwargs):
        assert isinstance(baudrate, int) and baudrate > 0, \
            f"baudrate: expected int, got {baudrate}"
        generic_c.__init__(self, **kwargs)
        ttbl.power.socat_pc.__init__(
            self,
            # note it is important to do the rawer first thing, then
            # do the settings; rawer resets to raw state
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            "%(device)s,creat=0,rawer,b%(baudrate)d,crtscts=%(crtscts)d,parenb=0,cs8,bs1")
        # pass the device name like this so we can resolve LATE
        if usb_serial_number != None:
            assert serial_file_name == None, \
                "can't specify serial_file_name and usb_serial_number at the same time"
            self.upid_set("RS-232C over USB serial port @%s" % serial_file_name,
                          name = "RS-232CoUSB",
                          usb_serial_number = usb_serial_number,
                          baudrate = baudrate,
                          crtscts = crtscts,
            )
        else:
            # default to a file called /dev/tty-TARGETNAME (udev rules)
            if serial_file_name == None:
                serial_file_name = "/dev/tty-%(id)s"
            self.upid_set("RS-232C serial port @%s" % serial_file_name,
                          name = "RS-232C",
                          serial_port = serial_file_name,
                          baudrate = baudrate,
                          crtscts = crtscts,

            )
        self.usb_serial_number = usb_serial_number
        self.serial_file_name = serial_file_name
        self.baudrate = baudrate
        self.crtscts = crtscts



    def target_setup(self, target, iface_name, component):
        generic_c.target_setup(self, target, iface_name, component)
        ttbl.power.socat_pc.target_setup(self, target, iface_name, component)


    # console interface; state() is implemented by generic_c
    def on(self, target, component):
        if self.serial_file_name:
            self.kws['device'] = self.serial_file_name
        else:
            device_resolver = ttbl.device_resolver_c(
                target, self.usb_serial_number,
                f"instrumentation.{self.upid_index}.usb_serial_number")
            self.kws['device'] = device_resolver.tty_find_by_spec()
        # this publishes what final device we are using at the system
        # level, which helps in diagnosing and is also used by other
        # pieces of code
        target.property_set(
            f"instrumentation.{self.upid_index}.device_resolved",
            self.kws['device'])
        # sometimes there are lingering processes that get stuck and
        # don't release access to our device, so we just slash them
        # out and complain about it
        pids = commonl.kill_procs_using_device(
            self.kws['device'], signal.SIGKILL)
        if pids:
            target.log.warning(
                f"BUG? {component}/on: had to kill -9 pids using"
                f" {self.kws['device']}: {pids}")

        self.kws['baudrate'] = target.property_get(
            f"instrumentation.{self.upid_index}.baudrate",
            self.baudrate)
        # socat wants 0 or 1; that's it.
        self.kws['crtscts'] = target.property_get(
            f"instrumentation.{self.upid_index}.crtscts",
            self.crtscts)

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


class tcp_pc(ttbl.power.socat_pc, generic_c):
    """Implement a console via TCP connection

    Say, for example, you are exposing a serial port via TCP in a remote host
    using a software as hub4com or even socat. This class allow you to add that
    stream of data as a console to any target (ttbl.test_target). Making it
    easier to write and read from.

    You can connect any stream using TCP as long as you have the host and port

    >>> target.interface_impl_add(
    >>>    'console',
    >>>    'serial_over_tcp',
    >>>     ttbl.console.tcp_pc('remote.host.intel.com', 8080)
    >>> )

    In this example, `remote.host.intel.com` is exposing the serial console as
    a TCP connection on port 8080
    """

    def __init__(self, host: str, port: str, **kwargs):
        generic_c.__init__(self, **kwargs)
        ttbl.power.socat_pc.__init__(
            self,
            # note it is important to do the rawer first thing, then
            # do the settings; rawer resets to raw state
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            f"TCP:{host}:{port}")
        self.upid_set(
            f"TCP console to {host}:{port}", host = host, port = port)


    def target_setup(self, target, iface_name, component):
        generic_c.target_setup(self, target, iface_name, component)
        ttbl.power.socat_pc.target_setup(self, target, iface_name, component)


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


    def target_setup(self, target, iface_name, component):
        generic_c.target_setup(self, target, iface_name, component)
        ttbl.power.socat_pc.target_setup(self, target, iface_name, component)


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


    :param str shell_cmd: (optional; default empty, which lets sshd
      decide) shell to use.

      For windows, use "cmd /D" to force disabling no VT management.

    :param dict exta_opts: (optional) dictionary of extra SSH options
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

      If an option is called *k#something*: *v* it is intrpreted as
      *k*: *something v*. This allows specifying multiple entries that
      are using the same config key (like LocalCommand).

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
    def __init__(self, hostname, port = 22, extra_opts = None,
                 shell_cmd: str = '', **kwargs):
        assert isinstance(hostname, str)
        assert port > 0
        assert extra_opts == None \
            or ( isinstance(extra_opts, dict) \
                 and all(isinstance(k, str) and isinstance(v, str)
                         for k, v in list(extra_opts.items()))), \
            "extra_opts: expected dict of string:string; got %s" \
            % type(extra_opts)

        generic_c.__init__(self, **kwargs)
        ttbl.power.socat_pc.__init__(
            self,
            "PTY,link=console-%(component)s.write,rawer"
            "!!CREATE:console-%(component)s.read",
            # Configuf file is generated during on().
            # -tt: (yeah, double) force TTY allocation even w/o
            # controlly TTY
            "EXEC:'sshpass -e ssh -v -F %(component)s-ssh-config -tt"
            # don't use ssh://USER@HOST:PORT, some versions do not grok it
            f"  -p %(port)s %(username)s@%(hostname)s {shell_cmd}'"
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
        # leak easily to anyone--however, we'll use it as default if
        # not found in the keyring
        self.password = password
        # SSHPASS always has to be defined
        self.env_add['SSHPASS'] = password if password else ""
        self.extra_opts = extra_opts
        self.paranoid_get_samples = 1
        self.upid_set(f"console over SSH to {hostname}:{port}",
                      name = f"ssh:{hostname}:{port}",
                      hostname = hostname, port = port)
        # we use the kernel keyring to set things -- to avoid conflict
        # we do a separate instance; note separate instances (on
        # multiple daemons, etc) will still use the same session
        # keyring, so the description of the keys will contain context
        # info to avoid conflicts--note we do not use it via the
        # keyring library because we want to FORCE using keyctl and
        # not conflict with other keyring module users.
        self.keyring = commonl.keys.keyring_keyctl_c()


    def target_setup(self, target, iface_name, component):
        generic_c.target_setup(self, target, iface_name, component)
        ttbl.power.socat_pc.target_setup(self, target, iface_name, component)


    def on(self, target, component):
        # generate configuration file from parameters
        with open(os.path.join(target.state_dir, component + "-ssh-config"),
                  "w+") as cf:
            _extra_opts = ""
            if self.extra_opts:
                for k, v in list(self.extra_opts.items()):
                    # if an option is called k#something, change to k:
                    # something v; this allows specifying multiple
                    # entries that are using the same config key (like
                    # LocalCommand)
                    if '#' in k:
                        k, prefix = k.split("#", 1)
                        v = prefix + " " + v
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
        ssh_password = self.keyring.get_password(
            f"{ttbl.config.instance}.{target.id}",
            f"interfaces.console.{component}.parameter_password")
        if ssh_password == None:
            ssh_password = self.password
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
            self.keyring.delete_password(
                f"{ttbl.config.instance}.{target.id}",
                f"interfaces.console.{component}.parameter_password")
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
            if key == "password":	# passwords go to the keyring!
                self.keyring.set_password(
                    f"{ttbl.config.instance}.{target.id}",
                    f"interfaces.console.{component}.parameter_password",
                    value)
                continue
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

    >>> target.interface.impl_add("console", "netconsole0", netconsole_pc())

    or

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
    def __init__(self, ip_addr, port = 6666, **kwargs):
        assert isinstance(port, numbers.Integer)
        generic_c.__init__(self, **kwargs)
        ttbl.power.socat_pc.__init__(
            self,
            # fork?
            "UDP-LISTEN:%d,range=%s" % (port, ip_addr),
            "CREATE:console-%(component)s.read",
            extra_cmdline = [ "-u" ])	# unidirectional, UDP:6666 -> file


    def target_setup(self, target, iface_name, component):
        generic_c.target_setup(self, target, iface_name, component)
        ttbl.power.socat_pc.target_setup(self, target, iface_name, component)


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
    def __init__(self, hostname, port = 23,
                 socat_pc_kwargs = None,
                 **kwargs):
        assert isinstance(port, int)
        generic_c.__init__(self, **kwargs)
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
        # this is used for sshpass to send the password; we dont' keep
        # the password in the default parameters because then it'd
        # leak easily to anyone--however, we'll use it as default if
        # not found in the keyring
        self.password = password
        self.paranoid_get_samples = 1
        self.upid_set(f"console over telnet to {username}@{_hostname}:{port}",
                      name = f"telnet:{username}@{_hostname}:{port}",
                      username = username,
                      hostname = _hostname,
                      port = port)
        # we use the kernel keyring to set things -- to avoid conflict
        # we do a separate instance; note separate instances (on
        # multiple daemons, etc) will still use the same session
        # keyring, so the description of the keys will contain context
        # info to avoid conflicts--note we do not use it via the
        # keyring library because we want to FORCE using keyctl and
        # not conflict with other keyring module users.
        self.keyring = commonl.keys.keyring_keyctl_c()


    def target_setup(self, target, iface_name, component):
        generic_c.target_setup(self, target, iface_name, component)
        ttbl.power.socat_pc.target_setup(self, target, iface_name, component)


    def on(self, target, component):
        telnet_user = target.fsdb.get(
            "interfaces.console." + component + ".parameter_user", None)
        telnet_port = target.fsdb.get(
            "interfaces.console." + component + ".parameter_port", None)
        telnet_password = self.keyring.get_password(
            f"{ttbl.config.instance}.{target.id}",
            f"interfaces.console.{component}.parameter_password")
        if telnet_password == None:
            telnet_password = self.password
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


    # console interface
    def setup(self, target, component, parameters):
        if parameters == {}:		# reset
            # wipe existing parameters
            for param_key in target.fsdb.keys("interfaces.console."
                                              + component + ".parameter_*"):
                target.fsdb.set(param_key, None, True)
            for key, value in self.parameters_default.items():
                target.fsdb.set("interfaces.console."
                                + component + ".parameter_" + key, value, True)
            self.keyring.delete_password(
                f"{ttbl.config.instance}.{target.id}",
                f"interfaces.console.{component}.parameter_password")
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
            if key == "password":
                # passwords go to the keyring!
                if key == 'password':
                    self.keyring.set_password(
                        f"{ttbl.config.instance}.{target.id}",
                        f"interfaces.console.{component}.parameter_password",
                        value)
                continue
            target.fsdb.set("interfaces.console."
                            + component + ".parameter_" + key, value, True)
        return {}


    def state(self, target, component):
        # we want to use this to gather state, since the generic_c
        # implementation relies on the console-NAME.write file
        # existing; this can linger if a process dies or not...
        # but the ttbl.power.socat_pc.get() implementation checks if
        # the process is alive looking at the PIDFILE
        # COMPONENT-socat.pid and verifying that thing is still running
        return ttbl.power.socat_pc.get(self, target, component)



class tcp_raw_pc(ttbl.power.socat_pc, generic_c):
    """
    Raw TCP console to interact with a TCP port

    :param str hostname: name or IP of the host to connect to
    :param int port: TCP port number to connect to

    :param dict socat_pc_kwargs: (optional, default none) more
      arguments for the :class:`ttbl.power.socat_pc`

    Other arguments as to :class:`ttbl.console.generic_c`
    """
    def __init__(self, hostname: str, port: int,
                 socat_pc_kwargs = None,
                 **kwargs):
        assert isinstance(port, int)
        if socat_pc_kwargs != None:
            assert isinstance(socat_pc_kwargs, dict)
        else:
            socat_pc_kwargs = {}
        generic_c.__init__(self, **kwargs)
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
            "TCP:%(hostname)s:%(port)s",
            **socat_pc_kwargs
        )
        self.upid_set(f"console over raw TCP to {hostname}:{port}",
                      name = f"TCP:{hostname}:{port}",
                      hostname = hostname,
                      port = port)


    def target_setup(self, target, iface_name, component):
        generic_c.target_setup(self, target, iface_name, component)
        ttbl.power.socat_pc.target_setup(self, target, iface_name, component)


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

    >>> target.interface_impl_add(
    >>>     "console",
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



class command_output_c(impl_c):
    """A console that streams the output of a process run in the server

    This is useful to report diagnostics that run on the server.

    :param str|list[str] cmdline: Command to execute

      Can be a string or list of strings; *%(FIELD)[sd]* are expanded
      from the target's inventory.

    :param bool run_on_enable: (optional; default *False*) run the
      command only when we enable the console, then disable it.

      By default, everytime we read we run the command; when this is
      enabled, we run the command then we always read the same data
      and report disabled, until we enable again.

    .. warning:: Make sure publishing the output does not open
                 users to internals from the system's operation

    This console can be read from but not written. The command is
    executed every time the console is read, so if called too
    often and is heavy on load, it will generate system load.

    This console can't be enabled/disabled and reports always enabled.

    >>> target.interface_impl_add(
    >>>     "console",
    >>>     "ls_log",
    >>>     ttbl.console.command_output_c("ls -l")
    >>> )

    """
    def __init__(self, cmdline: list,
                 run_on_enable: bool = False, **kwargs):
        assert isinstance(run_on_enable, bool), \
            f"run_on_enable: expected bool, got {type(run_on_enable)}"
        impl_c.__init__(self, **kwargs)
        if isinstance(cmdline, str):
            self.cmdline = cmdline.split()
        else:
            commonl.assert_list_of_strings(cmdline, "cmdline", "args")
            self.cmdline = cmdline
            cmdline = " ".join(cmdline)
        self.run_on_enable = run_on_enable
        self.upid_set(
            f"console for seeing output of command {cmdline}",
            cmdline = cmdline,
            run_on_enable = run_on_enable,
        )

    # console interface

    def setup(self, target, component, parameters):
        return


    def _stat(self, target, component):
        try:
            file_name = os.path.join(
                target.state_dir, f"console-{component}.read")
            stat_info = os.stat(file_name)
            return stat_info.st_size, int(stat_info.st_mtime)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            # not even existing, so empty
            return 0, 0

    def size(self, target, component):
        return self._stat(target, component)[0]



    def _read(self, target, component):
        kws = target.kws_collect(self)
        kws['component'] = component
        cmdline = []
        for i in self.cmdline:
            cmdline.append(commonl.kws_expand(i, kws))
        outfile = os.path.join(target.state_dir, f"console-{component}.read")
        with open(outfile, "w") as of:
            target.log.info("running command for console %s: %s",
                            component, cmdline)
            p = subprocess.run(
                cmdline,
                shell = False,
                timeout = 20,
                check = False,
                text = True,
                stdout = of,
                stderr = subprocess.STDOUT)
            target.log.warning("ran command for console %s (%s): %s",
                               component, cmdline, p)
            stat_info = os.fstat(of.fileno())
            return stat_info.st_size, int(stat_info.st_mtime)



    def read(self, target, component, offset):
        if self.run_on_enable:	# only run during enable, so get generation
            size, stream_generation = self._stat(target, component)
        else:			# run and get generation
            size, stream_generation = self._read(target, component)
        return dict(
            stream_file = os.path.join(
                target.state_dir, f"console-{component}.read"),
            stream_generation = stream_generation,
            stream_offset = offset,
        )



    def write(self, _target, component, _data):
        raise RuntimeError(f"{component}: console is read only")



    # we do nothing when we enable/disable
    def enable(self, target, component):
        if self.run_on_enable:
            self._read(target, component)



    def disable(self, target, _component):
        pass



    # power and console interface
    def state(self, target, component):
        # this is always "disabled"; when if self.run_on_enable() is
        # set, when you try to enable it it runs, otherwise when you read.
        return False


import serial
import serial.rfc2217
import socket
import threading

class rfc2217_server_c:
    """An RFC2217 server over the TTBD console drivers

    ***WARNING*** This class is pretty much very internal, used only
    by the :class:`ttbl.console.impl_c` code and there is not much
    need for others to use it.

    Each console driver based on :class:`ttbl.console.impl_c' can
    easily implement an RFC2217 server.

    Since there is always a backing file that contains the *recorded*
    output from the console, we can easily monitor that and send it to
    the other side. As well, anything we receive from the other side
    can be passed to the console implementation using
    :method:`ttbl.console.impl_c.write`.

    Serial port signals are passed around if the backing behind the
    console driver is a serial port; otherwise they are ignored.

    :param ttbl.test_target target: target which implements this
      console

    :param str component: name of the component in the console
      interface

    :param ttbl.console.impl_c: console object (this is usually
      *target.console.impls[component]*)

    :param str bind_host: host to bind to; IPv4 or IPv6 address of the
      interface to bind.

      - *0.0.0.0*: all interfaces
      - *127.0.0.1*: localhost interfce only

    :param int tcp_port: TCP port to which to bind to

    :param str serial_port: (optional, default *None*) what physical
      serial port to use; if *None*, no serial line control will be
      done.

      The :class:`ttbl.console.serial_pc` driver sets the serial port
      it resolves to in the inventory and
      :method:`ttbl.console.impl_c.enable` picks it up, if present to
      pass it here.

    ***Design constraints***

    - this has to be a separate class (vs part of
      :class:`ttbl.console.impl_c` because
      :class:`serial.rfc2217.PortManager` requires an object with a
      :methd:`write` to write the data; :class:`ttbl.console.impl_c`
      already has that with a different signature.

    - the life cycle: create+start when the console is enabled, spawns
      process; kills the process when disabled

    - remember this is a multiprocess server, so anything this spawns
      can't keep state in the python code; the start method just
      spawns the process and records the PID in the inventory for it to
      be killed later.

    - the spawned process listens and spawns another process per
      connection; the spawned per-connection processes handles both input
      and output in a very simplistic way.

    """
    def __init__(self,
                 target: ttbl.test_target,
                 component: str,
                 console: impl_c,
                 bind_host: str, tcp_port: int,
                 serial_port: str = None):

        assert isinstance(target, ttbl.test_target)
        assert isinstance(component, str)
        assert isinstance(console, ttbl.console.impl_c)
        assert isinstance(bind_host, str )
        assert isinstance(tcp_port, int ) and tcp_port > 1
        assert serial_port == None or isinstance(serial_port, str )

        self.target = target
        self.component = component
        self.console = console
        self.serial_port = serial_port
        self.bind_host = bind_host
        self.tcp_port = tcp_port



    def _serve_one_client(self, client_socket, remote_addr, remote_port):
        # FIXME: rename process to rfc2217 server etc etc
        self.client_socket = client_socket

        idle_wait_max = 0.25
        idle_wait_min = 0.01
        idle_wait = idle_wait_min

        if self.serial_port:
            setproctitle.setproctitle(
                f"rfc2217:{self.target.id}:{self.component}:{self.tcp_port}"
                f" [{self.serial_port}]"
                f" {remote_addr}:{remote_port}"
            )
        else:
            setproctitle.setproctitle(
                f"rfc2217:{self.target.id}:{self.component}:{self.tcp_port}"
                f" {remote_addr}:{remote_port}")

        if self.serial_port:
            serial_desc = serial.serial_for_url(
                self.serial_port, baudrate = self.console.baudrate)

            self.rfc2217_manager = serial.rfc2217.PortManager(
                serial_desc, self,
                logger = self.target.log)
            self.target.log.error(
                'rfc2217:%s:%s[%s]: serving connection for %s',
                remote_addr, remote_port,  self.component, self.serial_port)
        else:
            self.rfc2217_manager = serial.rfc2217.PortManager(
                "nonexistant serial port", self,
                logger = self.target.log)
            self.target.log.error(
                'rfc2217:%s:%s[%s]: serving connection (no serial port)',
                remote_addr, remote_port,  self.component)

        client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        fcntl.fcntl(client_socket, fcntl.F_SETFL, os.O_NONBLOCK)
        offset = self.console.size(self.target, self.component)
        _offset = None
        generation0 = None
        while True:
            # single thread approach
            if self.serial_port:
                self.target.log.debug(
                    'rfc2217:%s:%s[%s]: checking %s modem lines',
                    remote_addr, remote_port,  self.component, self.serial_port)
                self.rfc2217_manager.check_modem_lines()

            # is there anything coming from the serial console?
            r = self.console.read(self.target, self.component, None)
            file_name = r.get('stream_file', None)
            generation = r.get('generation', None)
            if generation != generation0:
                offset = 0
                generation0 = generation
            data_read_from_console = 0
            data_read_from_remote = 0
            with open(file_name, "br" ) as f:
                f.seek(offset)
                # we read a max of 1K
                data_from_console = f.read(4096)
                data_read_from_console = len(data_from_console)
                if data_read_from_console:
                    self.target.log.debug(
                        'rfc2217:%s:%s[%s]: read %dB from console',
                        remote_addr, remote_port,  self.component, data_read_from_console)
                offset += data_read_from_console
                if data_from_console:
                    data = b''.join(self.rfc2217_manager.escape(data_from_console))
                    try:
                        client_socket.sendall(data)
                        self.target.log.debug(
                            'rfc2217:%s:%s[%s]: wrote %dB from console to remote',
                            remote_addr, remote_port,  self.component, len(data))
                    except ConnectionResetError as e:
                        # did this socket disconnect, stop this thread
                        self.target.log.error(
                            'rfc2217:%s:%s[%s]: remote disconnected while sending; stopping',
                            remote_addr, remote_port,  self.component)
                        return

            # is there anything in the network connection to
            # send to the console?
            data_from_remote = None
            try:
                # we read a max of 4k, and it is non-blocking so we
                # don't get stuck if there is nothing
                data_from_remote = client_socket.recv(4096)
                #if data_read_from_remote:
                self.target.log.debug(
                    'rfc2217:%s:%s[%s]: read %dB from remote',
                    remote_addr, remote_port, self.component, len(data_from_remote))

                data = b''.join(self.rfc2217_manager.filter(data_from_remote))
                if data:
                    if len(data) < 20:
                        data_debug = str(data).encode('unicode-escape')
                    else:
                        data_debug = "n/a"
                    self.console.write(self.target, self.component, data)
                    self.target.log.debug(
                        'rfc2217:%s:%s[%s]: wrote %dB from remote to console: %s',
                        remote_addr, remote_port,  self.component, len(data), data_debug)
            except ConnectionResetError as e:
                # did this socket disconnect, stop this thread
                self.target.log.error(
                    'rfc2217:%s:%s[%s]: remote disconnected while receiving; stopping',
                    remote_addr, remote_port,  self.component)
                return
            except socket.error as e:
                self.target.log.debug(
                    'rfc2217:%s:%s[%s]: read from remote: %s',
                    remote_addr, remote_port, self.component, e,
                    exc_info = True)
                # we leep going until they kill us or disconnect

            except Exception as e:
                self.target.log.debug(
                    'rfc2217:%s:%s[%s]: read from remote: %s',
                    remote_addr, remote_port, self.component, e,
                    exc_info = True)
                # we keep going until they kill us or disconnect

            # No data avaialble, so wait -- do adaptative wait,
            # increase the wait to a max but reset to the min if we
            # got some data
            if data_read_from_console == 0 and not data_from_remote:
                idle_wait += idle_wait
                if idle_wait > idle_wait_max:
                    idle_wait = idle_wait_max
                # simplistic as it gets
                time.sleep(idle_wait)
            else:
                idle_wait = idle_wait_min



    def serve_one_client(self, client_socket, remote_addr, remote_port):
        try:
            self._serve_one_client(client_socket, remote_addr, remote_port)
        except Exception as e:
            self.target.log.error(
                'rfc2217:%s:%s[%s]: BUG? server loop died: %s',
                remote_addr, remote_port, self.component, e,
                exc_info = True)



    def write(self, data):
        #
        # Write all the data to the socket
        #
        # Required by rfc227_manager so it can use it to write--this
        # method is the sole reason why this is a separate class
        self.client_socket.sendall(data)


    def _serve(self):
        #
        # Serve the main connection, listening for clients and
        # spawning threads to handle them
        #
        try:
            if self.serial_port:
                setproctitle.setproctitle(
                    f"rfc2217:{self.target.id}:{self.component}:{self.tcp_port}"
                    f" [{self.serial_port}]")
            else:
                setproctitle.setproctitle(
                    f"rfc2217:{self.target.id}:{self.component}:{self.tcp_port}")
            # Record who this is process is in the inventory, so we
            # can kill it
            self.target.property_set(
                f"interfaces.console.{self.component}.rfc227_pid",
                os.getpid())
            self.target.property_set(
                f"interfaces.console.{self.component}.rfc227_tcp_port",
                self.tcp_port)

            # Bind the socket, listen and loop waiting for connections
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(( self.bind_host, self.tcp_port ))
            server_socket.listen(1)

            while True:
                try:
                    self.target.log.error(
                        f"rfc2217[%s]: waiting for connections",
                        self.tcp_port)
                    client_socket, addr = server_socket.accept()
                    self.target.log.error(
                        f"rfc2217[%s]: got connection from %s:%s, spawning",
                        self.tcp_port, addr[0], addr[1])
                    # fork vs thread, so we see it as a separate
                    # process and have better scalability
                    r = commonl.fork_c(self._serve_one_client, client_socket, addr[0], addr[1])
                    r.start()
                except socket.error as e:
                    self.target.log.error(
                        f'rfc2217: accept error {remote_addr}:{remote_port}: {e}')
        except Exception as e:
            self.target.log.error(
                f"rfc2217: {self.tcp_port=} _serve exception: {e.args[0]}",
                exc_info = True)



    def server_start(self):
        server_pid = self.target.property_set(
            f"interfaces.console.{self.component}.rfc227_pid", None)
        r = commonl.fork_c(self._serve)
        r.start()

        # test the process started
        ts0 = ts = time.time()
        while ts - ts0 < 5:
            server_pid = self.target.property_get(
                f"interfaces.console.{self.component}.rfc227_pid")
            if server_pid:
                ttbl.daemon_pid_add(server_pid)
                return
            time.sleep(1)
            ts = time.time()
            continue
        raise RuntimeError("BUG server didn't start?")


    @staticmethod
    def server_stop(target, component):
        server_pid = target.property_get(
            f"interfaces.console.{component}.rfc227_pid")
        if not server_pid:
            return
        try:
            os.kill(server_pid, signal.SIGTERM)
            time.sleep(0.2)
            os.kill(server_pid, signal.SIGKILL)
        except:
            pass

        target.property_set(f"interfaces.console.{component}.rfc227_pid", None)
        try:
            ttbl.daemon_pid_rm(server_pid)
        except KeyError as e:
            pass
