#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Run commands a shell available on a target's serial console
-----------------------------------------------------------

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
  prompt is printed, a ``$`` will no longer match. The ``\\Z`` regex
  operator cannot be used for the same reason.

- CRLF conventions make it harder to use the ``^`` and ``$`` regex
  expression metacharacteds.

- ANSI sequences, human doesn't see/notice them, but to the computer /
  regular expression they are

Thus, resorting to match a single line is the best bet; however, it is
almost impossible to guarantee that it is the last one as the multiple
formats of prompts could be matching other text.

Fixups
^^^^^^

Some shells need to deal with output from background processes that
interrupts the shell; fixups provide a way to deal with it by
recognizing that output, reporting it and continuing typing.

For hard coding into the inventory, add to the inventory keys such
as::

  shell.fixups.CONTEXTNAME.NAME: PYTHONREGEXPATTERN

For coding in the tescase:

  >>> target.kws['shell']['fixups'][CONTEXTNAME][NAME] = PYTHONREGEXPATTERN

Where *CONTEXTNAME* is the name of a shell :ref:`context
<shell_c.context>` where this fixup will apply, *NAME* is a name that
will be used for reporting when *PYTHONREGEXPATTERN* is found in the
output (which is this is a Python regex pattern).

For each, a fixup object will be created when the shell is moved to
use the right context.

When found while typing a command, the :ref:`fixup <shell_c.fixup_c>`
object will detect it, report the occurrence of the output and then
keep typing whichever command was being typed halfway.

