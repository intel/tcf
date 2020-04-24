#! /usr/bin/python
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
""".. _example_desktop_gedit:

Start Gedit and type Hello World
================================

Given a target that:

- can be provisioned with :ref:`Provisioning OS <pos_setup>` to a
  Linux GNOME desktop  (tested with Clear Workstation, see :ref:`image
  setup <ttbd_pos_deploying_images>`)

- can get its output captured (VMs can), otherwise you need an
  HDMI/camera capture card (FIXME: install guide)

this script will:

- provision the target

- wait for the Desktop to pop up, by looking for a tell tale icon (eg:
  the firefox icon) being displayed in the screen.

- press the left *Windows* key to bring up the desktop search, type
  *gedit* to launch a gedit window, wait for it to show up, click the
  mouse in the edit pane and type Hello World into it.


.. literalinclude:: /examples/test_desktop_gedit.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_desktop_gedit.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`) [output edited for clarity]::

  $ IMAGE=clear:desktop tcf run -vv /usr/share/tcf/examples/test_desktop_gedit.py
  INFO2/	toplevel @local [+0.5s]: scanning for test cases
  INFO1/e27x3t	.../test_desktop_gedit.py @lnss-eq2f [+0.4s]: will run on target group 'ic=jfsotc21/nwC target=jfsotc21/nuc-03C:x86_64' (PID 5499 / TID 7f52ae0ae580)
  PASS2/e27x3tD	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+164.1s]: deployed clear:desktop:32530::x86_64
  PASS2/e27x3t	.../test_desktop_gedit.py @lnss-eq2f [+164.3s]: deploy passed
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+168.6s]: power cycled
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+211.1s]: INPUT/evemu: TCF's static build w/ --fifo
  ...
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+235.7s]: 83.desktop_started/canary-icon-power_png: detected one match
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+239.6s]: 83.desktop_started/canary-icon-firefox_png: detected one match
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+239.7s]: serial0: wrote 98B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_LEFTMETA ...) to console
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+240.6s]: serial0: wrote 369B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_G 1<NL>WAIT ...) to console
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+241.3s]: serial0: wrote 92B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_ENTER 1<NL>W...) to console
  ...
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+247.8s]: 90.gedit_started/canary-gedit-1_png: detected one match
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+248.6s]: 90.gedit_started/canary-gedit-2_png: detected one match
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+249.2s]: 90.gedit_started/canary-gedit-start-bottom_png: detected 3 matches
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+516.4s]: mouse default_mouse: moving to (0.239785124388, 0.45688534279)
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+523.9s]: serial0: wrote 83B (cat > /tmp/evemu.data<NL>event11 EV_ABS ABS_X 15714<NL>e...) to console
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+524.7s]: mouse default_mouse: clicking at (0.239785124388, 0.45688534279)
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+524.7s]: serial0: wrote 95B (cat > /tmp/evemu.data<NL>event11 EV_KEY BTN_LEFT 1 SY...) to console
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+249.3s]: serial0: wrote 791B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_H 1<NL>WAIT ...) to console
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+250.1s]: serial0: wrote 60B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_LEFTSHIFT...) to console
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+250.9s]: serial0: wrote 84B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_1 1<NL>WAIT ...) to console
  INFO2/e27x3tE#1	.../test_desktop_gedit.py @lnss-eq2f|jfsotc21/nuc-03C [+251.6s]: serial0: wrote 60B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_LEFTSHIFT...) to console
  PASS1/e27x3t	.../test_desktop_gedit.py @lnss-eq2f [+253.6s]: evaluation passed
  PASS0/	toplevel @local [+255.0s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:04:13.870030) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""


import tcfl.tc
import tcfl.pos

@tcfl.tc.interconnect('ipv4_addr')
@tcfl.tc.target('pos_capable'
                ' and interfaces.capture.screen.type == "snapshot"')
class _test(tcfl.pos.tc_pos0_base):

    def eval(self, ic, target):
        ic.power.on()
        tcfl.tl.linux_wait_online(ic, target)
        tcfl.tl.sh_export_proxy(ic, target)

        # Setup the target for generic input event injection
        target.input.evemu_target_setup(ic)

        self.expect(
            target.capture.image_on_screenshot('canary-icon-power.png'),
            target.capture.image_on_screenshot('canary-icon-firefox.png'),
            name = "desktop started")

        # Launch terminal by pressing the left 'Windows' key, typing
        # 'terminal' and hitting enter
        target.input.kbd_key_press('KEY_LEFTMETA')
        # FIXME: wait for search icon to pop up at the top of the main screen
        target.input.kbd_string_send('gedit')
        target.input.kbd_key_press('KEY_ENTER')

        r = self.expect(
            target.capture.image_on_screenshot('canary-gedit-1.png'),
            target.capture.image_on_screenshot('canary-gedit-2.png'),
            target.capture.image_on_screenshot('canary-gedit-start-bottom.png'),
            name = "gedit started",
        )

        # click on the edit window and type hello world the
        # coordinates we got are basically squares on the on the left top
        # corner and the right top corner of the gedit window
        # so [0] is x0 [1] y0 -> [1] x, [2], y
        coord_tl = r['canary-gedit-1_png'].values()[0]['relative']
        # this is the bar at the bottom, we use it to move the mouse
        # down a wee bit on the edit area
        coord_bt = r['canary-gedit-start-bottom_png'].values()[0]['relative']

        target.input.mouse_click(
            (coord_tl[0] + coord_bt[0]) / 2,
            (coord_tl[1] + coord_bt[1]) / 2)

        target.input.kbd_string_send('Hello World')
        target.input.kbd_key_hold('KEY_LEFTSHIFT')
        target.input.kbd_key_press('KEY_1')
        target.input.kbd_key_release('KEY_LEFTSHIFT')

        target.capture.get("screen", self.report_file_prefix + "gedit.png")
