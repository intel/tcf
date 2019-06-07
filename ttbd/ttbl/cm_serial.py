#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import contextlib
import os

from . import cm_logger
import ttbl

# FIXME: move to console/serial or something more consistent
class cm_serial(ttbl.test_target_console_mixin):
    """Implement console/s over serial ports or network connections using
    the Python serial module

    The consoles maybe be open right after power on (if the target
    supports the power-on interface) and closed right before power off
    -- this is needed for device nodes that are powered off AT the
    same time as the target.
    This also means that you can loose console output from the time
    the target is powered on until the serial port is attached to the
    system.
    """

    def consoles_close(self):
        # Tell the logger process to stop logging
        for console in list(self.consoles.keys()):
            logfile_name = os.path.join(self.state_dir,
                                        "console-%s.log" % console)
            cm_logger.spec_rm(logfile_name)

    def consoles_open(self):
        """
        Open all serial ports assigned to the target
        """
        # Tell the logger process to start logging
        for console_id in list(self.consoles.keys()):
            logfile_name = os.path.join(self.state_dir,
                                        "console-%s.log" % console_id)
            cm_logger.spec_add(logfile_name, self.consoles[console_id])

    def consoles_reset(self):
        """
        Truncate all the logfiles (usually called when running a reset)
        """
        for console_id in list(self.consoles.keys()):
            logfile_name = os.path.join(self.state_dir,
                                        "console-%s.log" % console_id)
            cm_logger.spec_reset(logfile_name)

    def __init__(self, state_dir, specs):
        """FIXME

        :param dict specs: list of serial ports or dictionaries
          describing how to open serial ports

          - string "post-open": the serial ports have to be open after
            the target powers up.

            This is needed for ports whose power is tied to the
            target's power (thus, when the target is off, the port is
            gone).

            NOTE: you will lose serial output since
            the time the target is powered up until the serial port
            starts being monitored.

          - string "pc": there is a power-control unit (cm_serial.pc)
            tied to the power-control rail for this target that will
            turn ports on and off.

            This is needed for ports whose power is tied to the
            target's power (thus, when the target is off, the port is
            gone).

            NOTE: you will lose serial output since the time the
            target is powered up until the serial port starts being
            monitored.

          - A dictionary describing how to open a serial port eg::

              {
                  "port": DEVNAME,
                  "console" : CONSOLENAME,
                  "baudrate": 115200,
                  "bytesize": EIGHTBITS,
                  "parity": PARITY_NONE,
                  "stopbits": STOPBITS_ONE,
                  "timeout": 2,
                  "rtscts": True,
              }

          see the documentation for :py:mod:`serial` for more
          information as the elements on this dictionary would match
          the keyword arguments to :func:`serial.serial_for_url`.

          Note ``console`` is the name of the console associated to
          this port; the first one registered is always considered the
          default and assigned the name "default" if none given.

        :param bool save_log: shall the server record anything that
          comes through this serial port?
        """
        self.state_dir = state_dir
        self.consoles = {}
        ttbl.test_target_console_mixin.__init__(self)
        do_open = True
        count = -1
        self.console_default = None
        for spec in specs:
            count += 1
            if spec == "pc":
                # The serial ports will be open after powering on using a
                # hack power-control class (ttbl.cm_serial.pc)--link the
                # power control implementation ttbl.cm_serial.pc object to
                # this class.
                if not isinstance(self, ttbl.tt_power_control_mixin):
                    raise Exception("serial ports requested to be open "
                                    "after power up with power control "
                                    "implementation, but target does not "
                                    "support power control interface")
                do_open = False
            elif isinstance(spec, dict):
                if 'console' in spec:
                    console_name = spec.pop('console')
                else:
                    console_name = "%d" % count
                if self.console_default == None:
                    self.console_default = console_name
                self.consoles[console_name] = spec
            else:
                raise TypeError("Do not know how to handle '%s'" % spec)
        if do_open:
            self.consoles_open()

    def __del__(self):
        self.consoles_close()

    # Console mixin
    def console_do_list(self):
        return list(self.consoles.keys())

    def console_do_read(self, console_id = None, offset = 0):
        if console_id == None:
            console_id = self.console_default
        logfile_name = os.path.join(self.state_dir,
                                    "console-%s.log" % console_id)
        ifd = open(logfile_name, "rb")
        self.log.log(6, "DEBUG: reading from %s @%d (len %d)",
                     logfile_name, offset, ifd.tell())
        if offset > 0:
            ifd.seek(offset)
        return ifd

    def console_do_size(self, console_id = None):
        if console_id == None:
            console_id = self.console_default
        logfile_name = os.path.join(self.state_dir,
                                    "console-%s.log" % console_id)
        return os.stat(logfile_name).st_size

    def console_do_write(self, data, console_id = None):
        if console_id == None:
            console_id = self.console_default
        logfile_name = os.path.join(self.state_dir,
                                    "console-%s.log" % console_id)
        cm_logger.spec_write(logfile_name, data = data)

    @contextlib.contextmanager
    def console_takeover(self, console_id = None):
        """
        Indicate the console serial background port reading thread
        that it has to stop reading from the port.

        >>> with object.console_takeover(CONSOLEID) as descr, log:
        >>>   # ... operate the descr serial object and log file

        When the with statement is left, the background reader takes
        control of the port again.
        """
        if console_id == None:
            console_id = self.console_default
        logfile_name = os.path.join(self.state_dir,
                                    "console-%s.log" % console_id)
        try:
            cm_logger.spec_rm(logfile_name)
            yield self.consoles[console_id], logfile_name
        finally:
            cm_logger.spec_add(logfile_name, self.consoles[console_id])


class pc(ttbl.tt_power_control_impl):
    """
    Treat taget's serial ports like a *power controller* so that it is
    opened when the power control object is powering up all the power
    control implementations that give power to a target.

    This is used when a serial port adapter has to be powered up
    before powering up the target it is connected to. The power
    control implementation would be a list of three objects:

      - power control implementation for the serial port
      - this object
      - power control implementation for the tatrget
    """
    # Note we don't store the power state, as it follows that of the
    # main target. We just return it as the same as the target's
    def __init__(self):
        ttbl.tt_power_control_impl.__init__(self)
        self.powered = False

    def power_on_do(self, target):
        target.log.debug("serial ports power on / start")
        target.consoles_open()
        self.powered = True

    def power_off_do(self, target):
        self.powered = False
        target.log.debug("serial ports power off / stop")
        target.consoles_close()

    def power_get_do(self, target):
        return self.powered