"""

import binascii
import collections
import re
import threading
import time
import traceback
import typing

import commonl
from . import tc
from . import target_ext_console

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

class _context_c:
    # Encapsulates a context change
    #
    # when using this to enter a with block associated to a
    # target.shell object, this pushes the current contect name,
    # prompt regexs and fixups in a LIFO stack.

    # New fixups matching the context are loaded
    #
    # On exit, the prompt regexes and fixups from the previous context
    # are restored

    def __init__(self, shell, context_name):
        self.shell = shell
        self.context_name = context_name

    def __enter__(self):
        setattr(self.shell.tls, "contexts", [])
        setattr(self.shell.tls, "prompt_regexs", [])
        setattr(self.shell.tls, "fixups", [])

        self.shell.tls.contexts.append(self.context_name)
        self.shell.tls.prompt_regexs.append(self.shell.prompt_regex)

        target = self.shell.target
        self.shell.tls.fixups.append(self.shell._fixups)
        self.shell._fixups = {}
        # Load fixups
        # shell.fixups.CONTEXTNAME.FIXUP1: REGEX1
        # shell.fixups.CONTEXTNAME.FIXUP2: REGEX2..
        #
        # Generate a fixup console expecter for each that _run() will use
        fixups = target.kws.get("shell", {}).get("fixups", {}).get(self.context_name, {})
        for name, regex in fixups.items():
            self.shell._fixups[name] = target.shell.fixup_c(
                re.compile(regex), name = name,
                target = self.shell.target, timeout = 0)


    def __exit__(self, *args, **kwargs):
        self.shell.tls.contexts.pop()
        self.shell.prompt_regex = self.shell.tls.prompt_regexs.pop()
        self.shell._fixups = self.shell.tls.fixups.pop()


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
    prompt <prompt_regex>`.

    >>> target.shell.run("some command")

    Remove remote files (if the target supports it) with:

    >>> target.shell.file_remove("/tmp/filename")

    Copy files to the target with:

    >>> target.shell.file_copy_to("local_file", "/tmp/remote_file")
    """

    def __init__(self, target):
        if 'console' not in target.rt['interfaces']:
            raise self.unneeded
        tc.target_extension_c.__init__(self, target)
        self.tls = threading.local()
        self.tls.contexts = []
        self.tls.prompt_regexs = []
        self.tls.fixups = []
        self._fixups = {}

    def context(self, context_name):
        """
        Switch to a new context

        A shell object has a context defined by:

        - a name
        - the current prompt regular expression (:data:`prompt_regex`)
        - the current fixups (loaded from the inventory)

        With this, the context can be associated to a with block:

        >>> with target.shell.context("iPXE booting"):
        >>>    target.shell.prompt_regex = "iPXE>"
        >>>    ...

        In the block, any fixups the shell module does are those
        associated to the *iPXE* context (from the inventory
        *shell.fixups.iPXE booting* section).

        Upon exit the previous prompt regex is automatically restored,
        as well as previous fixups.
        """
        return _context_c(self, context_name)

    prompt_regex_default = \
        re.compile('(TCF-[0-9a-zA-Z]{4})?(' + "|".join(shell_prompts) + ')')

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
    prompt_regex = prompt_regex_default

    #: Deprecated, use :data:`prompt_regex`
    @property
    def shell_prompt_regex(self):
        role = self.target.want_name
        self.target.report_info(
            "DEPRECATED: %s.pos.shell_prompt_regex is deprecated in"
            " favour of %s.pos.prompt_regex" % (role, role),
            dict(trace = traceback.format_stack()))
        return self.prompt_regex

    @shell_prompt_regex.setter
    def shell_prompt_regex(self, val):
        role = self.target.want_name
        self.target.report_info(
            "DEPRECATED: %s.pos.shell_prompt_regex is deprecated in"
            " favour of %s.pos.prompt_regex" % (role, role),
            dict(trace = traceback.format_stack()))
        self.prompt_regex = val

    #: Deprecated, use :data:`prompt_regex`
    @property
    def linux_shell_prompt_regex(self):
        role = self.target.want_name
        self.target.report_info(
            "DEPRECATED: %s.pos.linux_shell_prompt_regex is deprecated in"
            " favour of %s.pos.prompt_regex" % (role, role),
            dict(trace = traceback.format_stack()))
        return self.prompt_regex

    @linux_shell_prompt_regex.setter
    def linux_shell_prompt_regex(self, val):
        role = self.target.want_name
        self.target.report_info(
            "DEPRECATED: %s.pos.linux_shell_prompt_regex is deprecated in"
            " favour of %s.pos.prompt_regex" % (role, role),
            dict(trace = traceback.format_stack()))
        self.prompt_regex = val


    def setup(self, console = None):
        """
        Setup the shell for scripting operation

        In the case of a bash shell, this:
        - sets the prompt to something easer to latch on to
        - disables command line editing
        - traps errors in shell execution
        """
        target = self.target
        testcase = target.testcase
        # dereference which console we are using; we don't want to
        # setup our trackers below to the "default" console and leave
        # it floating because then it will get confused if we switch
        # default consoles.
        console = target.console._console_get(console)
        self.run('export PS1="TCF-%s:$PS1"' % self.target.kws['tc_hash'],
                 console = console)
        # disable line editing for proper recording of command line
        # when running bash; otherwise the scrolling readline does
        # messes up the output
        self.run('test ! -z "$BASH" && set +o vi +o emacs',
                 console = console)
        # Trap the shell to complain loud if a command fails, and catch it
        # See that '' in the middle, is so the catcher later doesn't
        # get tripped by the command we sent to set it up
        self.run("trap 'echo ERROR''-IN-SHELL' ERR",
                 console = console)
        testcase.expect_global_append(
            # add a detector for a shell error, make sure to name it
            # after the target and console it will monitor so it
            # doesn't override other targets/consoles we might be
            # touching in parallel
            target.console.text(
                "ERROR-IN-SHELL",
                name = "%s:%s: shell error" % (target.want_name, console),
                console = console, timeout = 0, poll_period = 1,
                raise_on_found = tc.error_e("error detected in shell")),
            # if we have already added detectors for this, that's
            # fine, ignore them
            skip_duplicate = True
        )

    def setup_windows(self, console = None):
        """
        Setup the Windows shell for scripting operation

        In the case of a bash shell, this:

        - sets the prompt to something easer to latch on to with less
          false negatives

        - traps errors in shell execution

        This function is meant to be used by :meth:`up`:

        >>> class _test(tcfl.tc.tc_c):
        >>>
        >>>     def eval(self, target):
        >>>         target.power.cycle()
        >>>         target.shell.up(shell_setup = target.shell.setup_windows)
        >>>

        """
        target = self.target
        # dereference which console we are using; we don't want to
        # setup our trackers below to the "default" console and leave
        # it floating because then it will get confused if we switch
        # default consoles.
        console = target.console._console_get(console)
        self.prompt_regex = re.compile(
            "TCF-%s:[^>]+>" % self.target.kws['tc_hash'])
        self.run('set prompt=TCF-%s:%%PROMPT%%' % self.target.kws['tc_hash'],
                 console = console)
        # I do not know of any way to trap general shell error
        # commands in Windows that can be used to print a message that
        # then raises an exception (see :meth:setup)


    def up(self, tempt = None,
           user = None, login_regex = re.compile('login:'), delay_login = 0,
           password = None, password_regex = re.compile('[Pp]assword:'),
           shell_setup = True, timeout = None, console = None,
           wait_for_early_shell_prompt = True):
        """Wait for the shell in a console to be ready

        Giving it ample time to boot, wait for a :data:`shell prompt
        <prompt_regex>` and set up the shell so that if an
        error happens, it will print an error message and raise a
        block exception. Optionally login as a user and password.

        Note this resets any shell prompt set by the script to what is
        assumed to be the original one after a power up.

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

        :param shell_setup: (optional, default) setup the shell
          up by disabling command line editing (makes it easier for
          the automation) and set up hooks that will raise an
          exception if a shell command fails.

          By default calls target.shell.setup(); if *False*, nothing
          will be called. Arguments are passed:

          - *console = CONSOLENAME*: console where to operate; can be
            *None* for the default console.

        :param int timeout: [optional] seconds to wait for the login
          prompt to appear; defaults to 60s plus whatever the target
          specifies in metadata *bios_boot_time*.

        :param str console: [optional] name of the console where to
          operate; if *None* it will update the current default
          console to whatever the server considers it shall be (the
          console called *default*).

          If a previous run set the default console to something else,
          setting it to *None* will update it to what the server
          considers shall be the default console (default console at
          boot).

        """
        assert tempt == None or isinstance(tempt, str)
        assert user == None or isinstance(user, str)
        assert login_regex == None or isinstance(login_regex, ( str, re.Pattern ))
        assert delay_login >= 0
        assert password == None or isinstance(password, str)
        assert isinstance(password_regex, ( str, typing.Pattern ))
        assert isinstance(shell_setup, bool) or callable(shell_setup)
        assert timeout == None or timeout > 0
        assert console == None or isinstance(console, str)

        target = self.target
        testcase = target.testcase
        if timeout == None:
            bios_boot_time = int(target.kws.get(
                "bios.boot_time",
                target.kws.get("bios_boot_time", 0)	# COMPAT: legacy
            ))
            timeout = 60 + bios_boot_time
        # Set the original shell prompt
        self.prompt_regex = self.prompt_regex_default

        def _login(target):
            # If we have login info, login to get a shell prompt
            if login_regex != None:
                # we have already recevied this, so do not expect it
                target.expect(login_regex, name = "login prompt",
                              console = console)
            if delay_login:
                target.report_info("Delaying %ss before login in"
                                   % delay_login)
                time.sleep(delay_login)
            target.send(user)
            if password:
                target.expect(password_regex, name = "password prompt",
                              console = console)
                target.send(password, console = console)

        original_timeout = testcase.tls.expect_timeout
        try:
            if console == None:		# reset the default console
                target.console.default = None
                # this will yield the default console name, not None
                # as we set it above; bad API
                console = target.console.default
            testcase.tls.expect_timeout = timeout
            ts0 = time.time()
            ts = ts0
            inner_timeout = 3 * timeout / 20
            logged_in = False
            while ts - ts0 < 3 * timeout:
                # if this was an SSH console that was left
                # enabled, it will die and auto-disable when
                # the machine power cycles, so make sure it is enabled
                action = "n/a"
                try:
                    if console.startswith("ssh"):
                        target.console.disable()
                        action = "enable console %s" % console
                        target.console.setup(console,
                                             user = user, password = password)
                        target.console.enable(console = console)
                        ts = time.time()
                        target.report_info(
                            "shell-up: %s: success at +%.1fs"
                            % (action, ts - ts0), dlevel = 2)
                    if tempt:
                        action = "tempt console %s" % console
                        target.send(tempt, console = console)
                        ts = time.time()
                        target.report_info(
                            "shell-up: %s: success at +%.1fs"
                            % (action, ts - ts0), dlevel = 2)
                    if not console.startswith("ssh"):
                        if user and not logged_in:
                            action = "login in via console %s" % console
                            # _login uses this 'console' definition
                            _login(self.target)
                            # no need to wait for a login prompt again
                            # next time we retry
                            logged_in = True
                            ts = time.time()
                            target.report_info(
                                "shell-up: %s: success at +%.1fs"
                                % (action, ts - ts0), dlevel = 2)
                    if wait_for_early_shell_prompt:
                        action = "wait for shell prompt"
                        target.expect(self.prompt_regex,
                                      console = console,
                                      name = "early shell prompt",
                                      timeout = inner_timeout)
                    break
                except ( tc.error_e, tc.failed_e ) as e:
                    ts = time.time()
                    target.report_info(
                        "shell-up: action '%s' failed at +%.1fs; retrying: %s"
                        % (action, ts - ts0, e),
                        dict(target = target, exception = e),
                        dlevel = 2)
                    time.sleep(inner_timeout)
                    ts = time.time()
                    if console.startswith("ssh"):
                        target.console.disable(console = console)
                    if login_regex and user:
                        # sometimes the kernel spews stuff when we are
                        # trying to login and we can't find the
                        # prompt, so send a couple of blind <CRLFs>
                        # see if the prompt shows up propelry
                        target.report_info(
                            "shell-up: sending a couple of blind CRLFs"
                            " to clear the command line")
                        # ntoe we do not use target.send(), because we
                        # don't want to reset the send/expect markers
                        time.sleep(0.5)
                        target.console.write("\r\n")
                        time.sleep(0.5)
                        target.console.write("\r\n")
                    continue
            else:
                raise tc.error_e(
                    "Waited too long (%ds) for shell to come up on"
                    " console '%s' (did not receive '%s')" % (
                        3 * timeout, console,
                        self.prompt_regex.pattern), dict(target = target))
        finally:
            testcase.tls.expect_timeout = original_timeout

        # same as target.console.select_preferred()
        if shell_setup == True:    	# passed as a parameter
            target.shell.setup(console)
        elif callable(shell_setup):
            shell_setup(console)
        # False, so we don't call shell setup
        # don't set a timeout here, leave it to whatever it was defaulted
        return


    class fixup_c(target_ext_console.expect_text_on_console_c):
        """Assist in restarting partially interrupted commands

        In some shells, when typing commands into the console, messages
        are suddenly printed and the typing is interrupted halfway.

        This object is a expecter used to catch those messages and
        continue the typing without loosing the command. Working in
        coordination with :meth:`run` analyze how much of the command
        was echoed back to then continue

        This only works when the other side echoes; the flow is
        something like this::

          PROMPT> I am typing this command

        halfway through it, an error would be printed and the console
        output would look like::

          PROMPT> ERRORMESSAGEI am typing

        note at this point the sendind side has sent the whole::

          I am typing this command

        string but only the::

          I am typing

        part is echoed. This object will identify the error, report it
        as a recoverable condition and then adjust the expectation for
        target.shell.run() so it can re-type the rest.

        """

        def on_found(self, run_name, poll_context, buffers_poll, buffers,
                     ellapsed, timeout, match_data):
            testcase = self.target.testcase
            # these are matches specific to
            # tcfl.target_ext_console.expect_text_on_console_c; look at
            # its doc for details
            of = buffers_poll['of']
            start = match_data['offset_match_start']
            end = match_data['offset_match_end']
            # @of is the file that has what was read from the console,
            # @start is where the match start, @ends is ... guess it :)
            of.seek(start)
            text = of.read(end - start).strip().decode('utf-8')
            rest = of.read().decode('utf-8')
            # We'll file this under a buffer to keep track of how many are
            # found during execution
            name = f"shell fixup: {self.name} [{text}]"
            with testcase.lock:
                testcase.buffers.setdefault(name, 0)
                testcase.buffers[name] += 1
                count = testcase.buffers[name]
            # And each time we report it as a new KPI; this serves two
            # purposes; it reports them as it happened with a timestamp
            # and the last one serves as a count of how many times we
            # recovered each error message.
            self.target.report_data("Recovered conditions [%(type)s]", name, count)

            # Now, did this happen in the middle of sending a command with
            # target.shell.run?
            #
            # We need to recover so that target.shell.run() can keep
            # running. We got echo of how much was received, so let's get
            # the echo expecter to be happy with receiving only what was
            # received before being interrupted so that target.shell.run()
            # can send the rest.
            if testcase.tls.echo_cmd:
                # this is a hack, but we might have CRLFs (\r\n) or
                # similar in the beginning, so just wipe it
                rest = rest.lstrip()
                if rest < testcase.tls.echo_cmd:
                    testcase.tls.echo_cmd_leftover = commonl.removeprefix(
                        testcase.tls.echo_cmd, rest)
                    testcase.tls.echo_waiter.regex_set(rest)
            # this ends here and processing continues in target.shell.run
            # when it called testcase.expect(); the loop will be run again
            # and next time, the echo waiter will process only the part we
            # have seen received.


    def _run(self, cmd = None, expect = None, prompt_regex = None,
             output = False, output_filter_crlf = True, trim = False,
             console = None, origin = None):
        if cmd:
            assert isinstance(cmd, str)
        assert expect == None \
            or isinstance(expect, str) \
            or isinstance(expect, typing.Pattern) \
            or isinstance(expect, list)
        assert prompt_regex == None \
            or isinstance(prompt_regex, str) \
            or isinstance(prompt_regex, typing.Pattern)

        if origin == None:
            origin = commonl.origin_get(3)
        else:
            assert isinstance(origin, str)

        target = self.target
        testcase = target.testcase

        if output:
            offset = self.target.console.size(console = console)

        # the protocol needs UTF-8 anyway
        cmd = commonl.str_cast_maybe(cmd)
        if cmd and not self._fixups:
            self.target.send(cmd, console = console)
        if cmd and self._fixups:
            # we have to handle CRLF at the end ourselves here, we
            # can't defer to target.send() -- see that for how we get
            # crlf.
            if console == None:
                console = target.console.default
            crlf = target.console.crlf.get(console, None)
            cmd += crlf

            try:
                # send the command, doing echo verification if
                if origin == None:
                    origin = commonl.origin_get(2)
                testcase.tls.echo_cmd = cmd
                testcase.tls.echo_waiter = self.target.console.text(
                    cmd, name = "shell echo",
                    console = console, timeout = 10,
                )
                while True:
                    testcase.tls.echo_cmd_leftover = None
                    self.target.send(testcase.tls.echo_cmd,
                                     crlf = None, console = console)
                    testcase.tls.echo_waiter.regex_set(testcase.tls.echo_cmd)
                    testcase.expect(
                        testcase.tls.echo_waiter,
                        **self._fixups,
                    )
                    if testcase.tls.echo_cmd_leftover == None:
                        break
                    self.target.report_info(
                        "shell/fixup: resuming partially interrupted command"
                        " by message printed in console; sending: "
                        + commonl.str_bytes_cast(testcase.tls.echo_cmd, str))
                    testcase.tls.echo_cmd = testcase.tls.echo_cmd_leftover
                    continue
            finally:
                testcase.tls.echo_cmd = None
        if expect:
            if isinstance(expect, list):
                for expectation in expect:
                    assert isinstance(expectation, str) \
                        or isinstance(expectation, typing.Pattern)
                    target.expect(expectation, name = "command output",
                                  console = console, origin = origin)
            else:
                target.expect(expect, name = "command output",
                              console = console, origin = origin)
        if prompt_regex == None:
            self.target.expect(self.prompt_regex, name = "shell prompt",
                               console = console, origin = origin)
        else:
            self.target.expect(prompt_regex, name = "shell prompt",
                               console = console, origin = origin)
        if output:
            if console == None:
                console = target.console.default
            if output_filter_crlf:
                newline = None
            else:
                newline = ''
            output = self.target.console.read(
                offset = offset, console = console, newline = newline)
            if trim:
                # When we can run(), it usually prints in the console:
                ## <command-echo from our typing>
                ## <command output>
                ## <prompt>
                #
                # So to trim we just remove the first and last
                # lines--won't work well without output_filter_crlf
                # and it is quite a hack.
                first_nl = output.find("\n")
                last_nl = output.rfind("\n")
                output = output[first_nl+1:last_nl+1]
            return output
        return None

    def run(self, cmd = None, expect = None, prompt_regex = None,
            output = False, output_filter_crlf = True, timeout = None,
            trim = False, console = None):
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

        >>> output = target.shell.run("ls --color=never -1 /etc/", output = True)
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
        :param str console: (optional) on which console to run;
          (defaults to *None*, the default console).
        :param str origin: (optional) when reporting information about
          this expectation, what origin shall it list, eg:

          - *None* (default) to get the current caller
          - *commonl.origin_get(2)* also to get the current caller
          - *commonl.origin_get(1)* also to get the current function

          or something as:

          >>> "somefilename:43"
        :returns str: if ``output`` is true, a string with the output
          of the command.

          .. warning:: if ``output_filter_crlf`` is False, this output
             will be ``\\r\\n`` terminated and it will be confusing because
             regex won't work right away. A quick, dirty, fix

             >>> output = output.replace('\\r\\n', '\\n')

             ``output_filter_crlf`` enabled replaces this output with

             >>> output = output.replace('\\r\\n', target.console.crlf[CONSOLENAME])

        """
        assert timeout == None or timeout > 0, \
            "timeout has to be a greater than zero number of seconds " \
            "(got %s)" % timeout
        testcase = self.target.testcase
        original_timeout = testcase.tls.expect_timeout
        try:
            if timeout:
                testcase.tls.expect_timeout = timeout
            return self._run(
                cmd = cmd, expect = expect,
                prompt_regex = prompt_regex,
                output = output, output_filter_crlf = output_filter_crlf,
                trim = trim, console = console)
        finally:
            if timeout:
                testcase.tls.expect_timeout = original_timeout

    def file_remove(self, remote_filename):
        """
        Remove a remote file (if the target supports it)
        """
        assert isinstance(remote_filename, str)

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
        assert isinstance(local_filename, str)
        assert isinstance(remote_filename, str)
        self.files_remove(remote_filename, "/tmp/file.b64")
        with open(local_filename, "rb") as f:
            s = binascii.b2a_base64(f.read())
            for i in range(0, len(s), 64):
                # increase the log level to report each chunk of the
                # file we are transmitting
                with msgid_c("C.%d" % i):
                    self.run("echo -n %s  >> /tmp/file.b64"
                             % s[i:i+64].decode('utf-8').strip())

        # Now we do a python3 command in there (as cloud
        # versions don't include python2. good) to regenerate
        # it from base64 to bin
        self.run(
            'python3 -c "import sys, binascii; '
            'sys.stdout.buffer.write(binascii.a2b_base64(sys.stdin.buffer.read()))"'
            ' < /tmp/file.b64 > %s' % remote_filename)
        # FIXME: checksum and verify :/

    def string_copy_to_file(self, s, remote_filename):
        """\
        Store a string in a target's file via the console (if the target supports it)

        Encodes the file to base64 and sends it via the console in chunks
        of 64 bytes (some consoles are kinda...unreliable) to a file in
        the target called /tmp/file.b64, which then we decode back to
        normal.

        Assumes the target has python3; permissions are not maintained

        See :meth:`file_copy_to`

        .. note:: it is *slow*. The limits are not well defined; how
                  big a file can be sent/received will depend on local
                  and remote memory capacity, as things are read
                  whole. This could be optimized to stream instead of
                  just read all, but still sending a way big file over
                  a cheap ASCII protocol is not a good idea. Warned
                  you are.

        """
        assert isinstance(s, str)
        assert isinstance(remote_filename, str)
        self.files_remove(remote_filename, "/tmp/file.b64")
        s = binascii.b2a_base64(s)
        for i in range(0, len(s), 64):
            # increase the log level to report each chunk of the
            # file we are transmitting
            self.run("echo -n %s  >> /tmp/file.b64"
                     % s[i:i+64].decode('utf-8').strip())

        # Now we do a python3 command in there (as cloud
        # versions don't include python2. good) to regenerate
        # it from base64 to bin
        self.run(
            'python3 -c "import sys, binascii; '
            'sys.stdout.buffer.write(binascii.a2b_base64(sys.stdin.buffer.read()))"'
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
                  whole. This could be optimized to stream instead of
                  just read all, but still sending a way big file over
                  a cheap ASCII protocol is not a good idea. Warned
                  you are.

        """
        assert isinstance(local_filename, str)
        assert isinstance(remote_filename, str)

        # Now we do a python3 command in there (as cloud
        # versions don't include python2. good) to encode the file in
        # b64 and read it from the console
        output = self.run(
            'python3 -c "import sys, binascii; '
            'sys.stdout.buffer.write(binascii.b2a_base64(sys.stdin.buffer.read()))"'
            ' < %s' % remote_filename, output = True)
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
