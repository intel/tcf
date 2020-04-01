#! /usr/bin/python2
#
# Copyright (c) 2019-20 Intel Corporation
#
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME:
#
# - make it run in fedora/ubuntu/cleardesktop
#
# - move to driver model
#
#
"""Send input (keyboard, mouse, etc) to targets
--------------------------------------------

This exposes APIs to send keyboard presses, mouse movements, etc as
defined by the USB HID specification.

Supported implementations:

- evemu: injects events into Linux input layer with *evemu* package

Please see each driver for the intrinsic limitations they suffer.

*evemu  driver*
^^^^^^^^^^^^^^^

This driver injects input events directly into the Linux input layer
by creating a fake input device with *evemu-device* and then injecting
input events into it with *evemu-event*.

This allows running on any Linux system without any hardware
instrumentation, being able to emulate any input device supported by Linux.

*Requirements*:

- linux kernel supports the *uinput* driver/module

- *evemu* utility installed and available in path (FIXME: support
  uploading static copy)

  Requires a working Linux system with /dev/input
  support and to install the evemu package.

  Continuously uses a console to inject the commands

- Requires the mouse device to support absolute coordinates


What can be sent to devices?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This driver uses as reference standard what *evemu* can do, as it is
believed to be the most complete platform-independent input device
reference. This in turn is using the input event codes from the Linux
kernel; a summary from the  :ref:`libevdev's authoritative
<https://github.com/freedesktop/libevdev/blob/master/include/linux/input-event-codes.h>`:

- Event types (EV_*):

  - *EV_KEY*: press a key (eg: keyboard)
  - *EV_REL*: relative movement (eg: mouse)
  - *EV_ABS*: absolute movement (eg: touchpad)

- Keys and buttons (KEY_*, BTN_*):

  - *KEY_A*, *KEY_B*...: press *a*, press *b*...note this depends on the
    keyboard, thus why there is no *KEY_DOUBLEQUOTE* because you have
    to press and hold *KEY_LEFTSHIFT*, then press *KEY_APOSTROPHE*,
    then release *KEY_LEFTSHIFT*

  - *BTN_LEFT*, *BTN_MIDDLE*, *BTN_RIGHT*...: mouse buttons

- Mouse and controller axes:

  - *ABS_X*, *ABS_Y*, *ABS_Z*...: depending on the device, which
    defines a range of value, where each axes location is

  - *REL_X*, *REL_Y*, *REL_Z*...: depending on the device, which
    defines a range of value, on how much each axes has to move

this is not intended to be a comple guide, which would be completely
out of scope. Please refer to the reference given above.

"""

import numbers
import os
import re

import tc

from . import msgid_c

# Validate an evemu input device descriptor, as described in
# https://github.com/freedesktop/evemu#device-description-format
descriptor_valid_regex = re.compile(
    r"^# EVEMU 1\.3\n"
    r"N: .*\n"
    r"I:( [0-9a-fA-F]{4}){4}\n"
    r"P:( [0-9a-fA-F]{2}){8}\n"
    # BUTTON: a bunch of fieds of hex bytes
    r"(B:( [0-9a-fA-F]{2})+\s*$)*"
    # AXIS: six fields of hex / integer
    r"(A:( [0-9a-fA-F]+){6}\s*$)*"
    # LED: two fields hex / integer
    r"(L:( [0-9a-fA-F]+){2}\s*$)*"
    # SWITCH: two fields hex / integer
    r"(L:( [0-9a-fA-F]+){2}\s*$)*"
)


