#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
Run commands a shell available on a target's serial console
-----------------------------------------------------------

Also allows basic file transmission over serial line.

Shell prompts
^^^^^^^^^^^^^

Waiting for a shell prompt is quite a harder problem that it seems to
be at the beginning.

Problems:

- Background processes or (in the serial console, the kernel) printing
  lines in the middle.

  Even with line buffered output, when there are different CRLF
  conventions, a misplaced newline or carriage return can break havoc.

  As well, if a background process / kernel prints a message after the
  prompt is printed, a ``$`` will no longer match. The ``\Z`` regex
  operator cannot be used for the same reason.

- CRLF conventions make it harder to use the ``^`` and ``$`` regex
  expression metacharacteds.

- ANSI sequences, human doesn't see/notice them, but to the computer /
  regular expression they are 

Thus, resorting to match a single line is the best bet; however, it is
almost impossible to guarantee that it is the last one as the multiple
formats of prompts could be matching other text.
"""

import binascii
import collections
import re
import time

import tc

from . import msgid_c


# From http://ascii-table.com/ansi-escape-sequences.php
# add any character that can be in a prompt to specify user names,
# paths, etc  -- note we make the ANSI pattern fully optional (*), in
# case we have prompts that don't use it.
ansi_pattern =                r"[\x1b=;\[0-9A-Za-z]*"
ansi_pattern_prompt = r"[-/\@_~: \x1b=;\[0-9A-Za-z]+"

#: .. _waiting_shell_prompts:
#:
#:
#: What is in a shell prompt?
#:
shell_prompts = [
    #: - multicolor prompts (eggg. ANSI sequences)
    #:   'SOMETHING # ' or 'SOMETHING $ '
    ansi_pattern_prompt + " " + ansi_pattern + r"[#\$]" + ansi_pattern + " ",
    #: - Fedora
    r'[^@]+@.*[#\$] ',
    # SLES; make sure there is no trailing space, otherwise it gets
    # confused with the ANSI colouring sequences that come between them
    # and the space.
    # > makes ACRN match too
    r'[^:]+:.*[#\$>]',
]

_shell_prompt_regex = \
    re.compile('(TCF-[0-9a-zA-Z]{4})?(' + "|".join(shell_prompts) + ')')

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
    exception. Note you can change what is expected as a :data:`shell
    prompt <shell_prompt_regex>`.

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

    #: What do we look for into a shell prompt
    #:
    #: This is a Python regex that can be set to recognize what the
    #: shell prompt looks like. Multiple catchas here:
    #:
    #: - use a fixed string or compile the regex
    #:
    #: - if using ^ and/or $, even with re.MULTILINE, things tend not
    #:   to work so well because of \r\n line conventions vs \n...YMMV
    #:
    #: - ANSI chars...
    #:
    #:
    #: Note we don't force it has to start at the beginning of a line
    #: with ^ because then we might hit problems with different \r\n
    #: sequences when some kernel messages are intermixed in the
    #: console output, like when we mount.
    #:
    #: \Z means match the end of the string, the prompt is the last
    #: thing, period -- this means if something is printing spurious
    #: messages...yeah, it will fail to detect the prompt.
    #:
    #: The defaults are collected by joining the list
    #: :data:`shell_prompts`, which contains multiple prompt patterns
    #: that work for a bunch of OSes. More can be added FIXME: procedure
    #:
    #: Examples:
    #:
    #: >>> target.shell
    #:
    # default is set by the global variable
    shell_prompt_regex = _shell_prompt_regex

    #: Deprecated, use :data:`shell_prompt_regex`
    linux_shell_prompt_regex = shell_prompt_regex

    def up(self, tempt = None,
           user = None, login_regex = re.compile('login:'), delay_login = 0,
           password = None, password_regex = re.compile('[Pp]assword:'),
           shell_setup = True, timeout = 120):
        """Wait for the shell in a console to be ready

        Giving it ample time to boot, wait for a :data:`shell prompt
        <shell_prompt_regex>` and set up the shell so that if an
        error happens, it will print an error message and raise a
        block exception. Optionally login as a user and password.

        >>> target.shell.up(user = 'root', password = '123456')

        :param str tempt: (optional) string to send before waiting for
          the loging prompt (for example, to send a newline that
          activates the login)

        :param str user: (optional) if provided, it will wait for
          *login_regex* before trying to login with this user name.

        :param str password: (optional) if provided, and a password
          prompt is found, send this password.

        :param str login_regex: (optional) if provided (string
          or compiled regex) and *user* is provided, it will wait for
          this prompt before sending the username.

        :param str password_regex: (optional) if provided (string
          or compiled regex) and *password* is provided, it will wait for
          this prompt before sending the password.

        :param int delay_login: (optional) wait this many seconds
          before sending the user name after finding the login prompt.

        :param bool shell_setup: (optional, default) setup the shell
          up by disabling command line editing (makes it easier for
          the automation) and set up hooks that will raise an
          exception if a shell command fails.

        :param int timeout: [optional] seconds to wait for the login
          prompt to appear

        """
        assert tempt == None or isinstance(tempt, basestring)
        assert user == None or isinstance(user, basestring)
        assert isinstance(login_regex, ( basestring, re._pattern_type ))
        assert delay_login >= 0
        assert password == None or isinstance(password, basestring)
        assert isinstance(password_regex, ( basestring, re._pattern_type ))
        assert isinstance(shell_setup, bool)
        assert timeout > 0

        target = self.target

        def _login(target):
            # If we have login info, login to get a shell prompt
            target.expect(login_regex)
            if delay_login:
                target.report_info("Delaying %ss before login in"
                                   % delay_login)
                time.sleep(delay_login)
            target.send(user)
            if password:
                target.expect(password_regex)
                target.send(password)

        try:
            original_timeout = self.target.testcase.tls.expecter.timeout
            self.target.testcase.tls.expecter.timeout = timeout
            if tempt:
                tries = 0
                while tries < self.target.testcase.tls.expecter.timeout:
                    try:
                        self.target.send(tempt)
                        if user:
                            _login(self.target)
                        target.expect(self.linux_prompt_regex)
                        break
                    except tc.error_e as _e:
                        if tries == self.target.testcase.tls.expecter.timeout:
                            raise tc.error_e(
                                "Waited too long (%ds) for shell to come up "
                                "(did not receive '%s')" %
                                (self.target.testcase.tls.expecter.timeout,
                                 self.shell_prompt_regex.pattern))
                        continue
            else:
                if user:
                    _login(self.target)
                target.expect(self.shell_prompt_regex)
        finally:
            self.target.testcase.tls.expecter.timeout = original_timeout

        if shell_setup:
            # 
            self.run('export PS1="TCF-%s:$PS1"' % target.kws['tc_hash'])
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
        self.target.testcase.tls.expecter.timeout = 30

    def _run(self, cmd = None, expect = None, prompt_regex = None,
             output = False, output_filter_crlf = True, trim = False):
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
            self.target.expect(self.shell_prompt_regex)
        else:
            self.target.expect(prompt_regex)
        if output:
            output = self.target.console.read(offset = offset)
            if output_filter_crlf:
                output = output.replace("\r\n", self.target.crlf)
            if trim:
                # FIXME: not good enough, if the output didn't include
                # a nl, it will mess it up -- use regex finding
                first_nl = output.find(self.target.crlf)
                last_nl = output.rfind(self.target.crlf)
                output = output[first_nl+1:last_nl+1]
            return output
        return None

    def run(self, cmd = None, expect = None, prompt_regex = None,
            output = False, output_filter_crlf = True, timeout = None,
            trim = False):
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
        >>> for file in output.split('\\r\\n'):
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
          are returning output, filter out ``\\r\\n`` to whatever our CRLF
          convention is.
        :param bool trim: if ``output`` is True, trim the command and
          the prompt from the beginning and the end of the output
          respectively (True)
        :returns str: if ``output`` is true, a string with the output
          of the command.

          .. warning:: if ``output_filter_crlf`` is False, this output
             will be ``\\r\\n`` terminated and it will be confusing because
             regex won't work right away. A quick, dirty, fix

             >>> output = output.replace('\\r\\n', '\\n')

             ``output_filter_crlf`` enabled replaces this output with

             >>> output = output.replace('\\r\\n', target.crlf)

        """
        assert timeout == None or timeout > 0, \
            "timeout has to be a greater than zero number of seconds " \
            "(got %s)" % timeout
        testcase = self.target.testcase
        original_timeout = testcase.tls.expecter.timeout
        try:
            if timeout:
                testcase.tls.expecter.timeout = timeout
            return self._run(
                cmd = cmd, expect = expect,
                prompt_regex = prompt_regex,
                output = output, output_filter_crlf = output_filter_crlf,
                trim = trim)
        finally:
            if timeout:
                testcase.tls.expecter.timeout = original_timeout

    def file_remove(self, remote_filename):
        """
        Remove a remote file (if the target supports it)
        """
        assert isinstance(remote_filename, basestring)
        
        self.run("rm -f " + remote_filename)

    def files_remove(self, *remote_filenames):
        """
        Remove a multiple remote files (if the target supports it)
        """
        assert isinstance(remote_filenames, collections.Iterable)
        
        self.run("rm -f " + " ".join(remote_filenames))

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
        self.files_remove(remote_filename, "/tmp/file.b64")
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
        self.run(
            'python3 -c "import sys, binascii; '
            'sys.stdout.buffer.write(binascii.a2b_base64(sys.stdin.read()))"'
            ' < /tmp/file.b64 > %s' % remote_filename)
        # FIXME: checksum and verify :/

    def file_copy_from(self, local_filename, remote_filename):
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

        # Now we do a python3 command in there (as cloud
        # versions don't include python2. good) to encode the file in
        # b64 and read it from the console
        output = self.run(
            'python3 -c "import sys, binascii; '
            'sys.stdout.buffer.write(binascii.b2a_base64(sys.stdin.read()))"'
            ' < %s' % remote_filename, output = True, trim = True)
        # output comes as
        ## python3 -c...
        ## B64DATA
        ## PROMPT
        # so extract it
        first_nl = output.find('\n')
        last_nl = output.rfind('\n')
        output = output[first_nl+1:last_nl+1]
        with open(local_filename, "wb") as f:
            for line in output.splitlines():
                data = binascii.a2b_base64(line)
                f.write(data)
        # FIXME: checksum and verify :/
