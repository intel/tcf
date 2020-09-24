#! /usr/bin/python
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_pos0_base:

Quick way to deploy an OS image to an specific target and get a prompt
======================================================================

Given a target that can be provisioned with :ref:`Provisioning OS
<pos_setup>`, deploy to it a given image, :ref:`installed in the
server <pos_list_images>`. Then power cycle into the installed OS.

This is a :class:`template <tcfl.pos.tc_pos0_base>` when your testcase
just needs to flash a given target and you need control over that
target selection process. Otherwise is the same as :ref:`tc_pos_base
<example_pos_base>`.

The selection is controlled by the decorators
:func:`tcfl.tc.interconnect` (to request a network) and
:func:`tcfl.tc.target` (to request a target):

.. code-block:: python

   @tcfl.tc.interconnect('ipv4_addr', mode = 'all')
   @tcfl.tc.target('pos_capable and ic.id in interconnects '
                   'and capture:"screen:snapshot"')
   class _test(tcfl.pos.tc_pos0_base):
       ...

the filtering values come from the metadata exposed by the target,
which can be seen with *tcf list -vv TARGETNAME** and available to the
script in *target.kws* or *ic.kws* (see :ref:`here
<tcf_evaluation_expressions>` for more information). In this case:

 - select a network or interconnect (by default called *ic*) that
   exposes an IPv4 address, which by convention means it implements
   IPv4 networking

 - select a target that:

   - can be provisioned with Provisioning OS (*pos_capable*)

   - is connected to the interconnect (*ic.id in interconnects*
     indicates the target declares the network in the list of networks
     it is connected to; see the output of *tcf list -vv TARGETNAME |
     grep interconnects*)

   - exposes a capture interface to get screenshots from the screen;
     the colon ``:`` after *capture* acts as a regex operator; see::

       $ tcf list -vv capture | grep -w -e id: -e capture:*
        id: qu04a
        capture: vnc0:snapshot:image/png screen:snapshot:image/png
        id: qu04b
        capture: vnc0:snapshot:image/png screen:snapshot:image/png
        ...

.. literalinclude:: /examples/test_pos0_base.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_pos0_base.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=clear tcf run -v /usr/share/tcf/examples/test_pos0_base.py
  INFO1/yios	 .../test_pos0_base.py#_test @sv3m-twgl: will run on target group 'ic=localhost/nwb target=localhost/qu06b:x86_64'
  INFO1/yiosDPOS .../test_pos0_base.py#_test @sv3m-twgl|localhost/qu06b: POS: rsyncing clear:desktop:29820::x86_64 from 192.168.98.1::images to /dev/sda5
  PASS1/yios	 .../test_pos0_base.py#_test @sv3m-twgl: evaluation passed
  PASS0/	 toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:01:51.845546) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import os

import tcfl.tc
import tcfl.tl
import tcfl.pos

@tcfl.tc.interconnect('ipv4_addr', mode = os.environ.get('MODE', 'all'))
@tcfl.tc.target('pos_capable and ic.id in interconnects')
                # For example, it could add
                # ' and interfaces.capture.screen.type == "snapshot"')
class _test(tcfl.pos.tc_pos0_base):
    """
    Provisiong a target, boot it, run a shell command
    """

    def eval(self, ic, target):
        target.shell.run("echo I booted", "I booted")