#:
#: Default keyboard descriptor
#:
#: To use a descriptor specifc to a device you care for, use
#: evemu-describe to extract it and pass it to
descriptor_kbd = """
# EVEMU 1.3
N: Generic Keyboard
I: 0003 1d6b ff0f 0001
P: 00 00 00 00 00 00 00 00
B: 00 0b 00 00 00 00 00 00 00
B: 01 fe ff ff ff ff ff ff ff
B: 01 ff ff ef ff df ff be fe
B: 01 ff 57 40 c1 7a 20 9f ff
B: 01 07 00 00 00 00 00 01 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 02 00 00 00 00 00 00 00 00
B: 03 00 00 00 00 00 00 00 00
B: 04 10 00 00 00 00 00 00 00
B: 05 00 00 00 00 00 00 00 00
B: 11 1f 00 00 00 00 00 00 00
B: 12 00 00 00 00 00 00 00 00
B: 14 03 00 00 00 00 00 00 00
B: 15 00 00 00 00 00 00 00 00
B: 15 00 00 00 00 00 00 00 00
"""

#: Default mouse descriptor (touchpad)
#:
#: This is an absolute mouse whose axes go from 0 to 65535;
#: note we are making that assumption in mouse_move_to()
descriptor_mouse = """
# EVEMU 1.3
N: Generic Mouse
I: 0003 1d6b ff0e 0001
P: 00 00 00 00 00 00 00 00
B: 00 0b 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 07 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 01 00 00 00 00 00 00 00 00
B: 02 00 00 00 00 00 00 00 00
B: 03 03 00 00 00 00 00 00 00
B: 04 00 00 00 00 00 00 00 00
B: 05 00 00 00 00 00 00 00 00
B: 11 00 00 00 00 00 00 00 00
B: 12 00 00 00 00 00 00 00 00
B: 14 00 00 00 00 00 00 00 00
B: 15 00 00 00 00 00 00 00 00
B: 15 00 00 00 00 00 00 00 00
A: 00 0 65535 0 0 0
A: 01 0 65535 0 0 0
"""


