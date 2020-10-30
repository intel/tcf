#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
""".. _example_desktop_firefox_wikipedia:

Start Firefox and send it to wikipedia.org using keyboard and mouse
===================================================================

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
  *terminal* to launch a terminal window and press the keyboard keys
  needed to configure the proxy with *gsettings* (note this does not
  use the serial console, but it is typing in the Desktop's terminal
  app).

- click on the *Firefox* icon to start it and wait for it to appear

- move the mouse to the location bar and type *wikipedia.com*,
  pressing enter

- wait for the Wikipedia banner to be displayed

In the meantime, videos and screenshots will be recorded as collateral
(VMs so far can't record videos).


.. literalinclude:: /examples/test_desktop_firefox_wikipedia.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_desktop_firefox_wikipedia.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`) [output edited for clarity]::

  $ IMAGE=clear:desktop tcf run -vv /usr/share/tcf/examples/test_desktop_firefox_wikipedia.py
  INFO2/	toplevel @local [+0.5s]: scanning for test cases
  INFO1/jqmg46	.../test_desktop_firefox_wikipedia.py @lnss-eq2f [+0.4s]: will run on target group 'ic=jfsotc21/nwC target=jfsotc21/nuc-03C:x86_64' (PID 4987 / TID 7f0b03dca580)
  PASS2/jqmg46D	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+164.6s]: deployed clear:desktop:32530::x86_64
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nwC [+164.8s]: powered on
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+169.1s]: power cycled
  ...
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+214.2s]: tcp tunnel added from jfsotc21.jf.intel.com:5062 to 192.168.67.3:22
  ...
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+217.0s]: INPUT/evemu: TCF's static build w/ --fifo
  ...
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+229.8s]: 50.desktop_start/canary-icon-firefox_png: detected one match
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+230.0s]: serial0: wrote 98B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_LEFTMETA ...) to console
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+231.6s]: serial0: wrote 92B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_ENTER 1<NL>W...) to console
  ...
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+235.9s]: 57.terminal_window_pops_up/canary-close-window-button_png: detected 4 matches
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+239.4s]: 57.terminal_window_pops_up/canary-terminal_png: detected one match
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+239.5s]: mouse default_mouse: moving to (0.5, 0.5)
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+239.6s]: serial0: wrote 83B (cat > /tmp/evemu.data<NL>event11 EV_ABS ABS_X 32768<NL>e...) to console
  ...
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+243.1s]: mouse default_mouse: moving to (0.7, 0.7)
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+253.4s]: serial0: wrote 92B (cat > /tmp/evemu.data<NL>event12 EV_KEY KEY_ENTER 1<NL>W...) to console
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+254.1s]: mouse default_mouse: moving to (0.0158854166667, 0.572222222222)
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+254.2s]: serial0: wrote 82B (cat > /tmp/evemu.data<NL>event11 EV_ABS ABS_X 1041<NL>ev...) to console
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+254.9s]: mouse default_mouse: clicking at (0.0158854166667, 0.572222222222)
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+255.0s]: serial0: wrote 176B (cat > /tmp/evemu.data<NL>event11 EV_KEY BTN_LEFT 1 SY...) to console
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+268.0s]: 96.firefox_started/canary-firefox-reload_home_png: detected one match
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+271.3s]: 96.firefox_started/canary-close-window-button_png: detected 7 matches
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+272.1s]: 96.firefox_started/canary-firefox-bookmarks_settings_png: detected one match
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+272.2s]: mouse default_mouse: moving to (0.334635416667, 0.108333333333)
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+273.1s]: mouse default_mouse: clicking at (0.334635416667, 0.108333333333)
  INFO2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f|jfsotc21/nuc-03C [+288.1s]: 105.wikipedia_loaded/canary-web-wikipedia_org_png: detected one match
  PASS2/jqmg46E#1	.../test_desktop_firefox_wikipedia.py @lnss-eq2f [+288.2s]: Firefox launches and can load wikipedia
  PASS1/jqmg46	.../test_desktop_firefox_wikipedia.py @lnss-eq2f [+288.2s]: evaluation passed
  PASS0/	toplevel @local [+289.6s]: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:04:48.431436) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import os
import urllib.parse
import time

import tcfl.pos

@tcfl.tc.interconnect('ipv4_addr',
                      mode = os.environ.get('MODE', 'one-per-type'))
@tcfl.tc.target('pos_capable'
                ' and interfaces.capture.screen.type == "snapshot"')
class _test(tcfl.pos.tc_pos0_base):

    def eval(self, target, ic):
        ic.power.on()
        tcfl.tl.linux_wait_online(ic, target)
        tcfl.tl.linux_ssh_root_nopwd(target)
        tcfl.tl.linux_sshd_restart(ic, target)
        target.console.select_preferred(user = self.login_user)

        # done with ANSI colored prompts and sequences
        target.shell.run(r"export PS1='TCF-%(tc_hash)s \u:\w \$ '" % self.kws)
        tcfl.tl.sh_export_proxy(ic, target)

        # Do we need a proxy? extract it
        if 'http_proxy' in ic.kws:
            self.proxy_url = urllib.parse.urlparse(ic.kws['http_proxy'])
        else:
            self.proxy_url = None

        target.input.evemu_target_setup(ic)

        r_desktop = self.expect(
            # this assumes we are auto-login in to a GNOME desktop in English
            target.capture.image_on_screenshot('canary-icon-power.png',
                                               in_area = ( 0.80, 0, 1, 0.20 )),
            target.capture.image_on_screenshot('canary-activities.png'),
            name = "desktop start")

        target.input.image_click(r_desktop['canary-activities_png'])

        r_desktop = self.expect(
            # this assumes we are auto-login in to a GNOME desktop in English
            target.capture.image_on_screenshot('canary-icon-firegox.png',
                                               in_area = ( 0.80, 0, 1, 0.20 )),
            name = "desktop start")

        movie = 'interfaces.capture.screen_stream' in target.kws
        if movie:
            target.capture.start("screen_stream")

        # Launch terminal by pressing the left 'Windows' key, typing
        # 'terminal' and hitting enter
        target.input.kbd_key_press('KEY_LEFTMETA')
        # FIXME: wait for search icon to pop up at the top of the main screen
        target.input.kbd_string_send('terminal')
        target.input.kbd_key_press('KEY_ENTER')

        if movie:
            target.capture.stop_and_get(
                "screen_stream", self.report_file_prefix + "desktop-0.avi")

        r_terminal = self.expect(	# wait for terminal to pop up
            target.capture.image_on_screenshot('canary-close-window-button.png'),
            target.capture.image_on_screenshot('canary-terminal.png'),
            name = "terminal window pops up")

        if movie:
            target.capture.start("screen_stream")

        # Configure proxy in the desktop by typing commands in the terminal
        if self.proxy_url:
            target.input.mouse_move_to(0.5, 0.5)
            target.input.kbd_string_send('gsettings set org.gnome.system.proxy.http host ')
            target.input.kbd_string_send(self.proxy_url.hostname)
            target.input.kbd_key_press('KEY_ENTER')
            target.input.mouse_move_to(0.7, 0.7)
            target.input.kbd_string_send('gsettings set org.gnome.system.proxy.http port ')
            target.input.kbd_string_send(str(self.proxy_url.port))
            target.input.kbd_key_press('KEY_ENTER')

            # Send: gsettings set org.gnome.system.proxy mode 'manual'
            target.input.kbd_string_send('gsettings set org.gnome.system.proxy mode ')
            target.input.kbd_key_hold('KEY_LEFTSHIFT')
            target.input.kbd_key_press('KEY_APOSTROPHE')
            target.input.kbd_key_release('KEY_LEFTSHIFT')
            target.input.kbd_string_send('manual')
            target.input.kbd_key_hold('KEY_LEFTSHIFT')
            target.input.kbd_key_press('KEY_APOSTROPHE')
            target.input.kbd_key_release('KEY_LEFTSHIFT')
            target.input.kbd_key_press('KEY_ENTER')

        # when we waited for the desktop to pop, we were looking for
        # the Firefox icon; now click on it to start firefox
        target.input.image_click(r_desktop['canary-icon-firefox_png'],
                                 times = 2)

        if movie:
            target.capture.stop_and_get(
                "screen_stream", self.report_file_prefix + "desktop-1.avi")

        r_firefox = self.expect(	# wait for firefox to pop up
            target.capture.image_on_screenshot('canary-firefox-reload+home.png'),
            target.capture.image_on_screenshot('canary-close-window-button.png'),
            target.capture.image_on_screenshot('canary-firefox-bookmarks+settings.png'),
            name = "firefox started")

        if movie:
            target.capture.start("screen_stream")

        # The location bar is kinda hard to detect, because depending
        # on the phases of the moon and something else random, it
        # might show different icons.
        #
        # So because it is always set between the RELOAD/HOME butons
        # (to the left) and the BOOKMARKS/SETTINGS buttons (to the
        # right), we use the midde of those as the location to click into:

        d_reload = r_firefox['canary-firefox-reload_home_png']
        coord_reload = d_reload.values()[0]['relative']
        d_settings = r_firefox['canary-firefox-bookmarks_settings_png']
        coord_settings = d_settings.values()[0]['relative']
        x = (coord_reload[2] + coord_settings[0]) / 2
        y = (coord_reload[1] + coord_settings[3]) / 2
        target.input.mouse_click(x, y, times = 3)

        # we have clicked in the location bar, so it has focus, so
        # then launch wikipedia webpage by typing the URL and enter
        target.input.kbd_string_send('wikipedia.com')
        target.input.kbd_key_press('KEY_ENTER')

        if movie:
            time.sleep(5)	# give some time so we capture the page loading
            target.capture.stop_and_get(
                "screen_stream", self.report_file_prefix + "desktop-2.avi")

        # wait for wikipedia to load by looking for wikipedia's icon to
        # pop up in the screen
        r_wikipedia = self.expect(
            target.capture.image_on_screenshot('canary-web-wikipedia.org.png'),
            name = "wikipedia loaded")

        self.report_pass("Firefox launches and can load wikipedia")
