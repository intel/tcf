#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_pos_boot:

Boot a target in Provisioning mode
==================================

Given a target that supports Provisioning OS mode, boot it in said mode.

This allows to manipulate the target's filesystem, as the POS boots
off a filesystem in the network. 


.. literalinclude:: /examples/test_pos_boot.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_deploy_files.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ tcf run -vt "nwa or qu04a" /usr/share/tcf/examples/test_pos_boot.py
  $ tcf run -vt "nwa or qu04a" tcf.git/examples/test_pos_boot.py
  INFO1/rdgx	tcf.git/examples/test_pos_boot.py#_test @3hyt-uo3g: will run on target group 'ic=localhost/nwa target=localhost/qu04a:x86_64'
  PASS1/rdgx	tcf.git/examples/test_pos_boot.py#_test @3hyt-uo3g: evaluation passed 
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:36.773884) - passed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

Note if you add ``--no-release``, then you can login to the console
and manipulate the target; later you will have to manually release the
target and network::

  $ tcf run --no-release -vt "nwa or qu04a" tcf.git/examples/test_pos_boot.py
  INFO1/rdgx	tcf.git/examples/test_pos_boot.py#_test @3hyt-uo3g: will run on target group 'ic=localhost/nwa target=localhost/qu04a:x86_64'
  PASS1/rdgx	tcf.git/examples/test_pos_boot.py#_test @3hyt-uo3g: evaluation passed 
  INFO0/rdgx	tcf.git/examples/test_pos_boot.py#_test @3hyt-uo3g: WARNING!! not releasing targets
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:36.773884) - passed 

  $ tcf -t rdgx console-write -i qu04a
  WARNING: This is a very limited interactive console
           Escape character twice ^[^[ to exit
  ...
  My IP is 192.168.97.4
  TCF Network boot to Service OS
  Loading http://192.168.97.1/ttbd-pos/x86_64/vmlinuz-tcf-live... ok
  Loading http://192.168.97.1/ttbd-pos/x86_64/initramfs-tcf-live...ok
  ...
  
  TCF-rdgx: 4 $ ls -la
  ls -la
  total 28
  dr-xr-x---  2 root root 4096 Jan 10 11:56 .
  dr-xr-xr-x 18 root root 4096 Jan 10 11:58 ..
  -rw-r--r--  1 root root   18 Feb  9  2018 .bash_logout
  -rw-r--r--  1 root root  176 Feb  9  2018 .bash_profile
  -rw-r--r--  1 root root  176 Feb  9  2018 .bashrc
  -rw-r--r--  1 root root  100 Feb  9  2018 .cshrc
  -rw-r--r--  1 root root  129 Feb  9  2018 .tcshrc
  TCF-rdgx: 5 $ 
  ...

  $ tcf -t rdgx release nwa qu04a


"""

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect("ipv4_addr")
@tcfl.tc.target('pos_capable')
class _test(tcfl.tc.tc_c):
    """
    Boot a target to Provisioning OS
    """

    def eval(self, ic, target):
        ic.power.on()
        target.pos.boot_to_pos()

    def teardown(self):
        tcfl.tl.console_dump_on_failure(self)
