#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
.. _example_pos_base:

Quick way to deploy an OS image to a target and get a prompt
============================================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, deploy to it a given image, :ref:`installed in the
server <pos_list_images>`. Then power cycle into the installed OS.

This is a :class:`template <tcfl.pos.tc_pos_base>` when your testcase
*just needs a target*, with no frills and your evaluation wants a
prompt in a powered machine. In case of failures, errors or blockage,
the consoles will be dumped.

.. literalinclude:: /examples/test_pos_base.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_pos_base.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=clear tcf run -v /usr/share/tcf/examples/test_pos_base.py
  INFO1/hxgj	 .../test_pos_base.py#_test @sv3m-twgl: will run on target group 'ic=localhost/nwb target=localhost/qu06b:x86_64'
  INFO1/hxgjDPOS .../test_pos_base.py#_test @sv3m-twgl|localhost/qu06b: POS: rsyncing clear:desktop:29820::x86_64 from 192.168.98.1::images to /dev/sda5
  PASS1/hxgj	 .../test_pos_base.py#_test @sv3m-twgl: evaluation passed
  PASS0/	 toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:02:54.992824) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import tcfl.tc
import tcfl.tl
import tcfl.pos

class _test(tcfl.pos.tc_pos_base):
    """
    Provisiong a target, boot it, run a shell command
    """

    def eval(self, ic, target):
        target.shell.run("echo I booted", "I booted")
