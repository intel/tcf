#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Reproducing audio and capturing the output
==========================================

Given a target from which we can record audio, play a beep sound,
record it, and then compare with the original

The target selection for this test is any target that can be
provisioned with :ref:`Provisioning OS <pos_setup>` and supports
capture of audio over capturer called *front_astream*, which is
usually connected to the front audio output of the target.

The :download:`sound file <../examples/data/beep.wav>` is a beep,
located in the *examples/data* subdirectory and is sent to the
target during the deployment phase, after flashing the image.

When the OS boots, the *beep.wav* file is already in */home*,
ready to be played. The test starts recording the target's audio
output, plays the *beep*, and then downloads the recording.

.. literalinclude:: /examples/test_audio_capture.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_audio_capture.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=clear tcf run -vv /usr/share/tcf/examples/test_audio_capture.py

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

where IMAGE is the name of a Linux OS image :ref:`installed in the
server <pos_list_images>`.

"""
import os

import tcfl.tc
import tcfl.pos

@tcfl.tc.tags(ignore_example = True)
@tcfl.tc.interconnect('ipv4_addr', mode = 'all')
@tcfl.tc.target('pos_capable'
                ' and interfaces.capture.front_astream.type == "stream"'
                ' and ic.id in interconnects')
class _test(tcfl.pos.tc_pos0_base):
    """
    Simple audio test

    Play a beep while capturing the audio output, ensure they match
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
        target.capture.start("front_astream")
        target.shell.run("aplay -D front /home/beep.wav" )
        target.capture.get("front_astream",
                           self.report_file_prefix + "capture.wav")
        # here you would compare with some audio analysis tool:
        # - self.kws['srcdir'] + "/data/beep.wav"
        # - self.report_file_prefix + "capture.wav"
        # and if they are very different, raise a failure
