#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
import logging
import os
import struct

import serial
import serial.tools.list_ports

import ttbl
import ttbl.things
import ttbl.buttons

class rly08b(object):
    """
    A power control implementation for the USB-RLY08B relay controller
    https://www.robot-electronics.co.uk/htm/usb_rly08btech.htm.

    This serves as base for other drivers to implement :class:`per
    relay power controllers <pc>`, :class:`USB pluggers as *thing* or
    power controllers <plugger>`.

    This device offers eight relays for AC and DC. The relays being on
    or off are controlled by a byte-oriented serial protocol over an
    FTDI chip that shows as::

      $ lsusb.py -iu
      ...
      1-1.1.1       04d8:ffee 02  2.00   12MBit/s 100mA 2IFs (Devantech Ltd. USB-RLY08 00023456)
         1-1.1.1:1.0   (IF) 02:02:01 1EP  (Communications:Abstract (modem):AT-commands (v.25ter)) cdc_acm tty/ttyACM0
         1-1.1.1:1.1   (IF) 0a:00:00 2EPs (CDC Data:) cdc_acm
      ...

    Note the *00023456* is the serial number.

    To avoid permission issues, it can either:

    - The default rules in most Linux platforms will make the
      device node owned by group *dialout*, so make the daemon
      have that supplementary GID.

    - add a UDEV rule to ``/etc/udev/rules.d/90-ttbd.rules`` (or
      other name)::

        SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "00023456", \
          GROUP="GROUPNAME", MODE = "660"

      restart *udev**::

        $ sudo udevadm control --reload-rules

      replug your hubs so the rule is set.

    :param str serial_number: Serial number of the relay's control
      device.

    :param int relay: number of the relay to control (1-8)

    """

    class not_found_e(ValueError):
        pass

    # This code is SINGLE THREADED, so we are going to share one
    # backend to cut in the number of open file handles
    backend = None

    def __init__(self, serial_number):
        assert isinstance(serial_number, str)
        self.serial_number = serial_number

    def _command(self, cmd, states = None, get_state = False):
        """
        Execute a command, maybe get a reponse and relay states

        Opens the serial port and sends the command; depending on the
        command, read expected response and if we need to get state,
        get it, appending it to the response.
        :param byte cmd: byte command to send; if a list of bytes, a
          list of commands to send in sequence.
        """
        if not isinstance(cmd, list):
            cmds = [ cmd ]
        else:
            cmds = cmd
        response = []
        ports = serial.tools.list_ports.comports()
        port = None
        for port in ports:
            if port.vid == 0x04d8 and port.pid == 0xffee \
               and port.serial_number == self.serial_number:
                break
        else:
            raise self.not_found_e("Cannot find USB-RLY8B with serial %s"
                                   % self.serial_number)

        with serial.Serial(port.device, baudrate = 9600,
                           bytesize = serial.EIGHTBITS,
                           parity = serial.PARITY_NONE,
                           stopbits = serial.STOPBITS_ONE,
                           # .5s for timeout to avoid getting stuck,
                           # which will trigger the watchdog
                           timeout = 0.5) as s:
            for cmd in cmds:
                assert cmd >= 0 and cmd <= 255
                s.write(bytearray([cmd]))
                if cmd == 0x38:		# get serial #
                    response.append(s.read(8))
                elif cmd == 0x5a:		# get SW version
                    response.append(s.read(2))
                elif cmd == 0x5b:		# get relay states
                    r = s.read(1)
                    response.append(r)
                elif cmd == 0x5c:   	# set relay states
                    assert states >= 0 and states <= 255
                    s.write(bytearray([states]))
                    response.append(None)
                elif cmd >= 0x64 or cmd <= 76:
                    # No response
                    response.append(None)
                else:
                    raise ValueError("Unknown command 0x%02x" % cmd)

            if get_state:
                s.write(bytearray([0x5b]))
                r = s.read(1)
                response.append(r)
            return response


