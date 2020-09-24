#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_pos_ssh_enable:

Deploy an OS, enable SSH daemon so root can login and get a prompt
==================================================================

Images are usually shipped with the root password disabled.

These use convenience functions :func:tcfl.tl.linux_ssh_root_nopwd and
:func:tcfl.tl.linux_sshd_restart.

Building on :ref:`example_pos_base`, given a target that can be
provisioned with :ref:`Provisioning OS <pos_setup>`, deploy to it a
given image, :ref:`installed in the server <pos_list_images>`. Then
power cycle into the installed OS.

.. literalinclude:: /examples/test_pos_ssh_enable.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_pos_ssh_enable.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=clear tcf run -v /usr/share/tcf/examples/test_ssh_enable.py
  INFO1/hxgj	 .../test_ssh_enable.py#_test @sv3m-twgl: will run on target group 'ic=localhost/nwb target=localhost/qu06b:x86_64'
  INFO1/hxgjDPOS .../test_ssh_enable.py#_test @sv3m-twgl|localhost/qu06b: POS: rsyncing clear:desktop:29820::x86_64 from 192.168.98.1::images to /dev/sda5
  PASS1/hxgj	 .../test_ssh_enable.py#_test @sv3m-twgl: evaluation passed
  PASS0/	 toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:02:54.992824) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

If you add to *tcf run* the *--no-release* command line option, when
done it will not be released so the user can take control of it
using::

  $ tcf console-write -i TARGETNAME

or you can create a :ref:`tunnel <tunnels_linux_ssh>` and SSH into it::

  $ tcf tunnel-add TARGETNAME 22
  SERVERNAME:19893
  $ ssh -p 19893 root@SERVERNAME

when you access via the network, the server does not know you are
using the target, so it migh idle it and remove it from you. To keep
the allocation :ref:`alive in another console
<howto_target_keep_acquired>`:

- find the allocation ID with *tcf ls -v*::

     $ tcf ls -v TARGETNAME
     SERVER/TARGETNAME [USERNAME:b2Bkhb]

  the allocation ID is *b2Bkhb* in this case, next to *USERNAME*

- keep it alive using *tcf acquire... --hold* and the allocation ID
  just found::

    $ tcf -a b2Bkhb acquire TARGETNAME --hold

"""

import tcfl.tc
import tcfl.tl
import tcfl.pos

class _test(tcfl.pos.tc_pos_base):
    """
    Provisiong a target, boot it, run a shell command
    """

    def eval(self, ic, target):
        # these functions are a convenience from the library an will
        # add configuration to allow root login with no password and
        # then restart SSHd.
        tcfl.tl.linux_ssh_root_nopwd(target)
        tcfl.tl.linux_sshd_restart(ic, target)
        target.report_info(
            "SSH configured to allow logins from root with no password")
