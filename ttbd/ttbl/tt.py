#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#


import codecs
import os
import shutil
import socket
import string
import subprocess
import sys
import telnetlib
import tempfile
import time

import serial

import commonl
import ttbl
import ttbl.cm_loopback
import ttbl.cm_serial
import ttbl.config
import ttbl.pc_ykush
import ttbl.tt_qemu


class tt_serial(
        ttbl.test_target,
        ttbl.tt_power_control_mixin,
        ttbl.cm_serial.cm_serial):
    """A generic test target, power switched with a pluggable power
    control implementation and with one or more serial ports.

    Example configuration::

    >>> ttbl.config.target_add(
    >>>     tt_serial(
    >>>         "minnow-01",
    >>>         power_control = ttbl.pc.dlwps7("http://URL"),
    >>>         serial_ports = [
    >>>             { "port": "/dev/tty-minnow-01", "baudrate": 115200 }
    >>>         ]),
    >>>     tags = {
    >>>         'build_only': True,
    >>>         'bsp_models': { 'x86': None },
    >>>         'bsps': {
    >>>             'x86': dict(board = 'minnowboard',
    >>>                         console = "")
    >>>         }
    >>>     },
    >>>     target_type = "minnow_max")

    With a udev configuration that generated the ``/dev/tty-minnow-01``
    name such as ``/etc/udev/rules.d/SOMETHING.rules``::

      SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "SERIALNUMBER", \
        GROUP = "SOMEGROUP", MODE = "0660", \
        SYMLINK += "tty-minnow-01"

    :param power_control: an instance of an implementation
      of the power_control_mixin used to implement power control for
      the target. Use ttbl.pc.manual() for manual power control that
      requires user interaction.

    :param serial_ports: list of serial port dictionaries, specified
      as for :func:`serial.serial_for_url` with a couple of extras as
      specified in :class:`ttbl.cm_serial`.

    """
    def __init__(self, id, power_control, serial_ports,
                 _tags = None, target_type = None):
        ttbl.test_target.__init__(self, id, _tags = _tags, _type = target_type)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        ttbl.cm_serial.cm_serial.__init__(self, self.state_dir, serial_ports)


class tt_power(
        ttbl.test_target,
        ttbl.tt_power_control_mixin):
    def __init__(self, id, power_control, power = None):
        """
        A generic test target for just power control

        >>> ttbl.config.target_add(
        >>>    ttbl.tt.tt_power(name, ttbl.pc.dlwps7(URL), power = None),
        >>>    tags = dict(idle_poweroff = 0))

        :param bool power: if specified, switch the power of the target
          upon initialization; *True* powers it on, *False* powers it
          off, *None* does nothing.

        """
        assert isinstance(id, basestring)
        ttbl.test_target.__init__(self, id)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        if power == True:
            self.log.info("Powering on per configuration")
            self._power_on_do()
        elif power == False:
            self.log.info("Powering off per configuration")
            self._power_off_do()

class tt_power_lc(
        ttbl.test_target,
        ttbl.cm_loopback.cm_loopback,
        ttbl.tt_power_control_mixin):
    def __init__(self, id, power_control, power = None, consoles = None):
        """
        A generic test target for just power control and fake loopback consoles

        >>> ttbl.config.target_add(
        >>>    ttbl.tt.tt_power(name, ttbl.pc.dlwps7(URL), power = None))

        :param bool power: if specified, switch the power of the target
          upon initialization; *True* powers it on, *False* powers it
          off, *None* does nothing.

        :param consoles: see :class:`ttbl.cm_loopback.cm_loopback`.

        """
        ttbl.test_target.__init__(self, id)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        ttbl.cm_loopback.cm_loopback.__init__(self, self.state_dir, consoles)
        if power == True:
            self.log.info("Powering on per configuration")
            self._power_on_do()
        elif power == False:
            self.log.info("Powering off per configuration")
            self._power_off_do()



class tt_arduino2(
        ttbl.test_target,
        ttbl.test_target_images_mixin,
        ttbl.tt_power_control_mixin,
        ttbl.cm_serial.cm_serial):
    #: Command to call to execute the BOSSA command line flasher
    bossac_cmd = "bossac"

    def __init__(self, _id, serial_port,
                 power_control = None,
                 bossac_cmd = None):
        """Test target for a target flashable with the bossac tool (mostly
        Arduino Due)

        *Requirements*

        - Needs a connection to the USB  programming port

        - Uses the bossac utility built on the *arduino* branch from
          https://github.com/shumatech/BOSSA/tree/arduino; requires it
          to be installed in the path ``bossac_cmd`` (defaults to sytem
          path). Supports ``kernel{,-arm}`` images::

            $ git clone https://github.com/shumatech/BOSSA.git bossac.git
            $ cd bossac.git
            $ make -k
            $ sudo install -o root -g root bin/bossac /usr/local/bin

        - TTY devices need to be properly configured permission wise for
          bossac and serial console to work; for such, choose a Unix group
          which can get access to said devices and add udev rules such as::

            # Arduino2 boards: allow reading USB descriptors
            SUBSYSTEM=="usb", ATTR{idVendor}=="2a03", ATTR{idProduct}=="003d", \
              GROUP="GROUPNAME", MODE = "660"

            # Arduino2 boards: allow reading serial port
            SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "SERIALNUMBER", \
              GROUP = "GROUPNAME", MODE = "0660", \
              SYMLINK += "tty-TARGETNAME"

        The theory of operation is quite simple. According to
        https://www.arduino.cc/en/Guide/ArduinoDue#toc4, the Due will
        erase the flash if you open the programming port at 1200bps
        and then start a reset process and launch the flash when you
        open the port at 115200. This is not so clear in the URL
        above, but this is what expermientation found.

        So for flashing, we'll take over the console, set the serial
        port to 1200bps, wait a wee bit and then call bossac.

        We need power control to fully reset the Arduino Due when it
        gets in a tight spot (and to save power when not using it).
        There is no reset, we just power cycle -- found no way to do a
        reset in SW without erasing the flash.

        :param str _id: name identifying the target

        :param str serial_port: File name of the device node
           representing the serial port this device is connected to.

        :param ttbl.tt_power_control_impl power_control: power controller
          (if any)

        :param bossac_cmd: (optional) path and file where to find the
          `bossac` utility.

        """
        self.serial_port = serial_port
        self.serial_port_basename = os.path.basename(serial_port)
        #:param power_url: http://USER:PASSWORD@HOST:PORT/OUTLETNUMBER
        ttbl.test_target.__init__(self, _id)
        ttbl.test_target_images_mixin.__init__(self)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        ttbl.cm_serial.cm_serial.__init__(
            self, self.state_dir,
            [
                "pc",
                { 'port': serial_port, 'baudrate': 115200 }
            ])
        if bossac_cmd:
            assert isinstance(bossac_cmd, basestring)
            self.bossac_cmd = bossac_cmd

    def image_do_set(self, image_type, image_name):
        """Just validates the image types are ok. The flashing happens in
        images_do_set().

        :param str image_type: Type of the image supported
        :param str image_name: Name of image file in the daemon
          storage space for the user
        :raises: Any exception on failure

        """
        if image_type != "kernel" and image_type != "kernel-arm":
            raise self.unsupported_image_e("%s: image type not supported "
                                           "(only kernel or kernel-arm)"
                                           % image_type)
        self.power_on(self.owner_get())
        with self.console_takeover():
            # erase the flash by opening the serial port at 1200bps
            self.log.info("Erasing the flash")
            eo = serial.Serial(port = self.serial_port, baudrate = 1200)
            time.sleep(0.25)
            eo.close()
            self.log.debug("Erased the flash")
            # now write it
            cmdline = [ self.bossac_cmd,
                        "-p", self.serial_port_basename,
                        "-e",       # Erase current
                        "-w",	# Write a new one
                        "-v",	# Verify,
                        "-b",	# Boot from Flash
                        image_name ]
            self.log.info("flashing image with: %s" % " ".join(cmdline))
            so = commonl.logfile_open("bossac", type(self), True, 0)
            s = subprocess.Popen(
                cmdline, stdin = None, cwd = "/tmp",
                stdout = so, stderr = subprocess.STDOUT)
            self.log.info("running %s" % (" ".join(cmdline)))
            r = s.wait()
            del s

        so.seek(0)
        # Say what happened
        if r != 0:
            self.log.error("flashing failed")
            m = ""
            with codecs.open(so.name, "r", encoding = 'utf-8') as so_r:
                for line in so_r:
                    line = line.decode('utf-8').strip()
                    self.log.error("flashing output: " + line)
                    m += "flashing output: " + line + "\n"
            raise Exception("Flashing failed\n" + m)
        # Check the log, if it does not say "Verify succesful", it didn't work
        with codecs.open(so.name, "r", encoding = 'utf-8') as so_r:
            m = ""
            for line in so_r:
                line = line.decode('utf-8').strip()
                if line.endswith("Verify successful"):
                    break
                m += "flashing output: " + line + "\n"
            else:
                raise Exception(
                    "Flashing failed (can't find 'Verify syccessful')\n" + m)
        self.log.info("flashing succeeded")
        with codecs.open(so.name, "r", encoding = 'utf-8') as so_r:
            for line in so_r:
                line = line.strip()
                self.log.debug("flashing: " + line)

    def images_do_set(self, images):
        pass