class pc(rly08b, ttbl.power.impl_c):
    """
    Power control implementation that uses a relay to close/open a
    circuit on on/off
    """
    def __init__(self, serial_number, relay):
        self.relay = relay
        rly08b.__init__(self, serial_number)
        ttbl.power.impl_c.__init__(self)

    def on(self, target, _component):
        cmd = 0x64 + self.relay
        rs = self._command(cmd, get_state = True)[-1]
        rl = struct.unpack('<' + 'B' *len(rs), rs)
        r = rl[0]
        if not r & (1 << (self.relay - 1)):
            raise RuntimeError("USB-RLY08B[%s] failed to power on relay #%d"
                               " (returned 0x%02x)"
                               % (self.serial_number, self.relay, r))

    def off(self, target, _component):
        # Okie, this is quite a hack -- when we try to power it off,
        # if the serial is not found, we just assume the device is not
        # there and thus it is off -- so we ignore it. Why? Becuase
        # when we are part of a power control rail, we can't
        # interrogate the device or turn it off because maybe it is
        # disconnected. _command() has tried a few times to rule out
        # the device being quirky.
        cmd = 0x6e + self.relay
        try:
            rs = self._command(cmd, get_state = True)[-1]
            rl = struct.unpack('<' + 'B' *len(rs), rs)
            r = rl[0]
            if r & (1 << (self.relay - 1)):
                raise RuntimeError("USB-RLY08B[%s] failed to power off "
                                   "relay #%d (returned 0x%02x)"
                                   % (self.serial_number, self.relay, r))
        except self.not_found_e:
            target.log.log(8, "USB-RLY08B[%s] not found, assuming relay "
                           "#%d powered off"
                           % (self.serial_number, self.relay))

    def get(self, target, _component):
        cmd = 0x5b
        try:
            rs = self._command(cmd)[-1]
            rl = struct.unpack('<' + 'B' *len(rs), rs)
            r = rl[0]
            target.log.log(8, "USB-RLY08B[%s] status 0x%02x"
                           % (self.serial_number, r))
            if r & (1 << (self.relay - 1)):
                return True
            else:
                return False
        except self.not_found_e:
            # If it is not connected, it is off
            target.log.log(8, "USB-RLY08B[%s] not found, assuming relay "
                           "#%d powered off"
                           % (self.serial_number, self.relay))
            return False


class button_c(pc, ttbl.buttons.impl_c):
    """
    Implement a button press by closing/opening a relay circuit
    """
    def __init__(self, serial_number, relay):
        ttbl.buttons.impl_c.__init__(self)
        pc.__init__(self, serial_number, relay)

    def press(self, target, button):
        self.on(target, button)

    def release(self, target, button):
        self.off(target, button)

    # get implemented by pc.get()