class extension(tc.target_extension_c):

    def __init__(self, target):
        tc.target_extension_c.__init__(self, target)
        self.devices = {}

        # EVEMU driver
        self.evemu_event = None
        self.evemu_event_fifo = None
        self.evemu_device = None

    def evemu_create_device(self, did, descriptor):
        """
        Create a new input device

        :param str did: device id, or name of the device (eg: *mouse
          1*, *keyboard main*, *left joytick*...)

        :param str descriptor: input device descriptor, as described
          by Linux's *evemu-describe* (without the comments); see
          :const:`descriptor_mouse`, :const:`descriptor_kbd`.
        """
        # we'll evolve this into being able to create multiple mice of
        # different implementations (eg: evemu based vs hardware
        # based)...because we might want to type working with multiple mice
        assert isinstance(did, basestring), \
            "did is type %s; expected string" % type(did)
        descriptor = descriptor.strip()
        if not isinstance(did, basestring) \
            or not descriptor_valid_regex.search(descriptor.strip()):
            raise tc.error_e(
                "did %s: descriptor (%s) is not a string or it does not"
                " match the expected format in"
                " tcfl.target_ext_input.descriptor_valid_regex"
                % (did, type(descriptor)), dict(descriptor = descriptor))

        target = self.target
        # Copy the device descriptor to the device, using SSH if
        # possible (faster)
        if hasattr(target, 'ssh') and target.ssh.tunnel_up():
            with open(os.path.join(target.testcase.tmpdir,
                                   "input-dev.desc"), "w") as f:
                f.write(descriptor)
                f.flush()
                target.ssh.copy_to(f.name, "/tmp/input-dev.desc")
        else:
            target.shell.string_copy_to_file(descriptor, "/tmp/input-dev.desc")
        output = target.shell.run(
            "%s /tmp/input-dev.desc & sleep 1s" % self.evemu_device,
            output = True, trim = True)
        # this prints
        ## NAME: /dev/input/eventX, so get it
        input_regex = re.compile(
            r"(?P<name>[^:]+\s*)(?P<devname>\/dev\/input\/event.*)$")
        m = input_regex.search(output)
        if not m:
            raise tc.error_e(
                "can't locate /dev/input/event* name in output to"
                " create new input device", dict(output = output))
        # take only the basename; /dev/input will be added by the FIFO
        # itself, it is less chars to print
        self.devices[did] = os.path.basename(m.groupdict()['devname'])


    def evemu_target_setup(self, ic):
        """
        Setup a target to use the input subsystem with EVEMU

        - creates a simple keyboard
        - creates a simple absolute mouse

        This can be used only on Linux machines with uinput support
        and will drive the mouse via commands in the console.

        Requirements:

        - The server must have been configured to drop
          *evemu.bin.tar.gz* in the web server for test content; thus
          a client accessing
          *http://SERVERIP/ttbd-images-misc/evemu.bin.tar.gz* will be
          able to get this content. The server install instructions
        provide for this to be the case.
        """
        assert isinstance(ic, tc.target_c)
        target = self.target

        # Download the new evemu binaries with statically linked
        # libraries.
        output = target.shell.run("evemu-event --fifo || true", output = True)
        # if evemu-event is installed, it will print it's help
        ## Usage: evemu-event [--sync] <device> --type <type> --code <code> --value <value>
        #
        # if the --fifo extensions are installed, there will be a
        # --fifo in there
        if '<device>' in output:
            # evemu-event is installed
            self.evemu_event = "evemu-event"
            self.evemu_device = "evemu-device"
            if '--fifo' in output:
                # evemu-event has --fifo support
                self.evemu_event_fifo = "evemu-event --fifo="
                target.report_info("INPUT/evemu: distro's with --fifo")
            else:
                # upload helper
                with msgid_c():
                    target.shell.string_to_file(
                        # Each line is in the format:
                        #
                        # - <DEVICE> <TYPE> <CODE> <VALUE> [SYNC]
                        # - WAIT <MILLISECS>
                        # - empty (ignored)
                        #
                        # the helper is a wee hack since it has more
                        # overhead with evemu with the support
                        """\
    #! /bin/bash
    rm -f $1; mkfifo $1
    tail -f $1 | while read dev typetime code value sync; do
        [ "$dev" == "WAIT" ] && sleep $typetime && continue
        [ "${sync:-}" == SYNC ] && sync="--sync"
        echo evemu-event ${sync:-} /dev/input/$dev --type $type --code $code --value $value
    done
    """,
                        "/usr/local/bin/evemu-event-fifo")
                    target.shell.run("chmod a+x /usr/local/bin/evemu-event-fifo")
                self.evemu_event_fifo = "/usr/local/bin/evemu-event-fifo "
                target.report_info(
                    "INPUT/evemu: distro's with FIFO shell helper")

        else:
            with msgid_c():
                # There is no evemu in the system, so let's upload our
                # semistatic build from the POS cache.
                rsync_server = target.kws.get(
                    'pos_rsync_server',
                    ic.kws.get('pos_rsync_server', None))
                if rsync_server == None:
                    raise tc.error_e(
                        "INPUT/evemu: there is no place where to download"
                        " evemu.bin.tar.gz for, need the"
                        " target or interconnect to export"
                        " *pos_rsync_server* with the location")
                http_server = "http://" \
                    + rsync_server.replace("::images", "/ttbd-images-misc")
                target.shell.run(
                    "curl --noproxy '*' -sk %s/evemu.bin.tar.gz"
                    " --output /tmp/evemu.bin.tar.gz" % http_server)
                target.shell.run(
                    "tar xvvf /tmp/evemu.bin.tar.gz --overwrite -C /")
            self.evemu_event = "/opt/evemu/bin/evemu-event"
            self.evemu_device = "/opt/evemu/bin/evemu-device"
            self.evemu_event_fifo = "/opt/evemu/bin/evemu-event --fifo="
            target.report_info(
                "INPUT/evemu: TCF's static build w/ --fifo")

        self.evemu_create_device("default_mouse", descriptor_mouse)
        self.evemu_create_device("default_keyboard", descriptor_kbd)
        # start the FIFO pipe
        target.shell.run("nohup %s/tmp/evemu.fifo >& /tmp/evemu.log &"
                         % self.evemu_event_fifo)

    device_regex_valid = re.compile("^[0-9A-Za-z]+$")
    evtype_regex_valid = re.compile("^EV_[0-9A-Z]+$")
    code_regex_valid = re.compile("^(SND|REP|LED|MSC|SW|ABS|REL|BTN|KEY|SYN)_[A-Z0-9]+$")
    value_regex_valid = re.compile("^0-9+$")

    def sequence_send(self, sequence):
        """
        Send a sequence of events to one or more devices

        :param str sequence: sequence of events to send to input
          devices as a string.

          No syntax verification is done in the sequence string, it is
          assumed correct. Syntax verification is done for the list
          version of the sequence.

        :param list sequence: sequence of events to send as a list of
          individual events.

          Each event is a tuple in the forms:

            >>> ( 'WAIT', FLOAT )
            >>> ( DEVNAME, EVTYPE, CODE, VALUE[, 'SYNC' ] )

          - *DEVNAME*: device name to send it to; for *evemu* devices
            this will be converted in the target to
            */dev/input/DEVNAME*

          - *EVTYPE*: type of event (as supported by the hardware):

            - *EV_SYN*: synchronizatione vent
            - *EV_KEY*: press a key (eg: keyboard)
            - *EV_REL*: relative movement (eg: mouse)
            - *EV_ABS*: absolute movement (eg: touchpad)
            - *EV_MSC*: miscellaneous events
            - *EV_SW*: set a switch
            - *EV_LED*: set a led
            - *EV_SND*: play a sound
            - *EV_REP*: set repetition
            - *EV_FF*: set force feedback
            - *EV_PWR*: set power
            - *EV_FF_STATUS*: force feedback status

          - *CODE*: depends on the event type, which indicates the
             action being taken

            - *KEY_\**: press/release keys (eg: *KEY_A*, *KEY_B*...
            - *BTN_\**: press/release buttons (eg: *BTN_LEFT*, *BTN_RIGHT*...)
            - *ABS_\**: set absolute axes (eg: *ABS_X*, *ABS_Y*)
            - *SW_\**: miscelaneous switches
            - *MSC_\**: miscellaneous settings
            - *SND_{CLICK,BELL,TONE}*: play a sound
            - *REP_{DELAY,PERIOD}*: set repetition configuration
            - *LED_\**: set different leds

          - *VALUE*: integer value that depends on the *EVTYPE* and
             *CODE*; for example to press a key:

            - 1: press key/button
            - 0: release key/button

        See
        https://www.kernel.org/doc/html/latest/input/event-codes.html
        for more information.

        Examples:

        - press and release key *A*, holding key for 0.1 seconds:

          >>> [
          >>>     ( DEVNAME, 'EV_KEY', 'KEY_A', 1, 'SYNC') ,
          >>>     ( 'WAIT', 0.1 ),
          >>>     ( DEVNAME, 'EV_KEY', 'KEY_A', 0, 'SYNC')
          >>> ]

        - set a touchpad with 100,100 range to the center of its range
          and double click left button

          >>> [
          >>>     ( DEVNAME, 'EV_ABS', 'ABS_X', 50') ,
          >>>     ( DEVNAME, 'EV_ABS', 'ABS_Y', 50')
          >>>     ( DEVNAME, 'EV_KEY', 'BTN_LEFT', 1, 'SYNC')
          >>>     ( 'WAIT', 0.1 ),
          >>>     ( DEVNAME, 'EV_KEY', 'BTN_LEFT', 0, 'SYNC')
          >>>     ( 'WAIT', 0.3 ),
          >>>     ( DEVNAME, 'EV_KEY', 'BTN_LEFT', 1, 'SYNC')
          >>>     ( 'WAIT', 0.1 ),
          >>>     ( DEVNAME, 'EV_KEY', 'BTN_LEFT', 0, 'SYNC')
          >>> ]

        - Type the *@* sign (there is no keycode for it, must press
          shift + plus *2* then release both):

          >>> [
          >>>     ( DEVNAME, 'EV_KEY', 'KEY_LEFTSHIFT', 1 ) ,
          >>>     ( DEVNAME, 'EV_KEY', 'KEY_2', 1, 'SYNC' ) ,
          >>>     ( 'WAIT', 0.1 ),
          >>>     ( DEVNAME, 'EV_KEY', 'KEY_A', 0, 'SYNC' )
          >>>     ( DEVNAME, 'EV_KEY', 'KEY_LEFTSHIFT', 0 ) ,
          >>> ]

        """
        if isinstance(sequence, basestring):
            # send it first to a file, then in a single shot to the
            # FIFO; this ensures the timing on sending the sequence
            # over the serial port (which can be slow if there is a
            # lot of data) does not influence the sequence's timing.
            self.target.shell.run("cat > /tmp/evemu.data\n%s\x04" % sequence)
            self.target.shell.run("cat /tmp/evemu.data > /tmp/evemu.fifo")
            return

        # expect it to be a list of tuples
        count = -1
        self.target.send("cat > /tmp/evemu.data")
        for entry in sequence:
            count += 1
            assert isinstance(entry, (list, tuple))
            devcmd = entry[0]
            if devcmd == "WAIT":
                try:
                    _ = float(entry[1])
                    self.target.send(
                        "WAIT %s\n" % entry[1])
                except ValueError as e:
                    raise tc.error_e(
                        "INPUT sequence #%d: WAIT:"
                        " missing or invalid seconds field;"
                        " can't convert to float: %s" % (count, e))
                self.target.console.write("WAIT %s\n" % entry[1])
                continue
            if len(entry) != 4 and len(entry) == 5:
                raise tc.error_e(
                    "INPUT sequence #%d: event:"
                    " invalid number of entries;"
                    " got %d, expect 4 or 5 " % (count, len(entry)))
            evtype = entry[1]
            if self.evtype_regex_valid.search(evtype):
                raise tc.error_e(
                    "INPUT sequence #%d: event type '%s'"
                    " invalid; must match %s"
                    % (count, evtype, self.evtype_regex_valid.pattern))
            code = entry[2]
            if self.code_regex_valid.search(code):
                raise tc.error_e(
                    "INPUT sequence #%d: code '%s'"
                    " invalid; must match %s"
                    % (count, code, self.code_regex_valid.pattern))
            value = entry[3]
            if self.value_regex_valid.search(value):
                raise tc.error_e(
                    "INPUT sequence #%d: code '%s'"
                    " invalid; must match %s"
                    % (count, value, self.value_regex_valid.pattern))
            if len(entry) == 5:
                sync = entry[4]
                if sync != "SYNC":
                    raise tc.error_e(
                        "INPUT sequence #%d: 5th field '%s'"
                        " invalid; can only be 'SYNC'"
                        % (count, sync))
            else:
                sync = ""
            self.target.send(
                "%s %s %s %s\n"
                % evtype, code, value, sync)
        # complete the cat command we started above
        self.target.send("\x04" % sequence)
        self.target.shell.run("cat /tmp/evemu.data > /tmp/evemu.fifo")

    def _device_get(self, did):
        if did not in self.devices:
            raise tc.error_e("INPUT: device ID %s does not exist" % did)
        return self.devices[did]

    def mouse_move_to(self, x, y, did = "default_mouse"):
        """
        Move the mouse pointer to the given coordinates

        The coordinates are given in an absolute form and require the
        mouse to support absolute addressing. The default mouse created
        by :meth:`setup_target_evemu` can do this (axes range from
        0-65536).

        :param int|float x: X coordinate where to click; if integer,
          it is considered to be an absolute coordinate. If float
          between 0 and 1, a relative coordinate (0 leftmost edge, 1
          rightmost) If *None*, don't move the mouse on the X axis.

        :param int|float y: Y coordinate where to click, same typing a
          X.  If *None*, don't move the mouse on the Y axis.

        :param str did: (optional) name of mouse to use; defaults
          to *default_mouse*.

        NOTE: requires the mouse device to support absolute coordinates

        """
        assert x == None or isinstance(x, numbers.Real)
        assert y == None or isinstance(y, numbers.Real)
        assert isinstance(did, basestring)

        device = self._device_get(did)
        target = self.target
        target.report_info("mouse %s: moving to (%s, %s)" % (did, x, y))
        # FIXME: coordinates are now hardcoded to max 65k as absolute;
        # this has to be moved down the pile to the mouse
        # implementation later on as we have multiple implementations
        if x and y == None:
            if isinstance(x, float):
                x = int(x * 65536)
            self.sequence_send(
                "%s EV_ABS ABS_Y %s SYNC\n"
                % (device, x))
        elif y and x == None:
            if isinstance(y, float):
                y = int(y * 65536)
            self.sequence_send(
                "%s EV_ABS ABS_Y %s SYNC\n"
                % (device, y))
        elif x and y:
            if isinstance(x, float):
                x = int(x * 65536)
            if isinstance(y, float):
                y = int(y * 65536)
            self.sequence_send(
                "%s EV_ABS ABS_X %s\n"
                "%s EV_ABS ABS_Y %s SYNC\n"
                % (device, x, device, y))

    def mouse_click(self, x = None, y = None, did = "default_mouse",
                    click_time = 0.1, button = 'BTN_LEFT', times = 1,
                    interclick_time = 0.25):
        """
        Single click (or press and hold) a mouse button optionally
        moving the mouse first to a location

        To use, in the evaluation of a testcase running on a target
        which has input capability:

        >>> self.input.mouse_click(0.5, 0.5)

        :param int|float x: X coordinate where to click; if integer,
          it is considered to be an absolute coordinate. If float
          between 0 and 1, a relative coordinate (0 leftmost edge, 1
          rightmost) If *None*, don't move the mouse on the X axis.

        :param int|float y: Y coordinate where to click,same typing a X.
          If *None*, don't move the mouse on the Y axis.

        :param str did: (optional) name of mouse to use; defaults
          to *default_mouse*.

        :param str button: (optional) button to press (defaults to
          *BTN_LEFT*)

        :param float click_time: (optional) seconds to wait with the
           mouse button pressed for the clicking; if 0 or None, it
           will just press and not release.

        :param int times: how many times to click (eg: two for a
          double click)
        """
        assert isinstance(did, basestring)
        assert isinstance(click_time, numbers.Real)
        assert isinstance(button, basestring)
        assert isinstance(times, int)
        assert isinstance(interclick_time, numbers.Real)

        device = self._device_get(did)
        target = self.target

        # FIXME: coordinates are now hardcoded to max 65k as absolute;
        # this has to be moved down the pile to the mouse
        # implementation later on as we have multiple implementations
        if x != None or y != None:
            self.mouse_move_to(x, y, did)
            target.report_info("mouse %s: clicking at (%s, %s)"
                               % (did, x, y))
        else:
            target.report_info(
                "mouse %s: clicking at current location" % did)
        s = "%s EV_KEY %s 1 SYNC\n" \
            "WAIT %s\n" \
            "%s EV_KEY %s 0 SYNC\n" \
            % (device, button, click_time, device, button)
        # if double, triple click... add it
        for _ in range(times - 1):
            s += \
                "WAIT %s\n" \
                "%s EV_KEY %s 1 SYNC\n" \
                "WAIT %s\n" \
                "%s EV_KEY %s 0 SYNC\n" \
                % (interclick_time, device, button,
                   click_time, device, button)
        self.sequence_send(s)


    def mouse_release(self, x = None, y = None, did = "default_mouse",
                      button = 'BTN_LEFT'):
        """
        Release a mouse button, optionally moving the mouse first

        >>> self.input.mouse_click(0.5, 0.5)

        :param x: X coordinate where to release; if integer, it is
          considered to be an absolute coordinate. If float between 0
          and 1, a relative coordinate (0 leftmost edge, 1 rightmost)
          If *None*, don't move the mouse on the X axis.

        :param y: Y coordinate where to click,same typing a X.
          If *None*, don't move the mouse on the Y axis.

        :param str did: (optional) mouse to use to click

        :param float click_time: (optional) seconds to wait with the
           mouse button pressed for the clicking; if 0 or None, it
           will just press and not release.
        """
        assert isinstance(did, basestring)
        assert isinstance(button, basestring)

        device = self._device_get(did)
        if x != None or y != None:
            self.mouse_move_to(x, y, did)
        self.sequence_send("%s EV_KEY %s 0 SYNC\n"
                           % (device, button))


    def image_click(self, detection, did = "default_mouse",
                    button = 'BTN_LEFT', click_time = 0.1,
                    times = 1, interclick_time = 0.35):
        """
        Given the square where an image is detected (by the likes of
        :ref:`target.capture.image_on_screenshot
        <tcfl.target_ext_capture.extension.image_on_screenshot>`),
        double click on that icon:

        To use, in the evaluation of a testcase running on a target
        which has UI capture abilities:

        >>> r = self.expect(target.capture.image_on_screenshot('icon-firefox.png'))
        >>> self.input.image_click(r['icon-firefox_png'])

        :param dict detection: square where the image was detected by
          :ref:`target.capture.image_on_screenshot
          <tcfl.target_ext_capture.extension.image_on_screenshot>`

        For info on other parameters, see :meth:`mouse_click`
        """
        assert isinstance(detection, dict)

        # just get the first match's relative coordinates
        square = detection.values()[0]['relative']
        x = (square[0] + square[2]) / 2
        y = (square[1] + square[3]) / 2

        self.mouse_click(x, y, did = did,
                         button = button, click_time = click_time,
                         times = times, interclick_time = interclick_time)


    #:
    #: Maps characters to keys (and FIXME: key sequences)
    #:
    #: Note when you say type *@*, there is no *@* key, so it has to
    #: do SHIFT+2.
    key_mapping = {
        #
        # KEY_F1 ... KEY_F12,
        #
        # KEY_INSERT, KEY_DEL, KEY_HOME, KEY_END, KEY_PGUP,
        # KEY_PGDN, KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN,
        #
        # KEY_SLASH_PAD, KEY_ASTERISK, KEY_MINUS_PAD,
        # KEY_PLUS_PAD, KEY_DEL_PAD, KEY_ENTER_PAD,
        #
        # KEY_PRTSCR, KEY_PAUSE,
        #
        # KEY_ABNT_C1, KEY_YEN, KEY_KANA, KEY_CONVERT, KEY_NOCONVERT,
        # KEY_AT, KEY_CIRCUMFLEX, KEY_COLON2, KEY_KANJI,
        #
        # KEY_LSHIFT, KEY_RSHIFT,
        # KEY_LCONTROL, KEY_RCONTROL,
        # KEY_ALT, KEY_ALTGR,
        # KEY_LWIN, KEY_RWIN, KEY_MENU,
        # KEY_SCRLOCK, KEY_NUMLOCK, KEY_CAPSLOCK
        #
        # KEY_EQUALS_PAD, KEY_BACKQUOTE, KEY_SEMICOLON, KEY_COMMAND

        'a' : 'KEY_A',
        'b' : 'KEY_B',
        'c' : 'KEY_C',
        'd' : 'KEY_D',
        'e' : 'KEY_E',
        'f' : 'KEY_F',
        'g' : 'KEY_G',
        'h' : 'KEY_H',
        'i' : 'KEY_I',
        'j' : 'KEY_J',
        'k' : 'KEY_K',
        'l' : 'KEY_L',
        'm' : 'KEY_M',
        'n' : 'KEY_N',
        'o' : 'KEY_O',
        'p' : 'KEY_P',
        'q' : 'KEY_Q',
        'r' : 'KEY_R',
        's' : 'KEY_S',
        't' : 'KEY_T',
        'u' : 'KEY_U',
        'v' : 'KEY_V',
        'w' : 'KEY_W',
        'x' : 'KEY_X',
        'y' : 'KEY_Y',
        'z' : 'KEY_Z',
        # KEY_0 ... KEY_9,
        '0' : 'KEY_0',
        '1' : 'KEY_1',
        '2' : 'KEY_2',
        '3' : 'KEY_3',
        '4' : 'KEY_4',
        '5' : 'KEY_5',
        '6' : 'KEY_6',
        '7' : 'KEY_7',
        '8' : 'KEY_8',
        '9' : 'KEY_9',
        '.' : 'KEY_DOT',
        # KEY_0_PAD ... KEY_9_PAD,
        #
        # KEY_ESC,
        "`" : 'KEY_TILDE',
        "-": 'KEY_MINUS',
        "=": 'KEY_EQUALS',
        # KEY_BACKSPACE,
        "\t": 'KEY_TAB',
        "{": 'KEY_OPENBRACE',
        "}": 'KEY_CLOSEBRACE',
        "\n": 'KEY_ENTER',
        ":": 'KEY_COLON',
        "'": 'KEY_QUOTE',
        "\\": 'KEY_BACKSLASH',
        # KEY_BACKSLASH2,
        ",": 'KEY_COMMA',
        # KEY_STOP,
        '/' : 'KEY_SLASH',
        ' ' : 'KEY_SPACE'
    }


    def kbd_key_hold(self, key_code, did = "default_keyboard"):
        """
        Press and hold a key on a keyboard

        :param str key_code: key to hold (refer to :meth:`sequence_send`)
        :param str did: (optional) name of the device to which to send it
        """
        assert isinstance(key_code, basestring)
        assert isinstance(did, basestring)

        device = self._device_get(did)
        self.sequence_send(
            "%s EV_KEY %s 1 SYNC\n"
            % (device, key_code))

    def kbd_key_release(self, key_code, did = "default_keyboard"):
        """
        Release a held key on a keyboard

        :param str key_code: key to release (refer to :meth:`sequence_send`)
        :param str did: (optional) name of the device to which to send it
        """
        assert isinstance(key_code, basestring)
        assert isinstance(did, basestring)
        device = self._device_get(did)
        self.sequence_send(
            "%s EV_KEY %s 0 SYNC\n"
            % (device, key_code))

    def kbd_key_press(self, key_code, did = "default_keyboard",
                      press_time = 0.1):
        """
        Press and release (click/type) key on a keyboard for a given
        amount of time.

        :param str key_code: key to release (refer to :meth:`sequence_send`)
        :param str did: (optional) name of the device to which to send it
        :param float press_time: (optional) time in seconds to press
          the key
        """
        assert isinstance(key_code, basestring)
        assert isinstance(did, basestring)
        assert isinstance(press_time, numbers.Real)

        device = self._device_get(did)
        self.sequence_send(
            "%s EV_KEY %s 1\n"
            "WAIT %s\n"
            "%s EV_KEY %s 0 SYNC\n"
            % (device, key_code, press_time, device, key_code))

    def kbd_string_send(self, string, did = "default_keyboard",
                        press_time = 0.2, interkey_time = 0.2):
        """
        Send a sequence of strings to a keyboard as key presses

        :param str string: string to send; note some characters can't
          be sent as is and have to be translated to key sequences
          (eg: press and hold shift, key X, relase shift). This is
          still not supported (FIXME)
        :param str did: (optional) name of the device to which to send it
        :param float press_time: (optional) time in seconds to press
          the key
        :param float interkey_time: (optional) time in seconds to wait
          between pressing keys for each string character
        """
        assert isinstance(string, basestring)
        assert isinstance(did, basestring)
        assert isinstance(press_time, numbers.Real)
        assert isinstance(interkey_time, numbers.Real)

        device = self._device_get(did)
        s = ""
        for char in string.lower():
            if char in self.key_mapping:
                key_code = self.key_mapping[char]
            else:
                raise tc.blocked_e(
                    "still don't know how to send character '%s', add to"
                    "input.key_mapping" % char)
            s += \
                "%s EV_KEY %s 1\n" \
                "WAIT %s\n" \
                "%s EV_KEY %s 0 SYNC\n" \
                "WAIT %s\n" \
                % (device, key_code, press_time,
                   device, key_code, interkey_time)
        self.sequence_send(s)
