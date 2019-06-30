#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_deploy_files:

Send a file or directory tree during deployment to the target
=============================================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, send a directory tree to it during the deployment phase.

This allows to copy one or more files, directories etc to the target,
right after flashing the OS, so once the target is rebooted into the
provisioned OS, it is there. Note that the content itself is cached in
the target (in subdirectory */persistent.tcf.d*), so next time it is
transferred it will be faster (with sizeable files).

You can also send/receive files :class:`via SSH
<tcfl.target_ext_ssh.ssh>` once the target is running (:ref:`example
<example_ssh_in>`).

This also demonstrates a method to test if a local and remote files
are the same by using the MD5 sum.

.. literalinclude:: /examples/test_deploy_files.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_deploy_files.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=clear tcf run -v /usr/share/tcf/examples/test_deploy_files.py
  INFO1/ubio     .../test_deploy_files.py#_test @n6hi-da7e: will run on target group 'ic=server1/nwd target=server1/nuc-07d:x86_64'
  INFO1/ubioDPOS .../test_deploy_files.py#_test @n6hi-da7e|server1/nuc-07d: POS: rsyncing clear:desktop:30080::x86_64 from 192.168.100.1::images to /dev/sda4
  PASS1/ubio     .../test_deploy_files.py#_test @n6hi-da7e: deployed file is identical to local!
  PASS1/ubio     .../test_deploy_files.py#_test @n6hi-da7e: evaluation passed 
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:39.461709) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

where IMAGE is the name of a Linux OS image :ref:`installed in the
server <pos_list_images>`.

"""
import os
import subprocess

import tcfl.tc
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

    @tcfl.tc.serially()
    def deploy_00(self, target):
        # the format is still a wee bit pedestrian, we'll improve the
        # argument passing
        # This could be a single path not necessarily a list of them
        target.deploy_path_src = [
            # send a directory tree, the one containing this file
            self.kws['srcdir'],
            # send just a file, ../README.rst
            os.path.join(self.kws['srcdir'], "..", "README.rst")
        ]

        # note ending this in / will create a new entry under /home/,
        # otherwise it would overwrite /home
        target.deploy_path_dest = "/home/"
        self.deploy_image_args = dict(extra_deploy_fns = [
            tcfl.pos.deploy_path ])
	
    def eval(self, target):
        target.shell.run("ls -lR /home/examples")
        # verify the file exists and is the same
        remote = target.shell.run("md5sum < /home/examples/data/beep.wav",
                                  output = True, trim = True).strip()
        local = subprocess.check_output(
            "md5sum < %s" % self.kws['srcdir'] + "/data/beep.wav",
            shell = True).strip()
        if remote != local:
            raise tcfl.tc.failed_e("MD5 mismatch (local %s remote %s)"
                                   % (local, remote))
        self.report_pass("deployed file is identical to local!", level = 1)
