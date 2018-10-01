#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import subprocess

import commonl
import tc

class ssh(tc.target_extension_c):
    """Extension to :py:class:`tcfl.tc.target_c` for targets that support
    SSH to run remote commands via SSH or copy files around.

    The target has to be set to accept password less login, either by:

    - disabling password for the target user (**DANGEROUS!!** use only
      on isolated targets)

    - storing SSH identities in SSH agents (FIXME: not implemented
      yet) and provisioning the keys via cloud-init or similar

    Use as:

    1. As described in :class:`IP tunnels
       <tcfl.target_ext_tunnel.tunnel>`, upon which this extension
       builds, this will only work with a target with IPv4/6
       connectivity, which means there has to be an interconnect
       powered on and reachable for the server.

       As well, the target has to export the *ssh_client*
       tag. :class:`Linux <conf_00_lib.tt_qemu_linux>` targets are
       configured by default to accept root login over SSH and declare
       *ssh_client*; e.g.::

         @tcfl.tc.interconnect("ipv4_addr")
         @tcfl.tc.target("linux and ssh_client")
         class _test(tcfl.tc.tc_c):

    2. ensure the interconnect is powered on before powering on the
       target; otherwise some targets won't acquire an IP configuration
       (as they will assume there is no interconnect); e.g.: on *start*::

         def start(self, ic, target):
             ic.power.cycle()
             target.power.cycle()
             target.shell.up()		# wait for target to power up

    2. indicate the tunneling system which IP address is to be
       used::

         [ ... on the start() function ... ]
             target.tunnel.ip_addr = target.addr_get(ic, "ipv4")

    3. Use SSH::

         exitcode = target.ssh.call("test -f file_that_should_exist")
         target.ssh.check_call("test -f file_that_should_exist")
         s = target.ssh.check_output("cat some_file")
         if 'what_im_looking_for' in s:
            do_something()
         target.ssh.copy_to("somedir/local.file", "remotedir")
         target.ssh.copy_from("someremotedir/file", "localdir")

    FIXME: provide pointers to a private key to use

    """

    def __init__(self, target):
        if target.rt.get('ssh_client', False) != True:
            raise self.unneeded
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
        #: SSH port to use
        self.port = 22

        # Port to where to connect in the server to reach the target's
        # SSH port.
        self._ssh_port = None
        self._ssh_host = None

        self._ssh_cmdline_options = [
            "-q",
            "-o", "BatchMode yes",
            "-o", "StrictHostKeyChecking no",
        ]

    def _tunnel(self):
        # Ensure the IP tunnel is up, overriding whatever was there
        # before
        if self._ssh_port != None and self._ssh_host != None:
            return
        target = self.target
        self._ssh_host = target.rtb.parsed_url.hostname
        self._ssh_port = target.tunnel.add(self.port)

    def call(self, cmd):
        """
        Run a shell command over SSH, substituting any %(KEYWORD)[ds]
        field from the target's keywords in
        :attr:`tcfl.tc.target_c.kws`

        Similar to :func:`subprocess.call`

        :param str cmd: shell command to execute via SSH
        :returns: exitcode

        """
        self._tunnel()
        _cmd = cmd % self.target.kws
        self.target.report_info("running SSH command '%s'" % _cmd, dlevel = 2)
        r = subprocess.call(
            [ "/usr/bin/ssh", "-p", "%s" % self._ssh_port ]
            + self._ssh_cmdline_options
            + [ self.login + "@" + self._ssh_host, "-t", _cmd])
        self.target.report_info("ran SSH command '%s': %d" % (_cmd, r),
                                dlevel = 1)
        return r

    @staticmethod
    def _result_e(result):
        if result == 'fail':
            exception = tc.failed_e
        elif result == 'errr':
            exception = tc.error_e
        elif result == 'skip':
            exception = tc.skip_e
        elif result == 'blck':
            exception = tc.blocked_e
        else:
            raise AssertionError("unknown result '%s': "
                                 "expected errr, fail, skip, blck" % result)
        return exception

    def check_call(self, cmd, result_on_failure = "errr"):
        """
        Run a shell command over SSH, substituting any %(KEYWORD)[ds]
        field from the target's keywords in
        :attr:`tcfl.tc.target_c.kws`

        Similar to :func:`subprocess.check_call`

        :param str cmd: shell command to execute via SSH
        :param str result_on_failure: (optional) how shall a failure
          considered to be (errr|fail|blck|skip).
        :returns: exitcode
        """
        exc = self._result_e(result_on_failure)
        self._tunnel()
        _cmd = cmd % self.target.kws
        self.target.report_info("running SSH '%s'" % _cmd, dlevel = 2)
        try:
            r = subprocess.check_call(
                ["/usr/bin/ssh", "-p", "%s" % self._ssh_port]
                + self._ssh_cmdline_options
                + [ self.login + "@" + self._ssh_host, "-t", _cmd ])
        except subprocess.CalledProcessError as e:
            commonl.raise_from(exc("ssh command failed: %s" % cmd,
                                   dict(output = e.output,
                                        ssh_cmd = " ".join(e.cmd),
                                        cmd = cmd)), e)
        self.target.report_info("ran SSH command '%s': %s" % (_cmd, r),
                                dlevel = 1)
        return r

    def check_output(self, cmd, result_on_failure = "errr"):
        """
        Run a shell command over SSH, substituting any %(KEYWORD)[ds]
        field from the target's keywords in
        :attr:`tcfl.tc.target_c.kws`

        Similar to :func:`subprocess.check_output`

        :param str cmd: shell command to execute via SSH
        :param str result_on_failure: (optional) how shall a failure
          considered to be (errr|fail|blck|skip).
        :returns: exitcode
        """
        exc = self._result_e(result_on_failure)
        self._tunnel()
        _cmd = cmd % self.target.kws
        self.target.report_info("running SSH command '%s'" % _cmd, dlevel = 2)
        try:
            s = subprocess.check_output(
                [ "/usr/bin/ssh", "-p", "%s" % self._ssh_port ]
                + self._ssh_cmdline_options
                + [ self.login + "@" + self._ssh_host, "-t", _cmd ],
                stderr = subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            commonl.raise_from(exc("ssh command failed: %s" % cmd,
                                   dict(output = e.output,
                                        ssh_cmd = " ".join(e.cmd),
                                        cmd = cmd)), e)
        self.target.report_info("ran SSH command '%s': %s" % (_cmd, s),
                                dlevel = 1)
        return s

    def copy_to(self, src, dst = "", recursive = False,
                result_on_failure = "errr"):
        """
        Copy a file or tree with *SCP* to the target from the client

        :param str src: local file or directory to copy
        :param str dst: (optional) destination file or directoy
          (defaults to root's home directory)
        :param bool recursive: (optional) copy recursively (needed for
          directories)
        :param str result_on_failure: (optional) how shall a failure
          considered to be (errr|fail|blck|skip).
        """
        exc = self._result_e(result_on_failure)
        self._tunnel()
        self.target.report_info("running SCP %s %s" % (src, dst), dlevel = 2)
        options = "-vB"
        if recursive:
            options += "r"
        try:
            s = subprocess.check_output(
                [ "/usr/bin/scp", options, "-P", "%s" % self._ssh_port ]
                + self._ssh_cmdline_options
                + [ src, self.login + "@" + self._ssh_host + ":" + dst ],
                stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            commonl.raise_from(exc("scp to '%s' -> '%s' failed"
                                   % (src, dst),
                                   dict(output = e.output, src = src,
                                        dst = dst,
                                        recursive = recursive,
                                        ssh_cmd = " ".join(e.cmd))), e)
        self.target.report_info("ran SCP %s %s" % (src, dst), dlevel = 1)
        return s


    def copy_from(self, src, dst = ".", recursive = False,
                  result_on_failure = "errr"):
        """
        Copy a file or tree with *SCP* from the target to the client

        :param str src: remote file or directory to copy
        :param str dst: (optional) destination file or directory
          (defaults to current working directory)
        :param bool recursive: (optional) copy recursively (needed for
          directories)
        :param str result_on_failure: (optional) how shall a failure
          considered to be (errr|fail|blck|skip).
        """
        exc = self._result_e(result_on_failure)
        self._tunnel()
        self.target.report_info("running SCP %s %s" % (src, dst), dlevel = 2)
        options = "-vB"
        if recursive:
            options += "r"
        try:
            s = subprocess.check_output(
                [ "/usr/bin/scp", options, "-P", "%s" % self._ssh_port ]
                + self._ssh_cmdline_options
                + [self.login + "@" + self._ssh_host + ":" + src, dst ])
        except subprocess.CalledProcessError as e:
            commonl.raise_from(exc("scp from '%s' -> '%s' failed"
                                   % (dst, src),
                                   dict(output = e.output, src = src,
                                        dst = dst,
                                        recursive = recursive,
                                        ssh_cmd = " ".join(e.cmd))), e)
        self.target.report_info("ran SCP '%s' -> '%s'" % (src, dst),
                                dlevel = 1)
        return s
