#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import binascii
import re
import tc
from . import msgid_c


class shell(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` for targets that support
    some kind of shell (Linux, Windows) to run some common remote
    commands without needing to worry about the details.

    The target has to be set to boot into console prompt, so password
    login has to be disabled.

    >>> target.shell.up()

    Waits for the shell to be up and ready; sets it up so that if an
    error happens, it will print an error message and raise a block
    exception. Note you can change what is expected as a :ref:`shell
    prompt <linux_shell_prompt_regex>`.

    >>> target.shell.run("some command")

    Remove remote files (if the target supports it) with:

    >>> target.shell.file_remove("/tmp/filename")

    Copy files to the target with:

    >>> target.shell.file_copy_to("local_file", "/tmp/remote_file")
    """

    def __init__(self, target):
        for bsp in target.rt.get('bsps', []):
            keys = target.rt['bsps'][bsp]
            if 'linux' in keys:
                break
        else:
            raise self.unneeded
        tc.target_extension_c.__init__(self, target)

    #: What do we look for into a shel prompt
    #:
    #: This is a Python regex that can be set to recognize what the
    #: shell prompt looks like. Multiple catchas here:
    #:
    #:  - use a fixed string or compile the regex
    #:
    #:  - if using ^ and/or $, even with re.MULTILINE, things tend not
    #:    to work so well because of \r\n line conventions vs \n
    #:
    #: Examples:
    #:
    #: >>> target.shell.linux_shell_prompt_regex = re.compile(r'root@.*# ')

    linux_shell_prompt_regex = re.compile(r"[0-9]+ \$")

    def up(self, tempt = None,
           user = None, login_regex = re.compile('login:'),
           password = None, password_regex = re.compile('Password:')):
        """
        Giving it ample time to boot, wait for a shell prompt and set
        up the shell so that if an error happens, it will print an error
        message and raise a block exception.
        """
        def _login(target):
            # If we have login info, login to get a shell prompt
            target.expect(login_regex)
            target.send(user)
            if password:
                target.expect(password_regex)
                target.send(password)
                    
        self.target.testcase.expecter.timeout = 120
        if tempt:
            assert isinstance(tempt, basestring)
            tries = 0
            while tries < self.target.testcase.expecter.timeout:
                try:
                    self.target.send(tempt)
                    if user:
                        _login(self.target)
                    self.target.expect(self.linux_shell_prompt_regex,
                                       timeout = 1)
                    break
                except tc.error_e as _e:
                    if tries == self.target.testcase.expecter.timeout:
                        raise tc.error_e(
                            "Waited too long (%ds) for shell to come up "
                            "(did not receive '%s')" %
                            (self.target.testcase.expecter.timeout,
                             self.linux_shell_prompt_regex.pattern))
                    continue
        else:
            if user:
                _login(self.target)
            self.target.expect(self.linux_shell_prompt_regex)

        # disable line editing for proper recording of command line
        # when running bash; otherwise the scrolling readline does
        # messes up the output
        self.run('test ! -z "$BASH" && set +o vi +o emacs')
        # Trap the shell to complain loud if a command fails, and catch it
        # See that '' in the middle, is so the catcher later doesn't
        # get tripped by the command we sent to set it up
        self.run("trap 'echo ERROR''-IN-SHELL' ERR")
        self.target.on_console_rx("ERROR-IN-SHELL", result = 'errr',
                                  timeout = False)

        # Now commands should timeout fast
        self.target.testcase.expecter.timeout = 30


    def run(self, cmd = None, expect = None, prompt_regex = None,
            output = False, output_filter_crlf = True):
        """Runs *some command* as a shell command and wait for the shell
        prompt to show up.

        If it fails, it will raise an exception. If you want to get
        the error code or not have it raise exceptions on failure, you
        will have to play shell-specific games, such as:

        >>> target.shell.run("failing-command || true")

        Files can be easily generated in *unix* targets with commands
        such as:

        >>>     target.shell.run(\"\"\"
        >>> cat > /etc/somefile <<EOF
        >>> these are the
        >>> file contents
        >>> that I want
        >>> EOF\"\"\")

        or collecting the output:

        >>> target.shell.run("ls -1 /etc/", output = True)
        >>> for file in output.split("\r\n"):
        >>>     target.report_info("file %s" % file)
        >>>     target.shell.run("md5sum %s" % file)

        :param str cmd: (optional) command to run; if none, only the
          expectations are waited for (if *expect* is not set, then
          only the prompt is expected).
        :param expect: (optional) output to expect (string or
          regex) before the shell prompt. This an also be a list of
          things to expect (in the given order)
        :param prompt_regex: (optional) output to expect (string or
          regex) as a shell prompt, which is always to be found at the
          end. Defaults to the preconfigured shell prompt (NUMBER $).
        :param bool output: (optional, default False) return the
          output of the command to the console; note the output
          includes the execution of the command itself.
        :param bool output_filter_crlf: (optional, default True) if we
          are returning output, filter out \r\n to whatever our CRLF
          convention is.
        :returns str: if ``output`` is true, a string with the output
          of the command.

          .. warning:: if ``output_filter_crlf`` is False, this output
             will be \r\n terminated and it will be confusing because
             regex won't work right away. A quick, dirty, fix

             >>> output = output.replace("\r\n", "\n")

             ``output_filter_crlf`` enabled replaces this output with

             >>> output = output.replace("\r\n", target.crlf)

        """
        if cmd:
            assert isinstance(cmd, basestring)
        assert expect == None \
            or isinstance(expect, basestring) \
            or isinstance(expect, re._pattern_type) \
            or isinstance(expect, list)
        assert prompt_regex == None \
            or isinstance(prompt_regex, basestring) \
            or isinstance(prompt_regex, re._pattern_type)

        if output:
            offset = self.target.console.size()

        if cmd:
            self.target.send(cmd)
        if expect:
            if isinstance(expect, list):
                for expectation in expect:
                    assert isinstance(expectation, basestring) \
                        or isinstance(expectation, re._pattern_type)
                    self.target.expect(expectation)
            else:
                self.target.expect(expect)
        if prompt_regex == None:
            self.target.expect(self.linux_shell_prompt_regex)
        else:
            self.target.expect(prompt_regex)
        if output:
            output = self.target.console.read(offset = offset)
            if output_filter_crlf:
                return output.replace("\r\n", self.target.crlf)
            return output
        return None

    def file_remove(self, remote_filename):
        """
        Remove a remote file (if the target supports it)
        """
        assert isinstance(remote_filename, basestring)
        self.run("rm -f " + remote_filename)

    def file_copy_to(self, local_filename, remote_filename):
        """\
        Send a file to the target via the console (if the target supports it)

        Encodes the file to base64 and sends it via the console in chunks
        of 64 bytes (some consoles are kinda...unreliable) to a file in
        the target called /tmp/file.b64, which then we decode back to
        normal.

        Assumes the target has python3; permissions are not maintained

        .. note:: it is *slow*. The limits are not well defined; how
                  big a file can be sent/received will depend on local
                  and remote memory capacity, as things are read
                  hole. This could be optimized to stream instead of
                  just read all, but still sending a way big file over
                  a cheap ASCII protocol is not a good idea. Warned
                  you are.

        """
        assert isinstance(local_filename, basestring)
        assert isinstance(remote_filename, basestring)
        with open(local_filename, "rb") as f:
            s = binascii.b2a_base64(f.read())
            for i in range(0, len(s), 64):
                # increase the log level to report each chunk of the
                # file we are transmitting
                with msgid_c("C.%d" % i, l = 3):
                    self.run("echo -n %s  >> /tmp/file.b64"
                             % s[i:i+64].decode('utf-8').strip())

        # Now we do a python3 command in there (as cloud
        # versions don't include python2. good) to regenerate
        # it from base64 to bin
        self.file_remove(remote_filename)
        self.run(
            'python3 -c "import sys, binascii; '
            'sys.stdout.buffer.write(binascii.a2b_base64(sys.stdin.read()))"'
            ' < /tmp/file.b64 > %s' % remote_filename)
        # FIXME: checksum and verify :/
