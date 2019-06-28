#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Send a file during deployment to the target
===========================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, send a file to it during the deployment phase.

This allows to send test content to the target right after flashing
the OS, so once the target is rebooted into the provisioned OS, the
test the content is there.

Note that the content itself is cached in the target (in a
subdirectory of the root filesystem), so next time it is transferred
it will be faster (with sizeable files).

This also demonstrates a method to test if a local and remote files
are the same by using the MD5 sum.

.. literalinclude:: /examples/test_deploy_files.py
   :language: python
   :pyobject: _test

Execute with::

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
        target.deploy_path_src = self.kws['srcdir'] + "/data/beep.wav"
        target.deploy_path_dest = "/home/"
        self.deploy_image_args = dict(extra_deploy_fns = [
            tcfl.pos.deploy_path ])
	
    def eval(self, target):
        # verify the file exists and is the same
        remote = target.shell.run("md5sum < /home/beep.wav",
                                  output = True, trim = True).strip()
        local = subprocess.check_output(
            "md5sum < %s" % self.kws['srcdir'] + "/data/beep.wav",
            shell = True).strip()
        if remote != local:
            raise tcfl.tc.failed_e("MD5 mismatch (local %s remote %s)"
                                   % (local, remote))
        self.report_pass("deployed file is identical to local!", level = 1)
