#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Interface to provide flash the target using fastboot
----------------------------------------------------
"""

import json
import re
import subprocess

import ttbl

class interface(ttbl.tt_interface):
    """Interface to execute fastboot commands on target

    An instance of this gets added as an object to the main target
    with something like:

    >>> ttbl.config.targets['targetname'].interface_add(
    >>>     "fastboot",
    >>>     ttbl.fastboot.interface("R1J56L1006ba8b"),
    >>>     {
    >>>             # Allow a command called `flash_pos`; the command
    >>>             #
    >>>             # flash_pos partition_boot /home/ttbd/partition_boot.pos.img
    >>>             #
    >>>             # will be replaced with:
    >>>             #
    >>>             # flash partition_boot /home/ttbd/partition_boot.pos.img
    >>>             #
    >>>             # anything else will be rejected
    >>>             "flash_pos": [
    >>>                 ( "flash_pos", "flash" ),
    >>>                 "partition_boot",
    >>>                 "/home/ttbd/partition_boot.pos.img"
    >>>             ],
    >>>             # Allow a command called `flash`; the command
    >>>             #
    >>>             # flash partition_boot FILENAME
    >>>             #
    >>>             # will be replaced with:
    >>>             #
    >>>             # flash partition_boot /var/lib/ttbd-INSTANCE/USERNAME/FILENAME
    >>>             #
    >>>             # anything else will be rejected
    >>>             "flash": [
    >>>                 "flash",
    >>>                 "partition_boot",
    >>>                 ( re.compile("^(.+)$"), "%USERPATH%/\\g<1>" )
    >>>             ],
    >>>         }
    >>> )

    this allows to control which commands can be executed in the sever
    using fastboot, allowing access to the server's user storage area
    (to which files can be uploaded using the *tcf broker-upload*
    command or :func:`tcfl.tc.target_c.broker_files.upload
    <tcfl.target_ext_broker_files.broker_files.upload>`).

    The server configuration will decide which commands can be
    executed or not (a quick list can be obtained with *tcf
    fastboot-list TARGETNAME*).

    :param str usb_serial_number: serial number of the USB device
      under which the target exposes the fastboot interface. E.g.:
      ``"R1J56L1006ba8b"``.

    :param dict allowed_commands: Commands that can be executed with
      fastboot. This is a KEY/VALUE list. Each KEY is a command name
      (which doesn't necessarily need to map a fastboot command
      itself). The *VALUE* is a list of arguments to fastboot.

      The user must send the same amount of arguments as in the
      *VALUE* list.

      Each entry in the *VALUE* list is either a string or a regular
      expression. What ever the user sends must match the string or
      regular expression. Otherwise it will be rejected.

      The entry can be a tuple *( STR|REGEX, REPLACEMENT )* that
      allows to replace what the user sends (using
      :func:`re.sub`). In the example above:

      >>> ( re.compile("^(.+)$"), "%USERPATH%/\\g<1>" )

      it is meant to take a filename uploaded to the server's user
      storage area. A match is done on the totality of the argument
      (ala: file name) and then ``\\g<1>`` in the substitution string
      is replaced by that match (group #1), to yield
      ``%USERPATH%/FILENAME``.

      Furthermore, the following substitutions are done on the final
      strings before passing the arguments to fastboot:

        - ``%USERPATH%`` will get replaced by the current user path

      .. warning:: There is a potential to exploit the system's
                   security if wide access is given to touch files or
                   execute commands without filtering what the user is
                   given. Be very restrictive about what commands and
                   arguments are whitelisted.

    """
    def __init__(self, usb_serial_number, allowed_commands):
        assert isinstance(usb_serial_number, basestring), \
            "usb_serial_number must be a string, found %s" \
            % type(usb_serial_number).__name__
        assert isinstance(allowed_commands, dict), \
            "allowed_commands must be a dictionary keyed by " \
            "allowed command name, got %s" \
            % type(allowed_commands).__name__
        count = 0
        for key, data in allowed_commands.iteritems():
            assert isinstance(key, basestring), \
                "allowed_commands: item #%d: keys must be strings, found %s" \
                % (count, type(key).__name__)
            assert isinstance(data, list), \
                "allowed_commands: item #%d: values must be lists, found %s" \
                % (count, type(data).__name__)
            count2 = 0
            for item in data:
                if isinstance(item, tuple):
                    if len(item) != 2:
                        raise ValueError(
                            "Bad type given (%s); tuple of (STR|REGEX, STR) "
                            "expected for allowed argument"
                            % type(item).__name__)
                    assert isinstance(item[0],
                                      ( basestring, re._pattern_type )), \
                        "allowed_commands: item #%d/%d[0]: first value must " \
                        "be a string or compiled regex, found a %s" \
                        % (count, count2, type(item).__name__)
                    assert isinstance(item[1], basestring), \
                        "allowed_commands: item #%d/%d[1]: second value " \
                        "must be a string, found a %s" \
                        % (count, count2, type(item).__name__)
                else:
                    assert isinstance(item,
                                      ( basestring, re._pattern_type )), \
                        "allowed_commands: item #%d/%d: values in list must " \
                        "be strings or compiled regexs, found a %s" \
                        % (count, count2, type(item).__name__)
                count2 += 1
            count += 1

        ttbl.tt_interface.__init__(self)
        self.allowed_commands = allowed_commands
        self.usb_serial_number = usb_serial_number


    def _target_setup(self, _):
        pass

    def _release_hook(self, target, _force):
        # nothing needed here
        pass

    #: path to the fastboot binary
    #:
    #: can be changed globally:
    #:
    #: >>> ttbl.fastboot.interface.path = "/some/other/fastboot"
    #:
    #: or for an specific instance
    #:
    #: >>> ttbl.config.targets['TARGETNAME'].fastboot.path = "/some/other/fastboot"
    #:
    path = "/usr/bin/fastboot"

    @staticmethod
    def _regex_make(arg):
        if isinstance(arg, basestring):
            return re.compile(re.escape(arg))
        elif isinstance(arg, re._pattern_type):
            return arg
        raise ValueError("Bad type given (%s); str or re.compile() expected"
                         % type(arg).__name__)

    def _allowed(self, target, given_arg, allowed_arg, user_path):
        # allowed_arg can be
        #
        # - str
        # - compiled regex
        # - (str | regex, replacement) -> fed to re.sub()
        #
        # when using (str | regex, replacement), the given_arg is fed
        # to re.sub()
        if isinstance(allowed_arg, tuple):
            if len(allowed_arg) != 2:
                raise ValueError(
                    "Bad type given (%s); tuple of (STR|REGEX, STR) "
                    "expected for allowed argument"
                    % type(allowed_arg).__name__)
            allowed_regex = self._regex_make(allowed_arg[0])
            replacement_with = allowed_arg[1]
            match = allowed_regex.search(given_arg)
            target.log.warning("filtered arg %s with %s: %s",
                               given_arg, allowed_regex.pattern, match)
            if not match:
                return None
            # expand some values to replace
            for key, value in [
                    ("%USERPATH%", user_path)
            ]:
                replacement_with = replacement_with.replace(key, value)
            return re.sub(allowed_regex, replacement_with, given_arg)
        else:
            allowed_regex = self._regex_make(allowed_arg)
            match = allowed_regex.search(given_arg)
            if not match:
                return None
            return given_arg

    # called by the daemon when a METHOD request comes to the HTTP path
    # /ttb-vVERSION/targets/TARGET/interface/console/CALL

    def put_run(self, target, who, args, user_path):
        """
        Run a fastboot command

        Note we don't allow any command execution, only what is
        allowed by :data:`allowed_commands`, which might also filter
        the arguments based on the configuration.
        """
        if not 'parameters' in args:
            raise RuntimeError("missing argument: parameters")

        # FIXME: :100 is a hard limit on args, configurable?
        all_args = json.loads(args['parameters'])[:100]
        translated_args = []
        command = all_args[0]
        if command not in self.allowed_commands:
            raise RuntimeError("fastboot %s: disallowed by configuration"
                               % command)

        # The command is allowed, so now filter it if the config says so
        allowed_args = self.allowed_commands[command]
        count = 0
        target.log.warning("filtering args %s with %s",
                           all_args, allowed_args)
        for given_arg in all_args:
            if count >= len(allowed_args):
                raise RuntimeError(
                    "fastboot %s: argument #%d disallowed by "
                    "configuration (not enough count)" % (command, count))
            translated_arg = self._allowed(target, given_arg,
                                           allowed_args[count], user_path)
            if translated_arg == None:
                raise RuntimeError(
                    "fastboot %s: argument #%d disallowed by "
                    "configuration (no match)" % (command, count))
            translated_args.append(translated_arg)
            count += 1

        # we have a filtered command ready to run
        cmdline = [ self.path, "-s", self.usb_serial_number ] \
            + translated_args
        with target.target_owned_and_locked(who):
            try:
                target.log.info("fastboot running: %s" % " ".join(cmdline))
                output = subprocess.check_output(
                    cmdline, stderr = subprocess.STDOUT,
                    shell = False, cwd = target.state_dir)
                target.log.info("fastboot ran: %s" % " ".join(cmdline))
                for line in output.split('\n'):
                    target.log.debug("output: " + line)
                return {}
            except subprocess.CalledProcessError as e:
                msg = "fastboot error %d: %s" % (e.returncode,
                                                 " ".join(cmdline))
                target.log.error(msg)
                for line in e.output.split('\n'):
                    msg += "\n" + "error output: " + line
                    target.log.warning("error output: " + line)
                    raise RuntimeError(msg)


    def get_list(self, _target, _who, _args, _user_path):
        data = dict()
        for command, param_list in self.allowed_commands.iteritems():
            _param_list = []
            count = 0
            for param in param_list:
                if isinstance(param, tuple):
                    value = param[0]
                    if isinstance(value, basestring):
                        _param_list.append(value)
                    elif isinstance(value, re._pattern_type):
                        _param_list.append(value.pattern)
                    else:
                        assert(
                            "BUG: bad type %s in item #%d, expected "
                            "str or re._pattern_type"
                            % (type(value).__name__, count))
                else:
                    _param_list.append(param)
                count += 1
            params = " ".join(_param_list)
            data[command] = params
        return { 'commands': data }

