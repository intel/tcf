#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Run commands to the target and copy files back and forth using SSH
------------------------------------------------------------------

"""

import os
import subprocess

import commonl
from . import tc

class ssh(tc.target_extension_c):
    """Extension to :py:class:`tcfl.tc.target_c` for targets that support
    SSH to run remote commands via SSH or copy files around.

    If the target needs a password, it can be set in :data:`password`:

    .. code-block:: python

       target.ssh.login = "USERNAME
       target.ssh.password = "SOMEPASSWORD"

    The target can be set to passwordless login, either by:

    - disabling password for the target user (**DANGEROUS!!** use only
      on isolated targets)

      See :ref:`related how to disable password in images
      <linux_ssh_no_root_password>`.

    - storing SSH identities in SSH agents (FIXME: not implemented
      yet) and provisioning the keys via cloud-init or similar

    Use as (full usage example in
    :download:`/usr/share/tcf/examples/test_linux_ssh.py
    <../examples/test_linux_ssh.py>`):

    1. As described in :class:`IP tunnels
       <tcfl.target_ext_tunnel.tunnel>`, upon which this extension
       builds, this will only work with a target with IPv4/6
       connectivity, which means there has to be an interconnect
       powered on and reachable for the server and :func:`kept active
       <tcfl.tc.tc_c.targets_active>`, so the server doesn't power it off.

    2. ensure the interconnect is powered on before powering on the
       target; otherwise some targets won't acquire an IP configuration
       (as they will assume there is no interconnect); e.g.: on *start*:

       >>> def start(self, ic, target):
       >>>     ic.power.on()
       >>>     target.power.cycle()
       >>>     target.shell.prompt_regex = re.compile('root@.*# ')
       >>>     target.shell.up(user = 'root')

    2. indicate the tunneling system which IP address is to be
       used:

       >>>     target.tunnel.ip_addr = target.addr_get(ic, "ipv4")

    3. Use SSH::

       >>>     target.ssh.password = "SOMEPASSWORD"
       >>>     exitcode, _stdout, _stderr = target.ssh.call("test -f file_that_should_exist")
       >>>     target.ssh.check_output("test -f file_that_should_exist")
       >>>     output = target.ssh.check_output("cat some_file")
       >>>     if 'what_im_looking_for' in output:
       >>>        do_something()
       >>>     target.ssh.copy_to("somedir/local.file", "remotedir")
       >>>     target.ssh.copy_from("someremotedir/file", "localdir")

    FIXME: provide pointers to a private key to use

    Troubleshooting:

    a. SSH fails to login; open the report file generated with *tcf
       run*, look at the detailed error output:

       - returncode will show as 255: login error-- do you have
         credentials loaded? is the configuration in the target
         allowing you to login as such user with no password? or do
         you have the SSH keys configured?::

           E#1   @local  eval errored: ssh command failed: echo hello
           E#1   @local  ssh_cmd: /usr/bin/ssh -vp 5400 -q -o BatchMode yes -o StrictHostKeyChecking no root@jfsotc10.jf.intel.com -t echo hello
           ...
           E#1   @local  eval errored trace: error_e: ('ssh command failed: echo hello', {'ssh_cmd': '/usr/bin/ssh -vp 5400 -q -o BatchMode yes -o StrictHostKeyChecking no root@jfsotc10.jf.intel.com -t echo hello', 'output': '', 'cmd': ['/usr/bin/ssh', '-vp', '5400', '-q', '-o', 'BatchMode yes', '-o', 'StrictHostKeyChecking no', 'root@jfsotc10.jf.intel.com', '-t', 'echo hello'], 'returncode': 255})
           E#1   @local  returncode: 255

    For seeing verbose SSH output to debug, append ``-v`` to
    variable *_ssh_cmdline_options*::

    >>> target.ssh._ssh_cmdline_options.append("-v")

    """

    def __init__(self, target):
        #if target.rt.get('ssh_client', False) != True:
        #    raise self.unneeded
        self.target = target
        #: SSH destination host; this will be filled out automatically
        #: with any IPv4 or IPv6 address the target declares, but can
        #: be assigned to a new value if needed.
        self.host = None
        ipv4_addr = target.rt.get('ipv4_addr', None)
        ipv6_addr = target.rt.get('ipv6_addr', None)
        if ipv4_addr:
            self.host = ipv4_addr
        elif ipv6_addr:
            self.host = ipv6_addr
        else:
            self.host = None
        #: SSH login identity; default to root login, as otherwise it
        #: would default to the login of the user running the daemon.
        self.login = 'root'
        #: SSH Password to use
        self.password = None
        #: SSH port to use
        self.port = 22

        # Port to where to connect in the server to reach the target's
        # SSH port.
        self._ssh_port = None
        self._ssh_host = None

        self._ssh_cmdline_options = [
            # use a private known host directory -- even with disabled
            # strict host key checking it will disable password auth
            # if there is one and it changes; we'll remove everytime
            # we do a connection to avoid the problem
            "-o", f"UserKnownHostsFile {self._known_hosts_path()}",
            # Most of the machines used for testing get provisioned
            # and re-provisioned over and over again, with no stable
            # SSH key, so mo point on checking it
            "-o", "StrictHostKeyChecking no",
            "-o", "CheckHostIP no",
        ]

    def _known_hosts_path(self):
        return os.path.join(self.target.tmpdir, 'ssh_known_hosts')

    def _known_hosts_wipe(self):
        # wipe known_hosts, to avoid key issues
        commonl.rm_f(self._known_hosts_path())

    def _tunnel(self):
        # Ensure the IP tunnel is up, overriding whatever was there
        # before
        if self._ssh_port != None and self._ssh_host != None:
            return
        target = self.target
        self._ssh_host = target.server.parsed_url.hostname
        self._ssh_port = target.tunnel.add(self.port)

    def tunnel_up(self):
        """
        Return *True* if the SSH tunneling information is set and we
        can run SSH commands to the target.

        This assumes the user has previously setup and started the SSH
        daemon and authentication in the target.
        """
        return self._ssh_host != None and self._ssh_port != None


    def tunnel_refresh(self):
        """
        Wipe the tunnel (if any) and reconstruct it

        This assumes the user has previously setup and started the SSH
        daemon and authentication in the target.
        """
        if self._ssh_port:
            self.target.tunnel.remove(self._ssh_port)
            self._ssh_port = None
        return self._tunnel()


    def _returncode_eval(self, returncode):
        if returncode == 0:
            return
        if returncode == 255:
            self.target.report_info(
                "SSH: returned 255; this usually means failure to login; "
                "append `-v` to list target.shell._ssh_cmdline_options "
                "to get more verbose error output")

    def run(self, cmd, nonzero_e = None):
        """
        Run a shell command over SSH, return exitcode and output

        Similar to :func:`subprocess.call`; note SSH is normally run
        in verbose mode (unless ``-q`` has been set in
        *_ssh_cmdline_options*, so the stderr will contain SSH
        debug information.

        :param str cmd: shell command to execute via SSH, substituting
          any ``%(KEYWORD)[ds]`` field from the target's keywords in
          :attr:`tcfl.tc.target_c.kws`

          See :ref:`how to find
          <finding_testcase_metadata>` which fields are available.

        :param tcfl.tc.exception nonzero_e: exception to raise in case of non
          zero exit code.  Must be a subclass of :class:`tcfl.tc.exception`
          (i.e.: :class:`tcfl.tc.failed_e`,  :class:`tcfl.tc.error_e`,
          :class:`tcfl.tc.skip_e`, :class:`tcfl.tc.blocked_e`) or
          *None* (default) to not raise anything and just return the
          exit code.

        :returns: tuple of ``exitcode, stdout, stderr``, the two later
          being two tempfile file descriptors containing the standard
          output and standard error of running the command.

          The stdout (or stderr) can be read with:

          >>> stdout.read()

        """
        assert nonzero_e == None or issubclass(nonzero_e, tc.exception)
        self._tunnel()
        _cmd = cmd % self.target.kws
        self.target.report_info("running SSH command '%s'" % _cmd, dlevel = 1)
        log_stderr = commonl.logfile_open(
            tag = "stderr", directory = self.target.testcase.tmpdir)
        log_stdout = commonl.logfile_open(
            tag = "stdout", directory = self.target.testcase.tmpdir)
        # We always run check_output to capture the output and
        # display it inthe logs for later analysis
        # if not doing verbose to debug, add -q to avoid getting
        # spurious messages
        if '-v' not in self._ssh_cmdline_options:
            ql = [ '-q' ]
        else:
            ql = []
        env = dict(os.environ)
        if self.password:
            cmdline = [ 'sshpass', "-e" ]
            env['SSHPASS'] = self.password
        else:
            ql += [ '-o', "BatchMode yes" ]
            cmdline = []
        cmdline += [ "ssh", "-p", str(self._ssh_port) ] \
            + self._ssh_cmdline_options + ql \
            + [ self.login + "@" + self._ssh_host, "-t", _cmd ]
        self.target.report_info("running SSH command: %s"
                                % " ".join(cmdline), dlevel = 2)
        self._known_hosts_wipe()
        returncode = subprocess.call(cmdline, stdin = None, shell = False,
                                     stdout = log_stdout, stderr = log_stderr,
                                     env = env,
                                     encoding = 'utf-8')
        log_stdout.seek(0, 0)
        log_stderr.seek(0, 0)
        if returncode != 0:
            self._returncode_eval(returncode)
            if nonzero_e:
                raise nonzero_e(
                    "failed SSH command '%s': %d" % (cmd, returncode),
                    dict(returncode = returncode,
                         stdout = commonl.generator_factory_c(
                             commonl.file_iterator, log_stdout.name),
                         stderr = commonl.generator_factory_c(
                             commonl.file_iterator, log_stderr.name),
                         ssh_cmd = " ".join(cmdline),
                         cmd = cmd,
                         target = self.target))
        self.target.report_info(
            "ran SSH command '%s': %d" % (_cmd, returncode),
            attachments = dict(
                returncode = returncode,
                stdout = commonl.generator_factory_c(
                    commonl.file_iterator, log_stdout.name),
                stderr = commonl.generator_factory_c(
                    commonl.file_iterator, log_stderr.name),
                ssh_cmd = " ".join(cmdline),
                cmd = cmd,
                target = self.target))
        log_stdout.seek(0, 0)
        log_stderr.seek(0, 0)
        return returncode, log_stdout, log_stderr

    def call(self, cmd):
        """
        Run a shell command over SSH, returning the output

        Please see :func:`run` for argument description; the only
        difference is this function raises an exception if the call fails.
        """
        exitcode, _stdout, _stderr = self.run(cmd, nonzero_e = None)
        return exitcode

    def check_call(self, cmd, nonzero_e = tc.error_e):
        """
        Run a shell command over SSH, returning the output

        Please see :func:`run` for argument description; the only
        difference is this function raises an exception if the call fails.
        """
        self.run(cmd, nonzero_e = nonzero_e)

    def check_output(self, cmd, nonzero_e = tc.error_e):
        """
        Run a shell command over SSH, returning the output

        Please see :func:`run` for argument description; the only
        difference is this function returns the stdout only if the
        call succeeds and raises an exception otherwise.
        """
        _exitcode, stdoutf, _stderrf = self.run(cmd, nonzero_e = nonzero_e)
        return stdoutf.read()

    def copy_to(self, src, dst = "", recursive = False,
                nonzero_e = tc.error_e):
        """Copy a file or tree with *SCP* to the target from the client

        :param str src: local file or directory to copy

          Note a relative path will be made relative to the location
          of the testscript, see :func:`testcase.relpath_to_abs
          <tcfl.tc.tc_c.relpath_to_abs>`.

        :param str dst: (optional) destination file or directoy
          (defaults to root's home directory)
        :param bool recursive: (optional) copy recursively (needed for
          directories)

        :param tcfl.tc.exception nonzero_e: exception to raise in case of 
          non zero exit code.  Must be a subclass of :class:`tcfl.tc.exception`
          (i.e.: :class:`tcfl.tc.failed_e`,  :class:`tcfl.tc.error_e`,
          :class:`tcfl.tc.skip_e`, :class:`tcfl.tc.blocked_e`) or
          *None* (default) to not raise anything and just return the
          exit code.

        """
        self._tunnel()
        self.target.report_info("running SCP local:%s -> target:%s"
                                % (src, dst), dlevel = 1)
        src = self.target.testcase.relpath_to_abs(src)
        options = "-vvv"
        if recursive:
            options += "r"
        env = dict(os.environ)
        if self.password:
            cmdline = [ 'sshpass', "-e" ]
            env['SSHPASS'] = self.password
        else:
            cmdline = []
            options += "B"
        try:
            cmdline += \
                [ "scp", options, "-P", str(self._ssh_port) ] \
                + self._ssh_cmdline_options \
                + [ src, self.login + "@" + self._ssh_host + ":" + dst ]
            self.target.report_info("running SCP command: %s"
                                    % " ".join(cmdline), dlevel = 2)
            self._known_hosts_wipe()
            s = subprocess.check_output(cmdline, stderr = subprocess.STDOUT,
                                        shell = False, encoding = 'utf-8',
                                        env = env)
        except subprocess.CalledProcessError as e:
            self._returncode_eval(e.returncode)
            self.target.report_error(
                f"error runing SCP local:{src} -> target:{dst}",
                dict(returncode = e.returncode,
                     output = e.output,
                     src = src, dst = dst, recursive = recursive,
                     ssh_cmd = " ".join(e.cmd),
                     target = self.target))
            commonl.raise_from(nonzero_e(
                "failed SCP local:%s -> target:%s" % (src, dst),
                dict(returncode = e.returncode,
                     output = e.output,
                     src = src, dst = dst, recursive = recursive,
                     ssh_cmd = " ".join(e.cmd),
                     target = self.target
                )), e)
        self.target.report_info("ran SCP local:%s -> target:%s" % (src, dst),
                                attachments = dict(output = s))


    def copy_from(self, src, dst = ".", recursive = False,
                  nonzero_e = tc.error_e):
        """
        Copy a file or tree with *SCP* from the target to the client

        :param str src: remote file or directory to copy
        :param str dst: (optional) destination file or directory
          (defaults to current working directory)
        :param bool recursive: (optional) copy recursively (needed for
          directories)

        :param tcfl.tc.exception nonzero_e: exception to raise in case of 
          non zero exit code.  Must be a subclass of :class:`tcfl.tc.exception`
          (i.e.: :class:`tcfl.tc.failed_e`,  :class:`tcfl.tc.error_e`,
          :class:`tcfl.tc.skip_e`, :class:`tcfl.tc.blocked_e`) or
          *None* (default) to not raise anything and just return the
          exit code.

        """
        self._tunnel()
        self.target.report_info("running SCP target:%s -> local:%s"
                                % (src, dst), dlevel = 1)
        options = "-v"
        if recursive:
            options += "r"
        try:
            env = dict(os.environ)
            if self.password:
                cmdline = [ 'sshpass', "-e" ]
                env['SSHPASS'] = self.password
            else:
                cmdline = []
                options += "B"
            cmdline += \
                [ "scp", options, "-P", str(self._ssh_port) ] \
                + self._ssh_cmdline_options \
                + [ self.login + "@" + self._ssh_host + ":" + src, dst ]
            self.target.report_info("running SCP command: %s"
                                    % " ".join(cmdline), dlevel = 2)
            self._known_hosts_wipe()
            s = subprocess.check_output(cmdline, stderr = subprocess.STDOUT,
                                        shell = False, env = env,
                                        encoding = 'utf-8')
        except subprocess.CalledProcessError as e:
            self._returncode_eval(e.returncode)
            commonl.raise_from(nonzero_e(
                "failed SCP local:%s -> target:%s" % (src, dst),
                dict(returncode = e.returncode,
                     output = e.output,
                     src = src, dst = dst, recursive = recursive,
                     ssh_cmd = " ".join(e.cmd),
                     target = self.target
                )), e)
        self.target.report_info("ran SCP target:%s -> local:%s" % (src, dst),
                                attachments = dict(output = s))