class plugger(rly08b,		 # pylint: disable = abstract-method
              ttbl.things.impl_c,
              ttbl.power.impl_c):
    """
    Implement a USB multiplexor/plugger that allows a DUT to be
    plugged to Host B and to Host A when unplugged. It follows it can
    work as a USB cutter if Host A is disconnected.

    It also implements a power control implementation, so when powered
    off, it plugs-to-Host-B and when powered on, it
    plugs-to-host-A. Likewise, if Host B is disconnected, when off it
    is effectively disconnected. This serves to for example, connect a
    USB storage drive to a target that will be able to access it when
    turned on and when off, it can be connected to another machine
    that can, eg: use it to flash software.

    This uses a :class:`rly08b` relay bank to do the switching.

    :param str serial_number: USB serial number of the USB-RLY8B
        device used to control

    :param int bank: bank of relays to use; bank 0 are relays 1-4,
        bank 1 are relays 5-8. Note below for connection information.

    **System setup details**

    - A USB connection is four cables: VCC (red), D+ (white), D-
      (green), GND (black) plus a shielding wrapping it all.

    - A relay has three terminals; NO, C and NC.
      - ON means C and NC are connected
      - OFF means C and NO are connected

      (it is recommended to label the cable connected to NO as
       OFF/PLUGGED and the one to NC as ON/UNPLUGGED)

    - We use the USB-RLY8B, which has eight individual relays, so we can
      switch two devices between two USB hosts each.

    We connect the DUT's cables and host cables as follows:

    =========== ===  =========== ===  =========== ===
    DUT1        pin  Host A1/ON  pin  Host B1/OFF pin
    ----------- ---  ----------- ---  ----------- ---
    VCC (red)    1C  VCC (red)   1NO  VCC (red)   1NC
    D+  (white)  2C  D+  (white) 2NO  D+  (white) 2NC
    D-  (green)  3C  D-  (green) 3NO  D-  (green) 3NC
    GND (black)  4C  GND (black) 4NO  GND (black) 4NC
    =========== ===  =========== ===  =========== ===

    =========== ===  =========== ===  =========== ===
    DUT2        pin  Host A2/ON  pin  Host B1/OFF pin
    ----------- ---  ----------- ---  ----------- ---
    VCC (red)    5C  VCC (red)   5NO  VCC (red)   5NC
    D+  (white)  6C  D+  (white) 6NO  D+  (white) 6NC
    D-  (green)  7C  D-  (green) 7NO  D-  (green) 7NC
    GND (black)  8C  GND (black) 8NO  GND (black) 8NC
    =========== ===  =========== ===  =========== ===

    For example, to switch an Arduino 101 between a NUC and the TTBD
    server that flashes and controls it:

    - DUT (C) is our Arduino 101,
    - Host B (NC) is another NUC machine in the TCF infrastructure
    - Host A (NO) is the TTBD server (via the YKUSH port)

    For a pure USB cutter (where we don't need the connection to a
    TTBD server on MCU boards that expose a separate debugging cable
    for power and flashing), we'd connect the USB port like:

    - DUT (C) is the MCU's USB port
    - Host B (NC) is the NUC machine in the TCF infrastructure
    - Host A (NO) is left disconnected

    .. note:: switching *ONLY* the VCC and GND connections (always
              leave D+ and D- connected the the Host A to avoid Host B
              doing a data connection and only being used to supply
              power) does not work.

              Host A still detects the power differential in D+ D- and
              thought there was a device; tried to enable it, failed
              and disabled the port.

    .. note:: We can't turn them on or off at the same time because
              the HW doesn't allow to set a mask and we could override
              settings for the other ports we are not controlling
              here--another server process might be tweaking the other
              ports.

    ** Configuration details **

    Example:

      To connect a USB device from system A to system B, so power off
      means connected to B, power-on connected to A, add to the
      configuration:

      >>> target.interface_add("power", ttbl.power.inteface(
      >>>      ttbl.usbrly08b.plugger("00023456", 0)
      >>> )
      >>> ...

      Thus to connect to system B::

        $ tcf acquire devicename
        $ tcf power-off devicename

      Thus to connect to system A::

        $ tcf power-on devicename

    Example:

      If system B is the ttbd server, then you can refine it to test
      the USB device is connecting/disconnecting.

      To connect a USB drive to a target before the target is powered
      on (in this example, a NUC mini-PC with a USB drive connected
      to boot off it, the configuration block would be as::

      >>> target.interface_add("power", ttbl.power.interface(
      >>>     # Ensure the dongle is / has been connected to the server
      >>>     ttbl.pc.delay_til_usb_device("7FA50D00FFFF00DD",
      >>>                                  when_powering_on = False,
      >>>                                  want_connected = True),
      >>>     ttbl.usbrly08b.plugger("00023456", 0),
      >>>     # Ensure the dongle disconnected from the server
      >>>     ttbl.pc.delay_til_usb_device("7FA50D00FFFF00DD",
      >>>                                  when_powering_on = True,
      >>>                                  want_connected = False),
      >>>     # power on the target
      >>>     ttbl.pc.dlwps7("http://admin:1234@SPNAME/SPPORT"),
      >>>     # let it boot
      >>>     ttbl.pc.delay(2)
      >>> )
      >>> ...

      Note that the serial number *7FA50D00FFFF00DD* is that of the
      USB drive and *00023456* is the serial number of the USB-RLY8b
      board which implements the switching (in this case we use bank 0
      of relays, from 1 to 4).

    Example:

    An Arduino 101 is connected to a NUC mini-PC as a USB device using
    the *thing* interface that we can control from a script or command line:

    In this case we create an *interconnect* that wraps all the
    targets together (the Arduino 101, the NUC) to indicate they
    operate together and the configuration block would be::

      ttbl.config.interconnect_add(ttbl.test_target("usb__nuc-02__a101-04"),
                                  ic_type = "usb__host__device")
      ttbl.config.targets['nuc-02'].add_to_interconnect('usb__nuc-02__a101-04')
      ttbl.config.targets['a101-04'].add_to_interconnect('usb__nuc-02__a101-04')
      ttbl.config.targets['nuc-02'].thing_add('a101-04',
                                              ttbl.usbrly08b.plugger("00033085", 1))

    Where *00033085* is the serial number for the USB-RLY8b which
    implements the USB plugging/unplugging (in this case we use bank 1
    of relays, from 5 to 8)
    """
    def __init__(self, serial_number, bank):
        self.serial_number = serial_number
        self.bank = bank
        if bank == 0:
            self.vcc = 4
            self.dp = 3
            self.dm = 2
            self.gnd = 1
            self.mask = 0x0f
        elif bank == 1:
            self.vcc = 8
            self.dp = 7
            self.dm = 6
            self.gnd = 5
            self.mask = 0xf0
        else:
            raise RuntimeError("unknown bank number %s "
                               "(only 0 or 1 available)" % bank)
        # 0 is ignored, we don't use an specific relay in this mode
        rly08b.__init__(self, serial_number)
        ttbl.things.impl_c.__init__(self)
        ttbl.power.impl_c.__init__(self)

    def plug(self, target, _thing):	# pylint: disable = missing-docstring
        # Connect terminals C and NC (Host B), disconnecting NO (Host A)
        # to the switch.

        # Turn the vcc, dm, dn, gnd off so they switch to Host B
        response = self._command(
            [
                0x6e + self.vcc, 0x6e + self.dp,
                0x6e + self.dm, 0x6e + self.gnd
            ], get_state = True)
        # Verify the states match
        state = ord(response[-1])
        target.log.info("USB-RLY08B[%s/%d] status after plug 0x%02x"
                        % (self.serial_number, self.bank, state))
        if state & self.mask:
            raise RuntimeError("USB-RLY08B[%s] failed to plug (powering "
                               "off ports %d|%d|%d|%d, state 0x%02x)"
                               % (self.serial_number,
                                  self.vcc, self.dp, self.dm, self.gnd,
                                  state & self.mask))

    def unplug(self, target, _thing):	# pylint: disable = missing-docstring
        # Connect terminals C and NO (Host A), disconnecting NC (Host B).

        # Turn the vcc, dm, dn, gnd off so they switch to Host B
        response = self._command(
            [
                0x64 + self.vcc, 0x64 + self.dp,
                0x64 + self.dm, 0x64 + self.gnd
            ], get_state = True)
        # Verify the states match
        state = ord(response[-1])
        target.log.info("USB-RLY08B[%s/%d] status after unplug 0x%02x"
                        % (self.serial_number, self.bank, state))
        if state & self.mask != self.mask:
            raise RuntimeError("USB-RLY08B[%s] failed to unplug (powering "
                               "off ports %d|%d|%d|%d, state 0x%02x)"
                               % (self.serial_number,
                                  self.vcc, self.dp, self.dm, self.gnd,
                                  state & self.mask))

    def on(self, target, _component):
        # Why reverse? Because we'd rather have default power off to
        # be disconnected from the target that requires it on until we
        # turn the target on
        self.unplug(target, None)

    def off(self, target, _component):
        self.plug(target, None)

    def get(self, target, _thing = None):
        cmd = 0x5b
        try:
            rs = self._command(cmd)[-1]
            rl = struct.unpack('<' + 'B' *len(rs), rs)
            r = rl[0]
            target.log.info("USB-RLY08B[%s/%d] status 0x%02x"
                            % (self.serial_number, self.bank, r))
            # watch out: off (False) means connected to Host-A
            return bool(r & self.mask == self.mask)
        except self.not_found_e:
            # If it is not connected, it is off
            target.log.log(8, "USB-RLY08B[%s] not found, assuming bank "
                           "%d connected to Host-B"
                           % (self.serial_number, self.bank))
            return False