class tt_esp32(
        ttbl.test_target,
        ttbl.tt_power_control_mixin,
        ttbl.cm_serial.cm_serial,
        ttbl.test_target_images_mixin):

    esptool_path = "__unconfigured__tt_esp32.esptool_path__"

    def __init__(self, _id, serial_number,
                 power_control, serial_port):
        """\
        Test target ESP32 Tensilica based MCUs that use the ESP-IDF framework

        :param str _id: name identifying the target

        :param str serial_number: Unique USB serial number of the device (can
          be updated with http://cp210x-program.sourceforge.net/)

        :param power_control: Power control implementation or rail
          (:class:`ttbl.tt_power_control_impl` or list of such)

        :param str serial_port: Device name of the serial port where
          the console will be found. This can be set with udev to be a
          constant name.

        The base code will convert the *ELF* image to the required
        *bin* image using the ``esptool.py`` script. Then it will
        flash it via the serial port.

        *Requirements*

        - The ESP-IDK framework, of which ``esptool.py`` is used to
          flash the target; to install::

            $ cd /opt
            $ git clone --recursive https://github.com/espressif/esp-idf.git

          (note the ``--recursive``!! it is needed so all the
          submodules are picked up)

          configure path to it globally by setting
          :attr:`esptool_path` in a /etc/ttbd-production/conf_*.py file:

          .. code-block:: python

             import ttbl.tt
             ttbl.tt.tt_esp32.esptool_path = "/opt/esp-idf/components/esptool_py/esptool/esptool.py"

          Note you will also most likely need this in the client to
          compile code for the board.

        - Permissions to use USB devices in */dev/bus/usb* are needed;
          *ttbd* usually roots with group *root*, which shall be
          enough.

        - Needs power control for proper operation; FIXME: pending to
          make it operate without power control, using ``esptool.py``.
        """
        assert isinstance(_id, basestring)
        assert isinstance(serial_number, basestring)
        assert isinstance(power_control, ttbl.tt_power_control_impl) \
            or isinstance(power_control, list)

        self.serial_number = serial_number

        ttbl.test_target.__init__(self, _id)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        ttbl.test_target_images_mixin.__init__(self)
        self.serial_port = serial_port
        ttbl.cm_serial.cm_serial.__init__(
            self, self.state_dir,
            [
                "pc",
                { 'port': serial_port, 'baudrate': 115200 }
            ])

    def images_do_set(self, images):
        # We implement image_do_set(), as there is only one image to set
        pass


    def image_do_set(self, image_type, image_name):
        """Just validates the image types are ok. The flashing happens in
        images_do_set().

        :param str image_type: Type of the image supported
        :param str image_name: Name of image file in the daemon
          storage space for the user
        :raises: Any exception on failure

        """
        cmdline_convert = [
            self.esptool_path,
            "--chip", "esp32",
            "elf2image",
        ]
        cmdline_flash = [
            self.esptool_path,
            "--chip", "esp32",
            "--port", self.serial_port,
            "--baud", "921600",
            "--before", "default_reset",
            "write_flash", "-u",
            "--flash_mode", "dio",
            "--flash_freq", "40m",
            "--flash_size", "detect",
            "0x1000",
        ]

        if image_type == "kernel":
            image_type = "kernel-xternsa"
        if not image_type.startswith("kernel-"):
            raise RuntimeError(
                "Unknown image type '%s' (valid: kernel-{%s})"
                % (image_type, ",".join(self.tags['bsps'].keys())))
        image_name_bin = image_name + ".bin"
        try:
            cmdline = cmdline_convert + [ image_name,
                                          "--output", image_name_bin ]
            self.log.info("converting with %s" % " ".join(cmdline))
            s = subprocess.check_output(cmdline, cwd = "/tmp",
                                        stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            self.log.error("converting image with %s failed: (%d) %s"
                           % (" ".join(cmdline), e.returncode, e.output))
            raise

        self._power_cycle_do()
        with self.console_takeover():	# give up the serial port
            try:
                cmdline = cmdline_flash + [ image_name_bin ]
                self.log.info("flashing with %s" % " ".join(cmdline))
                s = subprocess.check_output(cmdline, cwd = "/tmp",
                                            stderr = subprocess.STDOUT)
                self.log.info("flashed with %s: %s" % (" ".join(cmdline), s))
            except subprocess.CalledProcessError as e:
                self.log.error("flashing with %s failed: (%d) %s"
                               % (" ".join(cmdline), e.returncode, e.output))
                raise
        self._power_off_do()
        self.log.info("flashing succeeded")


class tt_flasher(
        ttbl.test_target,
        ttbl.test_target_images_mixin,
        ttbl.tt_power_control_mixin,
        ttbl.tt_debug_mixin,
        ttbl.cm_serial.cm_serial):

    class error(RuntimeError):
        pass

    def __init__(self, _id, serial_ports,
                 flasher, power_control):
        """Test target flashable, power switchable with debuggin

        Any target which supports the :class:`ttbl.flasher.flasher_c`
        interface can be used, mostly OpenOCD targets.

        How we use this, is for example:

        >>> flasher_openocd = ttbl.flasher.openocd_c("frdm_k64f", FRDM_SERIAL,
        >>>                                          openocd10_path, openocd10_scripts)
        >>> ttbl.config.target_add(
        >>>     ttbl.tt.tt_flasher(
        >>>         NAME,
        >>>         serial_ports = [
        >>>             "pc",
        >>>             dict(port = "/dev/tty-NAME", baudrate = 115200)
        >>>         ],
        >>>         flasher = flasher_obj,
        >>>         power_control = [
        >>>             ttbl.pc_ykush.ykush(YKUSH_SERIAL, YKUSH_PORT)
        >>>             # delay until device comes up
        >>>             ttbl.pc.delay_til_usb_device(FRDM_SERIAL),
        >>>             ttbl.cm_serial.pc(),	# Connect serial ports
        >>>             flasher_openocd,        # Start / stop OpenOCD
        >>>         ]
        >>>     ),
        >>>     tags = {
        >>>         'bsp_models' : { 'arm': None },
        >>>         'bsps' : {
        >>>             "arm":  dict(board = "frdm_k64f", kernelname = 'zephyr.bin',
        >>>                          kernel = [ "micro", "nano" ],
        >>>                          console = "", quark_se_stub = "no"),
        >>>         },
        >>>         'slow_flash_factor': 5,	# Flash verification slow
        >>>         'flash_verify': 'False',    # Or disable it ...
        >>>     },
        >>>     target_type = "frdm_k64f")

        .. note: the power for this target is a normal power control
                 implementation, HOWEVER, the power rail also contains
                 the OpenOCD flasher to start/stop the daemon once the
                 board is powered up.

        :param str _id: target name

        :param serial_ports: list of serial port dictionaries,
          specified as for :func:`serial.serial_for_url` with a couple
          of extras as specified in :class:`ttbl.cm_serial`.

        :param ttbl.flasher.flasher_c flasher: flashing object that
          provides access to deploy images and debug control

        :param power_control: an instance of an implementation
          of the power_control_mixin used to implement power control for
          the target. Use ttbl.pc.manual() for manual power control that
          requires user interaction.

        """
        ttbl.test_target.__init__(self, _id)
        ttbl.test_target_images_mixin.__init__(self)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        ttbl.tt_debug_mixin.__init__(self)
        ttbl.cm_serial.cm_serial.__init__(self, self.state_dir, serial_ports)
        self.flasher = flasher
        self.flasher.test_target_link(self)
        self.power_on_post_fns.append(self.power_on_do_post)
        self.power_off_pre_fns.append(self.power_off_do_pre)

    # Debugging interface
    #
    # We don't do much other than resuming the target if we stop
    # debugging
    def debug_do_start(self, tt_ignored):
        pass

    def debug_do_halt(self, _):
        if self.flasher:
            self.flasher.target_halt(for_what = "debug_halt")

    def debug_do_reset(self, _):
        if self.flasher:
            self.flasher.target_reset_halt(for_what = "debug_reset")

    def debug_do_reset_halt(self, _):
        if self.flasher:
            self.flasher.target_reset_halt(for_what = "debug_reset_halt")

    def debug_do_resume(self, _):
        if self.flasher:
            self.flasher.target_resume(for_what = "debug_resume")

    def debug_do_stop(self, _):
        if self.flasher:
            self.flasher.target_resume()

    def debug_do_info(self, _):
        # FIXME: self.flasher should be providing this information, this
        # is breaking segmentation
        count = 2   # port #0 is for telnet, #1 for TCL
        tcp_port_base_s = self.fsdb.get("openocd.port")
        if tcp_port_base_s == None:
            return "Debugging information not available, power on?"
        tcp_port_base = int(tcp_port_base_s)
        s = "OpenOCD telnet server: %s %d\n" \
            % (socket.getfqdn('0.0.0.0'), tcp_port_base)
        for target in self.flasher.board['targets']:
            s += "GDB server: %s: tcp:%s:%d\n" % (target,
                                                  socket.getfqdn('0.0.0.0'),
                                                  tcp_port_base + count)
            count +=1
        if self.fsdb.get('powered') != None:
            s += "Debugging available as target is ON"
        else:
            s += "Debugging not available as target is OFF"
        return s

    def debug_do_openocd(self, _, command):
        return self.flasher.openocd_cmd(command)

    # Wrap actual reset with retries
    def target_reset_halt(self, for_what = ""):
        tries = 1
        tries_max = 2
        # FIXME: current limitation, can't access the tags from the
        # constructor as the ones we add in target_add() aren't there
        # yet.
        wait = \
            float(self.tags.get('hard_recover_rest_time', 2))
        while tries <= tries_max:
            # The Arduino101 get's so stuck sometimes
            try:
                self.flasher.target_reset_halt(for_what)
                break
            except self.flasher.error:
                pass
            try_s = "%d/%d" % (tries, tries_max)
            time.sleep(2)
            try:
                self.flasher.target_reset("[recover reset #1 %s] " % try_s
                                          + for_what)
            except self.flasher.error:
                pass
            try:
                self.flasher.target_reset_halt("[retry %s] " % try_s
                                               + for_what)
                break
            except self.flasher.error:
                pass
            # In some targets, this fails because maybe we just
            # power-cycled and the JTAG said it was ready but it
            # is really not ready...when that happens, just
            # power-cycle again.
            # well, that didn't work either; bring the big guns,
            # power cycle it and try the whole thing again
            wait_s = (1 + 2.0 * tries/tries_max) * wait
            self.log.info("Failed to reset/halt, power-cycle (%.2fs) "
                          "and retrying (try %d/%d)"
                          % (wait_s, tries, tries_max))
            self.power_cycle(self.owner_get(), wait_s)
            tries += 1
        else:
            # FIXME: pass the exception we get or the log or something
            raise self.error("Can't reset/halt the target")

    def target_reset(self, for_what = ""):
        tries = 1
        tries_max = 5
        # FIXME: current limitation, can't access the tags from the
        # constructor as the ones we add in target_add() aren't there
        # yet.
        wait = \
            float(self.tags.get('hard_recover_rest_time', 10))
        while tries <= tries_max:
            # The Arduino101 get's so stuck sometimes
            try:
                self.flasher.target_reset(for_what)
                break
            except self.flasher.error:
                pass
            # Try again
            try:
                self.flasher.target_reset(for_what)
                break
            except self.flasher.error:
                pass
            # Bring the big guns, power cycle it
            if wait != None:
                wait_s = tries * wait
                self.log.info("Failed to reset/run, power-cycle (%.2fs) "
                              "and retrying (try %d/%d)"
                              % (wait_s, tries, tries_max))
                self.power_cycle(self.owner_get(), wait_s)
                tries += 1
        else:
            # FIXME: pass the exception we get or the log or something
            raise self.error("Can't reset/run the target")

    # Power interface
    #
    # Fire up the flasher when we power the target up, so it can
    # access the JTAG


    def power_on_do_post(self):
        self.flasher.start()

    def power_off_do_pre(self):
        self.flasher.stop()

    def reset_do(self, _):
        # We halt first so we can stop recording from the serial ports
        # and then restart wihout getting any trash; we use reset_halt
        # because it is a single command for all targets (halt needs
        # to select each target).
        self.flasher.target_reset_halt()
        self.consoles_reset()
        # When we reset, if we are debugging we need to halt the target as
        # soon as it starts. Otherwise, we reset it normally. These
        # are atomic (they act on all the targets at the same time..in
        # theory)
        if self.fsdb.get("debug") != None:
            self.flasher.target_reset_halt()
        else:
            self.flasher.target_reset()

    # Flashing interface -- quite simple, we need the target on and
    # then just flash the image in.
    def image_do_set(self, image_type, image_name):
        pass

    def images_do_set(self, images):
        # FIXME: current limitation, can't access the tags from the
        # constructor as the ones we add in target_add() aren't there
        # yet.
        wait = \
            float(self.tags.get('hard_recover_rest_time', 10))
        if self.fsdb.get("disable_power_cycle_before_flash") != 'True':
            # Make sure the target is really fresh before flashing it
            try:
                # See the documentation for this on class flasher_c
                # for why we have to do it.
                self.flasher.hack_reset_after_power_on = True
                self.power_cycle(self.owner_get(), wait = wait)
            finally:
                self.flasher.hack_reset_after_power_on = False
            self.log.info("sleeping 2s after power cycle")
            # HACK: For whatever the reason, we need to sleep before
            # resetting/halt, seems some of the targets are not ready
            # inmediately after
            time.sleep(2)
        self.target_reset_halt(for_what = "for image flashing")
        timeout_factor = self.tags.get('slow_flash_factor', 1)
        verify = self.tags.get('flash_verify', 'True') == 'True'
        # FIXME: replace this check for verifying which image types
        # the flasher supports
        for t, n in images.iteritems():
            if t == "kernel-x86":
                it = "x86"
            elif t == "kernel":
                it = "x86"
            elif t == "kernel-arc":
                it = "arc"
            elif t == "kernel-arm":
                it = "arm"
            elif t == "rom":
                it = "rom"
            elif t == "bootloader":
                it = "bootloader"
            else:
                raise self.unsupported_image_e(
                    "%s: Unknown image type (expected "
                    "kernel|kernel-(x86,arc,arm), rom)"
                    % t)
            try:
                self.flasher.image_write(it, n, timeout_factor, verify)
            except ValueError as e:
                self.log.exception("flashing got exception: %s", e)
                raise self.unsupported_image_e(e.message)

class tt_dfu(
        ttbl.test_target,
        ttbl.tt_power_control_mixin,
        ttbl.cm_serial.cm_serial,
        ttbl.test_target_images_mixin):

    def __init__(self, _id, serial_number,
                 power_control, power_control_board,
                 serial_ports = None):
        """Test target for a flashable with DFU Utils

        *Requirements*

        - Needs a connection to the USB port that exposes a DFU
          interface upon boot

        - Uses the dfu-utils utility, available for most (if not all)
          Linux distributions

        - Permissions to use USB devices in */dev/bus/usb* are needed;
          *ttbd* usually roots with group *root*, which shall be
          enough.

        - Needs power control for proper operation

        :param str _id: name identifying the target

        :param power_control: Power control implementation or rail
          (:class:`ttbl.tt_power_control_impl` or list of such)

        :param ttbl.tt_power_control_impl power_control: power controller
          *just* for the board--this is the component in the power
          control rail that controls the board only (versus other
          parts such as serial ports or pseudo-power-controllers that
          wait for the USB device to pop up.

        Note the tags to the target must include, on each supported
        BSP, a tag named *dfu_interface_name* listing the name of the
        *altsetting* of the DFU interface to which the image for said
        BSP needs to be flashed.

        This can be found, when the device exposes the DFU interfaces
        with the *lsusb -v* command; for example, for a tinyTILE
        (output summarized for clarity)::

          $ lsusb -v
          ...
          Bus 002 Device 110: ID 8087:0aba Intel Corp.
          Device Descriptor:
            bLength                18
            bDescriptorType         1
            ...
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update...
                iInterface              4 x86_rom
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update...
                iInterface              5 x86_boot
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update
                iInterface              6 x86_app
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update
                iInterface              7 config
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update
                iInterface              8 panic
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update
                iInterface              9 events
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update
                iInterface             10 logs
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update
                iInterface             11 sensor_core
              Interface Descriptor:
                bInterfaceClass       254 Application Specific Interface
                bInterfaceSubClass      1 Device Firmware Update
                iInterface             12 ble_core

        In this case, the three cores available are x86 (x86_app), arc
        (sensor_core) and ARM (ble_core).

        *Example*

        A Tiny Tile can be connected, without exposing a serial console:

        >>> pc_board = ttbl.pc_ykush.ykush("YK22909", 1)
        >>>
        >>> ttbl.config.target_add(
        >>>     tt_dfu("ti-01",
        >>>            serial_number = "5614010001031629",
        >>>            power_control = [
        >>>                pc_board,
        >>>                ttbl.pc.delay_til_usb_device("5614010001031629"),
        >>>            ],
        >>>            power_control_board = pc_board),
        >>>     tags = {
        >>>         'bsp_models': { 'x86+arc': ['x86', 'arc'], 'x86': None, 'arc': None},
        >>>         'bsps' : {
        >>>             "x86":  dict(zephyr_board = "tinytile",
        >>>                          zephyr_kernelname = 'zephyr.bin',
        >>>                          dfu_interface_name = "x86_app",
        >>>                          console = ""),
        >>>             "arm":  dict(zephyr_board = "arduino_101_ble",
        >>>                          zephyr_kernelname = 'zephyr.bin',
        >>>                          dfu_interface_name = "ble_core",
        >>>                          console = ""),
        >>>             "arc": dict(zephyr_board = "arduino_101_sss",
        >>>                         zephyr_kernelname = 'zephyr.bin',
        >>>                         dfu_interface_name = 'sensor_core',
        >>>                         console = "")
        >>>         },
        >>>
        >>>     },
        >>>     target_type = "tile"
        >>> )

        """
        assert isinstance(_id, basestring)
        assert isinstance(serial_number, basestring)
        assert isinstance(power_control, ttbl.tt_power_control_impl) \
            or isinstance(power_control, list)

        self.serial_number = serial_number
        self.pc_board = power_control_board
        self.pc_usb = ttbl.pc.delay_til_usb_device(serial_number)

        ttbl.test_target.__init__(self, _id)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        ttbl.test_target_images_mixin.__init__(self)
        ttbl.cm_serial.cm_serial.__init__(self, self.state_dir, serial_ports)

    def images_do_set(self, images):
        """Just validates the image types are ok. The flashing happens in
        images_do_set().

        :param str image_type: Type of the image supported
        :param str image_name: Name of image file in the daemon
          storage space for the user
        :raises: Any exception on failure

        """

        # Power cycle the board so it goes into DFU mode; it then
        # stays there for five seconds
        self.pc_board.power_cycle_raw(self, 5)
        self.pc_usb.power_on_do(self)

        cmdline = [
            "/usr/bin/dfu-util",
            "-S", self.serial_number
        ]
        for image_type, image_name in images.iteritems():
            if image_type == "kernel":
                image_type = "kernel-x86"
            if not image_type.startswith("kernel-"):
                raise RuntimeError(
                    "Unknown image type '%s' (valid: kernel-{%s})"
                    % (image_type, ",".join(self.tags['bsps'].keys())))
            bsp = image_type[len("kernel-"):]
            tags_bsp = self.tags.get('bsps', {}).get(bsp, None)
            if tags_bsp == None:
                raise RuntimeError(
                    "Unknown BSP %s from image type '%s' (valid: %s)"
                    % (bsp, image_type, " ".join(self.tags['bsps'].keys())))
            dfu_if_name = tags_bsp.get('dfu_interface_name', None)
            if dfu_if_name == None:
                raise RuntimeError(
                    "Misconfigured target: image type %s (BSP %s) has "
                    "no 'dfu_interface_name' key to indicate which DFU "
                    "interface shall it flash"
                    % (image_type, bsp))
            # now write it
            cmdline += [
                "-a", dfu_if_name,
                "-D", image_name,
            ]
        try:
            self.log.info("flashing with %s" % (" ".join(cmdline)))
            s = subprocess.check_output(cmdline, cwd = "/tmp",
                                        stderr = subprocess.STDOUT)
            self.log.info("flashed with %s: %s" % (" ".join(cmdline), s))
        except subprocess.CalledProcessError as e:
            self.log.error("flashing with %s failed: (%d) %s" %
                           (" ".join(cmdline), e.returncode, e.output))
            raise
        self.log.info("flashing succeeded")
        self.pc_board.power_off_do(self)

    def image_do_set(self, t, n):
        pass

class tt_max10(
        ttbl.test_target,
        ttbl.tt_power_control_mixin,
        ttbl.cm_serial.cm_serial,
        ttbl.test_target_images_mixin):
    """
    Test target for an Altera MAX10

    This allows to flash images to an Altera MAX10, using the Quartus
    tools, freely downloadable from http://dl.altera.com.

    Exports the following interfaces:

    - power control (using any AC power switch, such as the
      :class:`Digital Web Power Switch 7 <ttbl.pc.dlwps7>`)
    - serial console
    - image (in hex format) flashing (using the Quartus Prime tools
      package)

    Multiple instances at the same time are supported; however, due to
    the JTAG interface not exporting a serial number, addressing has
    to be done by USB path, which is risky (as it will change when the
    cable is plugged to another port or might be enumerated in a
    different number).

    Note that:

    - when flashing LED1 blinks green/blue

    - the blue power switch must be pressed, to ensure the board is
      *ON* when we switch the AC power to the power brick on

    - SW2 DIP bank on the back of the board has to be all OFF (down)
      except for 3, that has to be ON (this comes from the Zephyr
      Altera MAX10 configuration)

    - J7 (at the front of the board, next to the coaxial connectors)
      has to be open

    Pending:

    - CPU design hardcoded to use Zephyr's -- it shall be possible to
      flash it
    """

    #: Path where the Quartus Programmer binaries have been installed
    #:
    #: 1. Download Quartus Prime Programmer and Tools from
    #:    http://dl.altera.com/17.1/?edition=lite&platform=linux&download_manager=direct
    #: 2. Install to e.g `/opt/intelFPGA/17.1/qprogrammer/bin`.
    #: 3. Configure in /etc/ttbd-production/conf_00_max10.py::
    #:
    #:    .. code-block: python
    #:
    #:       import ttbl.tt
    #:       ttbl.tt.tt_max10.quartus_path = "/opt/intelFPGA/17.1/qprogrammer/bin"
    quartus_path = "__unconfigured__tt_max10.quartus_path__"

    #: Path to where the NIOS Zephyr CPU image has been installed
    #:
    #: 1. Download the CPU image to `/var/lib/ttbd`::
    #:
    #:      $ wget -O /var/lib/ttbd/ghrd_10m50da.sof \
    #:           https://github.com/zephyrproject-rtos/zephyr/raw/master/arch/nios2/soc/nios2f-zephyr/cpu/ghrd_10m50da.sof
    #:
    #: 3. Configure in /etc/ttbd-production/conf_00_max10.py:
    #:
    #:    .. code-block: python
    #:
    #:       import ttbl.tt
    #:       ttbl.tt.tt_max10.input_sof = "/var/lib/ttbd/ghrd_10m50da.sof"
    input_sof = "__unconfigured__tt_max10.input_sof__"

    def __init__(self, _id, device_id,
                 power_control, serial_port = None):
        assert isinstance(_id, basestring)
        assert isinstance(device_id, basestring)
        assert isinstance(power_control, ttbl.tt_power_control_impl) \
            or isinstance(power_control, list)

        self.device_id = device_id

        ttbl.test_target.__init__(self, _id)
        ttbl.tt_power_control_mixin.__init__(self, power_control)
        ttbl.test_target_images_mixin.__init__(self)
        self.serial_port = serial_port
        if serial_port:
            ttbl.cm_serial.cm_serial.__init__(
                self, self.state_dir,
                [
                    "pc",
                    { 'port': serial_port, 'baudrate': 115200 }
                ])
        else:
            ttbl.cm_serial.cm_serial.__init__(self, self.state_dir, [])

    quartus_cpf_template = """\
<?xml version="1.0" encoding="US-ASCII" standalone="yes"?>
<cof>
	<output_filename>${OUTPUT_FILENAME}</output_filename>
	<n_pages>1</n_pages>
	<width>1</width>
	<mode>14</mode>
	<sof_data>
		<user_name>Page_0</user_name>
		<page_flags>1</page_flags>
		<bit0>
			<sof_filename>${SOF_FILENAME}<compress_bitstream>1</compress_bitstream></sof_filename>
		</bit0>
	</sof_data>
	<version>10</version>
	<create_cvp_file>0</create_cvp_file>
	<create_hps_iocsr>0</create_hps_iocsr>
	<auto_create_rpd>0</auto_create_rpd>
	<rpd_little_endian>1</rpd_little_endian>
	<options>
		<map_file>1</map_file>
	</options>
	<MAX10_device_options>
		<por>0</por>
		<io_pullup>1</io_pullup>
		<config_from_cfm0_only>0</config_from_cfm0_only>
		<isp_source>0</isp_source>
		<verify_protect>0</verify_protect>
		<epof>0</epof>
		<ufm_source>2</ufm_source>
		<ufm_filepath>${KERNEL_FILENAME}</ufm_filepath>
	</MAX10_device_options>
	<advanced_options>
		<ignore_epcs_id_check>2</ignore_epcs_id_check>
		<ignore_condone_check>2</ignore_condone_check>
		<plc_adjustment>0</plc_adjustment>
		<post_chain_bitstream_pad_bytes>-1</post_chain_bitstream_pad_bytes>
		<post_device_bitstream_pad_bytes>-1</post_device_bitstream_pad_bytes>
		<bitslice_pre_padding>1</bitslice_pre_padding>
	</advanced_options>
</cof>
"""

    # XXX Do we care about FileRevision, DefaultMfr, PartName? Do they need
    # to be parameters? So far seems to work across 2 different boards, leave
    # this alone for now.
    quartus_pgm_template = """\
/* Quartus Prime Version 16.0.0 Build 211 04/27/2016 SJ Lite Edition */
JedecChain;
	FileRevision(JESD32A);
	DefaultMfr(6E);

	P ActionCode(Cfg)
		Device PartName(10M50DAF484ES) Path("${POF_DIR}/") File("${POF_FILE}") MfrSpec(OpMask(1));

ChainEnd;

AlteraBegin;
	ChainType(JTAG);
AlteraEnd;"""

    def _create_pof(self, output_pof, input_sof, kernel_hex):
        t = string.Template(self.quartus_cpf_template)
        input_sof = os.path.abspath(input_sof)
        kernel_hex = os.path.abspath(kernel_hex)
        # These tools are very stupid and freak out if the desired filename
        # extensions are used. The kernel image must have extension .hex
        with tempfile.NamedTemporaryFile(dir = self.state_dir,
                                         suffix = ".cof") as temp_xml:
            xml = t.substitute(SOF_FILENAME = input_sof,
                               OUTPUT_FILENAME = output_pof.name,
                               KERNEL_FILENAME = kernel_hex)
            temp_xml.write(xml)
            temp_xml.flush()
            try:
                cmd = [
                    os.path.join(self.quartus_path, "quartus_cpf"),
                    "-c", temp_xml.name
                ]
                subprocess.check_output(cmd)
            except OSError as e:
                raise RuntimeError("Failed to create POF file w/ %s: %s"
                                   % (" ".join(cmd), e))
            except subprocess.CalledProcessError as cpe:
                raise RuntimeError("Failed to create POF file: %s"
                                   % cpe.output.decode("UTF-8"))
        return output_pof


    def images_do_set(self, images):
        # We implement image_do_set(), as there is only one image to set
        pass

    # FIXME: limitation: SOF image is fixed, should be possible to
    # upload it and default to built-in? Problem is we need to fixup
    # the build instructions so they understand they need to upload
    # the SOF too
    # FIXME: also, the SOF is kinda big, 3M
    def image_do_set(self, image_type, image_name):
        if image_type == "kernel":
            image_type = "kernel-max10"
        if not image_type.startswith("kernel-"):
            raise RuntimeError(
                "Unknown image type '%s' (valid: kernel-{%s})"
                % (image_type, ",".join(self.tags['bsps'].keys())))
        self._power_cycle_do()
        # This code snippet lifted from Zephyr's
        # scripts/support/quartus-flash.py -- thx
        # Minimum changes to place files in directories and wipe them
        # upon context exit, match local style .
        # def _flash_kernel(device_id, input_sof, kernel_hex):
        self.log.info("Flashing %s:%s" % (image_type, image_name))
        with tempfile.NamedTemporaryFile(dir = self.state_dir,
                                         suffix = ".pof") as output_pof, \
             tempfile.NamedTemporaryFile(dir = self.state_dir,
                                         suffix = ".hex") as kernel_hex, \
             tempfile.NamedTemporaryFile(dir = self.state_dir,
                                         suffix = ".cdf") as temp_cdf:
            # Apparently, the tools get freaked out by our largish
            # file names, so just make it a temp with a short sweet name
            shutil.copyfile(image_name, kernel_hex.name)
            pof_file = self._create_pof(output_pof, self.input_sof, kernel_hex.name)
            dname, fname = os.path.split(pof_file.name)
            t = string.Template(self.quartus_pgm_template)
            cdf = t.substitute(POF_DIR = dname, POF_FILE = fname)
            temp_cdf.write(cdf)
            temp_cdf.flush()
            try:
                output = subprocess.check_output([
                    os.path.join(self.quartus_path, "quartus_pgm"),
                    "--quiet",
                    "-c", self.device_id,
                    temp_cdf.name
                ])
            except subprocess.CalledProcessError as cpe:
                raise RuntimeError("Failed to flash image: %s"
                                   % cpe.output.decode("UTF-8"))
            self.log.info("Flashed %s:%s; output:\n%s"
                          % (image_type, image_name, output))
        self._power_off_do()
        self.log.info("flashing succeeded")


class grub2elf(tt_serial, ttbl.test_target_images_mixin):
    """Boot anything that can take an ELF image with grub2

    **Overview**

    A platform that can EFI boot off a multiplexed boot USB drive;
    this drive:

    - when connected to the target, acts as boot drive which boots
      into grub2 which multiboots into whatever ELF binary we gave it

    - when connected to the server, we partition, format, install
      grub2 and the ELF kernel to be booted.

    An eight-port USBRLY8 relay bank acting as a USB switcher, each
    relay switching one of the four USB lines from target to server,
    using :class:`ttbl.usbrly08b.plugger`:

    - the USB-A female cable is connected to the C relay terminals

    - the USB-A male cable for the server is connected to the NC relay
      terminals

    - the USB-A male cable for the client is connected to the NO relay
      terminal

    - a target that EFI/boots and can boot off a USB drive

    Limitations:

    - kinda hardcoded x86-64, shall be easy to fix

    **Methodology**

    The power rail for the target ensures that when the target is
    powered on, the USB boot drive is connected to the target by the
    USB multiplexor. When the target is off, the USB boot drive is
    connected to the server.

    The imaging process in :meth:`image_do_set` will make sure the USB
    drive is connected to the server (by powering off the target) and
    then use the helper script ``/usr/share/tcf/setup-efi-grub2-elf.sh``
    to flash the ELF kernel to the drive (as well, will create the
    grub2 boot structure)--for this we need the drive's USB serial
    number and the ELF file  to boot.

    Upon boot, the boot drive will be detected and booted by default,
    as the grub configuration is set to just boot that ELF kernel.

    For cases where BIOS interaction with the console might be
    necessary, a boot coercer can be implemented in the form of a
    power control implementation that in its `power_on_do()` method
    talks to the serial port to do whatever is needed. See for example
    :class:`conf_00_lib.minnowboard_EFI_boot_grub_pc` which does so
    for Minnowboards.

    **Setup**

    - the helper script ``/usr/share/tcf/setup-efi-grub2-elf.sh`` is
      used to partition, configure and setup the USB drive--it
      is run with *sudo* (via the sudo configurations script
      :download:`/etc/sudoers.d/ttbd_sudo <../ttbd/ttbd_sudo>`)

    - The daemon will require specific capabilities for being able to
      run *sudo* (*CAP_SETGID*, *CAP_SETUID*, *CAP_SYS_ADMIN*,
      *CAP_FOWNER*, *CAP_DAC_OVERRIDE*) setup in
      :download:`/etc/systemd/system/ttbd@.service
      <../ttbd/ttbd@.service>`.

    - Ensure the following packages are available in the system:

      * parted
      * dosfstools
      * grub2-efi-x64-cdboot and grub2-efi-x64-modules
      * util-linux

    - Identify the serial number for the USB drive; plug it to a
      machine and issue::

        $ lsblk -o "NAME,SERIAL,VENDOR,MODEL"
        NAME   SERIAL    VENDOR   MODEL
        sdb    AOJROZB8  JetFlash Transcend 8GB
        sdj    76508A8E  JetFlash Transcend 8GB
        ...

      (for this example, ours is *76508A8E*, `/dev/sdj`)

      blank the USB drive (**NOTE!!!** This will destroy the drive's
      contents)::

        $ dd if=/dev/zero of=/dev/sdj

    - Create a power controller

    - Setup the target's BIOS to boot by default off the USB drive

    See :func:`conf_00_lib.minnowboard_add` for an example instantiation.

    """
    def __init__(self, _id,
                 power_controller,
                 usb_drive_serial,
                 usbrly08b_serial, usbrly08b_bank,
                 serial_port,
                 boot_coercer = None):
        power_control = [
            # Ensure the USB dongle is / has been connected to the server
            ttbl.pc.delay_til_usb_device(usb_drive_serial,
                                         when_powering_on = False,
                                         want_connected = True),
            ttbl.usbrly08b.plugger(usbrly08b_serial, usbrly08b_bank),
            # let the dongle power up, otherwise it won't be seen
            ttbl.pc.delay(2),
            ttbl.pc.delay_til_usb_device(usb_drive_serial,
                                         when_powering_on = True,
                                         want_connected = False),
            ttbl.pc.delay(2),		# let USB dongle settle to the target
            ttbl.cm_serial.pc(),		# Let it open and close ports
            power_controller,
            ttbl.pc.delay(2),		# board powers up...
        ]
        # A boot coercer is a PCI that talks to the target to get it to
        # boot right, so it only implements power_on_do() to do that,
        # power_off_do() has only a pass and power_get_do() returns
        # True.
        # This is eg needed if we need to tell the bios to do this, do
        # that -- in the case of Minnowboard, tell the EFI shell to
        # run grub (sometimes).
        if boot_coercer:
            assert isinstance(boot_coercer, ttbl.tt_power_control_impl)
            power_control.append(boot_coercer)
        self.usb_drive_serial = usb_drive_serial
        tt_serial.__init__(
            self,
            _id,
            power_control,
            serial_ports = [
                "pc",
                { "port": serial_port, "baudrate": 115200 }
            ])
        ttbl.test_target_images_mixin.__init__(self)

    image_types_valid = ("kernel", "kernel-x86")

    def image_do_set(self, image_type, image_name):
        if image_type not in self.image_types_valid:
            raise self.unsupported_image_e(
                "%s: image type not supported (valid: %s)"
                % (image_type, ", ".join(self.image_types_valid)))
        # power off the board to flash, this will redirect the USB
        # drive to be connected to the server
        self.power_off(self.owner_get())

        # We don't verify image_name is an ELF file so that we can
        # also use this to flash other stuff and it's up to the Grub
        # bootloader to interpret it.

        # We need an image with a bootloader, we use grub2 and we
        # share the setup-efi-grub2-elf.sh implementation from
        # simics and others
        cmd_path = commonl.ttbd_locate_helper("setup-efi-grub2-elf.sh",
                                              log = self.log)
        # Yeah, sudo ... it kinda sucks, but it is the best way to
        # isolate it -- could run from the daemon, then it'd have too
        # many permissions--nope. file ./ttbd.sudo contains the config
        # to put in /etc/sudoers.d for this to work.
        cmdline = [ "sudo", "-n", cmd_path, self.usb_drive_serial,
                    image_name, "x86_64" ]
        try:
            self.log.debug("flashing with command '%s'" % " ".join(cmdline))
            output = subprocess.check_output(cmdline,
                                             stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as cpe:
            msg = "flashing with command '%s' failed: %s" \
                  % (" ".join(cpe.cmd), cpe.output)
            self.log.error(msg)
            raise RuntimeError(msg)
        self.log.debug("flashed with command '%s': %s"
                       % (" ".join(cmdline), output))

    def images_do_set(self, images):
        # No need to set multiple images at the same time
        pass

class simics(
        ttbl.test_target,
        ttbl.tt_power_control_mixin,
        ttbl.tt_power_control_impl,
        ttbl.test_target_images_mixin,
        ttbl.test_target_console_mixin):
    """
    Driver for a target based on Simics simulation of a platform

    Currently this driver is quite basic and supports only the image
    and console management interfaces:

    - images are only supported as an ELF file that is booted by
      *grub2* when simics boots from a hard disk image generated on
      the fly.

    - the only supported console is a serial output (no input)

    **System setup**

    1. In a configuration file (e.g. */etc/environment*), set the base
       package for Simics::

         SIMICS_BASE_PACKAGE=/opt/simics/5.0/simics-5.0.136

       note that all the packages and extensions installed in there
       must have been registered with the global Simics configuration,
       as it will execute under the user as which the daemon is run
       (usually *ttbd*).

       Note that the installation of Simics and any extra packages
       needed can be done automagically with::

         $ destdir=/opt/simics/5.0
         $ mkdir -p $destdir
         # --batch: no questions asked, just proceed
         # -a: auto select packages and register them
         $ ./install-simics.pl --batch -a --prefix $destdir \\
             package-1000-5.0.136-linux64.tar.gz.aes KEY-1000 \\
             package-1001-5.0.54-linux64.tar.gz.aes  KEY-1001 \\
             package-1010-5.0.59-linux64.tar.gz.aes  KEY-1010 \\
             package-1012-5.0.24-linux64.tar.gz.aes  KEY-1012 \\
             package-2018-5.0.31-linux64.tar.gz.aes  KEY-2018 \\
             package-2075-5.0.50-linux64.tar.gz.aes  KEY-2075

    """
    class error_e(Exception):		# pylint: disable = missing-docstring
        pass

    class simics_start_e(error_e):	# pylint: disable = missing-docstring
        pass

    #: location of the base Simics installation in the file system; by
    #: default this taken from the *SIMICS_BASE_PACKAGE* environment
    #: variable, if it exists; it can also be set in a configuration
    #: file as:
    #:
    #: >>> ttbl.tt.simics.base_package = "/some/path/simics-5.0.136"
    base_package = os.environ.get('SIMICS_BASE_PACKAGE', None)

    def __init__(self, _id, simics_cmds, _tags = None,
                 image_size_mb = 100):
        assert isinstance(_id, basestring)
        assert isinstance(simics_cmds, basestring)
        assert image_size_mb > 0
        if self.base_package == None:
            raise RuntimeError(
                "Simics not yet configured, either define environment "
                "variable SIMICS_BASE_PACKAGE or configuration "
                "ttbl.tt.simics.base_package")
        ttbl.test_target.__init__(self, _id, _tags = _tags)
        ttbl.tt_power_control_mixin.__init__(self)
        ttbl.tt_power_control_impl.__init__(self)
        ttbl.test_target_images_mixin.__init__(self)
        ttbl.test_target_console_mixin.__init__(self)
        self.simics_path = os.path.join(self.base_package, "bin/simics")
        self.simics_check_path = os.path.join(self.base_package,
                                              "linux64/bin/simics-common")
        self.simics_cmds = simics_cmds
        #: Variables that can be expanded in the Simics configuration
        #: script passed as an argument
        self.simics_vars = dict(
            simics_workspace =  os.path.join(self.state_dir,
                                             "simics.workspace"),
            simics_pidfile = os.path.join(self.state_dir, "simics.pid"),
            simics_console = os.path.join(self.state_dir,
                                          "simics-console.read"),
            simics_hd0 = os.path.join(self.state_dir, "simics-hd0.img"),
            simics_hd0_size = image_size_mb,
        )
        self.logfile_name = os.path.join(self.state_dir, "simics.log")
        self.telnet = None
        # FIXME: verify the BSP is kosher? generate command line from it?

    image_types_valid = ( "kernel", "kernel-x86" )

    # Image management interface
    def image_do_set(self, image_type, image_name):
        if image_type not in self.image_types_valid:
            raise self.unsupported_image_e(
                "%s: image type not supported (valid: %s)"
                % (image_type, ", ".join(self.image_types_valid)))
        # power off the target to flash, so in case simics is running
        # on the image/files, it is stopped and we won't conflict /
        # corrupt anything.
        self.power_off(self.owner_get())
        # Remove old image and create a new one, just writing one byte
        # at the end to create a shallow file.
        commonl.rm_f(self.simics_vars['simics_hd0'])
        with open(self.simics_vars['simics_hd0'], "w") as f:
            f.seek(self.simics_vars['simics_hd0_size'] * 1024 * 1024 - 1)
            f.write('0')

        # We don't verify image_name is an ELF file so that we can
        # also use this to flash other stuff and it's up to the Grub
        # bootloader to interpret it.

        # Simics needs an image with a bootloader, we use grub2 and we
        # share the setup-efi-grub2-elf.sh implementation from
        # grub2elf.
        cmd_path = commonl.ttbd_locate_helper("setup-efi-grub2-elf.sh",
                                              log = self.log)
        # Yeah, sudo ... it kinda sucks, but it is the best way to
        # isolate it -- could run from the daemon, then it'd have too
        # many permissions--nope. file ./ttbd_sudo contains the config
        # to put in /etc/sudoers.d for this to work. Also note the
        # systemd configuration requires us to have permission to
        # regain certain capabilities.
        cmdline = [ "sudo", "-n", cmd_path, self.simics_vars['simics_hd0'],
                    image_name, "i386" ]
        try:
            self.log.debug("flashing with '%s'" % " ".join(cmdline))
            output = subprocess.check_output(cmdline,
                                             stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as cpe:
            msg = "flashing with command '%s' failed: %s" \
                  % (" ".join(cpe.cmd), cpe.output)
            self.log.error(msg)
            raise RuntimeError(msg)
        self.log.debug("flashed with command '%s': %s"
                       % (" ".join(cmdline), output))


    def images_do_set(self, images):
        pass

    # power control interface
    def _simics_launch(self, _target):
        # Note this function will be called again if there is a
        # resource conflict because simics will fail to start and
        # _power_on_do() will detect it.
        cmd_file_name = os.path.join(self.state_dir, "commands")
        # clean up old state, but NOT the hd, as we probably created
        # the image with images_do_set() before
        commonl.rm_f(cmd_file_name)
        if self.fsdb.get("debug") != None:	# if debugging, keep log
            commonl.rm_f(self.logfile_name)
        commonl.rm_f(self.simics_vars['simics_console'])
        commonl.rm_f(self.simics_vars['simics_pidfile'])
        try:
            # Create a fresh Simics workspace
            shutil.rmtree(self.simics_vars['simics_workspace'],
                          ignore_errors = True)
            cmdline = [
                os.path.join(self.base_package, "bin/project-setup"),
                "--ignore-existing-files",
                self.simics_vars['simics_workspace'] ]
            self.log.info("creating workspace with %s" % " ".join(cmdline))
            subprocess.check_output(cmdline, shell = False,
                                    stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            self.log.error("failed to create workspace: %s" % e.output)
        except OSError as e:
            self.log.error("failed to create workspace: %s" % e)

        # Write the command script here, in case anything changes in
        # the interpretation of the fields
        simics_console_port = commonl.tcp_port_assigner(1)
        with open(cmd_file_name, "w") as cmd_file:
            simics_vars = dict(self.simics_vars)
            simics_vars['simics_console_port'] = simics_console_port
            cmd_file.write(self.simics_cmds % simics_vars)
        cmdline = [ self.simics_path, "-no-gui" ]
        if self.fsdb.get("debug"):		# if debugging, be verbose
            cmdline += [ "-verbose", "-verbose" ]
        cmdline += [
            "-project", self.simics_vars['simics_workspace'], cmd_file_name
        ]

        # Fire up simics, redirecting all the output (stdout, stderr,
        # traces) to a log file
        logfile = open(self.logfile_name, "ab")
        try:
            env = dict(os.environ)
            env['SIMICS_BASE_PACKAGE'] = self.base_package
            self.log.info("Starting simics with: %s" % " ".join(cmdline))
            p = subprocess.Popen(
                cmdline, shell = False, cwd = self.state_dir, env = env,
                close_fds = True, stdout = logfile, stderr = subprocess.STDOUT)
        except OSError as e:
            raise self.simics_start_e("Simics failed to start: %s" % e)
        with open(self.simics_vars['simics_pidfile'], "w") as pidfilef:
            pidfilef.write("%d" % p.pid)
        pid = commonl.process_started(		# Verify it started
            self.simics_vars['simics_pidfile'],
            self.simics_check_path,
            verification_f = os.path.exists,
            verification_f_args = (self.simics_vars['simics_console'],),
            timeout = 20, tag = "simics", log = self.log)
        if pid == None:
            raise self.simics_start_e("Simics failed to start after 5s")
        self.fsdb.set('simics_console_port', "%d" %
                      simics_console_port)

    def power_on_do(self, target):
        # try to start qemu, retrying if we have to
        for cnt in range(5):
            try:
                self._simics_launch(target)
                break
            except self.error_e:
                with open(self.logfile_name) as logfile:
                    for line in logfile:
                        if 'Address already in use' in line:
                            # Ops, port we took for the console is
                            # taken, try again with another port
                            self.log.info("%d/5: port conflict, trying again"
                                          % cnt)
                            self.power_off_do(target)
                            continue
        else:
            raise RuntimeError("simis: did not start after 5 tries")

    def power_off_do(self, _target):
        self.fsdb.set('simics_console_port', None)
        commonl.process_terminate(self.simics_vars['simics_pidfile'],
                                  tag = "simics",
                                  path = self.simics_check_path)

    def power_get_do(self, _target):
        pid = commonl.process_alive(self.simics_vars['simics_pidfile'],
                                    self.simics_check_path)
        return pid != None

    # Console mixin
    # Any file SOMETHING-console.read describes a console that is available.
    def console_do_list(self):
        consoles = []
        for filename in os.listdir(self.state_dir):
            if filename.endswith("-console.read"):
                console_name = filename[:-len("-console.read")]
                consoles.append(console_name)
        return consoles

    def console_do_read(self, console_id = None, offset = 0):
        if console_id == None:
            console_id = 'simics'
        if console_id != 'simics':
            raise RuntimeError("console ID '%s' not found" % console_id)
        # Reading is simple -- simics pipes all the output to a file
        # called simics-console.read
        consolefname = os.path.join(self.state_dir,
                                    "%s-console.read" % console_id)
        if os.path.isfile(consolefname):
            # don't open codecs.open() UTF-8, as that will trip Flask
            # when passing the generator up to serve to the client
            ifd = open(consolefname, "rb")
            if offset > 0:
                ifd.seek(offset)
            return ifd
        else:
            return iter(())

    def console_do_write(self, _data, _console_id = None):
        _simics_console_port = self.fsdb.get('simics_console_port')
        if _simics_console_port == None:
            raise RuntimeError("target is off, cannot write to it")
        simics_console_port = int(_simics_console_port)

        # re-create it for every write -- yeah, overkill, but this
        # runs across multiple servers, so we don't know if it was
        # power cycled and thus the port is still valid/open..
        # FIXME: hack, should cache
        telnet = telnetlib.Telnet('127.0.0.1', simics_console_port)

        # KLUDGE, workaround
        # So this C-like loop (because I want it to be clearer
        # than hidden iterator pythonic stuff) it is chunking
        # the data to be sent to the VM's serial console
        # and doing a short sleep in between. Why?
        # Because by observation we've seen data being lost
        # when sending it to the sock that represents the
        # input. Chunking it up and giving it a breather
        # alleviated it.
        chunk_size = 8
        count = 0
        l = len(_data)
        while l > 0:
            if l >= chunk_size:
                chunk_data = _data[count:count + chunk_size]
            else:
                chunk_data = _data[count:count + l]
            # FIXME: I seriously don't have any idea of what am I doing
            #        here; this Python2 string decoding/encoding stuff is
            #        utterly confusing -- but this is how it works :/
            telnet.write(chunk_data.decode('latin1').encode('utf-8'))
            time.sleep(0.15)
            l -= chunk_size
            count += chunk_size
