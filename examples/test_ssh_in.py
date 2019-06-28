#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Enabling target's SSH server and executing an SSH command
==========================================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, execute a command with SSH.

This allows to login via SSH, copy and rsync files around, etc.

.. literalinclude:: /examples/test_deploy_files.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_ssh_in.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=clear  tcf run -Dvvvt 'nwa or qu04a' tcf.git/examples/test_ssh_in.py
  INFO1/l79r	.../test_ssh_in.py#_test @zsqj-uwny: will run on target group 'ic=SERVER/nwa target=SERVER/qu04a:x86_64'
  PASS1/l79r	.../test_ssh_in.py#_test @zsqj-uwny: evaluation passed 
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:42.127021) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

Note that once you have enabled the SSH server, you can use in the
script the functions enabled by the :class:`target.ssh
<tcfl.target_ext_ssh.ssh>` interface. As well, as long as the
*target* and the *network* are on, you can create a tunnel through the
server to access remotely::

  $ tcf acquire nwa qu04a
  $ tcf power-on nwa qu04a

Find the IPv4 address::

  $ tcf tcf list -vv qu04a | grep ipv4_addr
  interconnects.nwa.ipv4_addr: 192.168.97.4

Establish a tunnel to the SSH port::

  $ tcf tunnel-add qu04a 22 tcp 192.168.97.4
  SERVERNAME:20250

SSH into the target::

  $ ssh -p 20250 root@SERVERNAME
  ...

Similarly *scp -P 20250 root@SERVERNAME:REMOTEFILE .* or *rsync* over
SSH.

Learn more about tunnels :ref:`here <tunnels_linux_ssh>`.

"""
import os
import subprocess

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.tags(ignore_example = True)
@tcfl.tc.interconnect('ipv4_addr')
@tcfl.tc.target("pos_capable")
class _test(tcfl.pos.tc_pos0_base):
    """
    Deploy files after installing OS
    """
    image_requested = os.environ.get("IMAGE", 'clear:desktop')
    login_user = os.environ.get('LOGIN_USER', 'root')

    def eval(self, target):
        # enable root login, passwordless login
        tcfl.tl.linux_ssh_root_nopwd(target)
        target.shell.run("systemctl restart sshd")
        
        output = target.shell.run("echo hello",
                                  output = True, trim = True).strip()
        if output != "hello":
            raise tcfl.tc.failed_e("didn't get hello but '%s'" % output)
