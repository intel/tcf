#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Drivers for Noyito hardware
---------------------------

Noyito is just a brand name for stuff manufactured by
http://www.chinalctech.com/cpzx/Programmer/AD_DA_Module/68.html.


"""

import logging
import os
import subprocess
import sys

import serial

import commonl
import ttbl._install
import ttbl.capture
import ttbl.power



class mux_pc(ttbl.power.daemon_c):
    """Implement a multiplexor to read Noyitos' serial port to multiple users

    Noyito reports at 2 Hz the value of all the channels on the serial
    port; we will have multiple capturers, belonging to different
    users, taking its output.

    This multiplexor with *ncat* takes the serial port output and pipes
    it to a Unix domain socket.

    - use ncat because if there is no readers in the domain socket, it
      doesn't even open the serial port

    - supports N readers without conflicts or buffering issues.

    This allows then creating another capture device
    :class:`channel_c`, which just takes the data from a single
    channel (to enforce separation betwene users pullign data from
    separate channels).

    **Target setup**

    This has to be added to the targets's power rail as an explicit
    off component:

    >>> target.interface_impl_add(
    >>>     "power",
    >>>     "data_acquisition_1",
    >>>     ttbl.noyito.mux_pc(
    >>>         "/dev/serial/by-path/pci-0000:00:14.0-usb-0:3.1.6:1.0-port0",
    >>>         explicit = "off"
    >>>     )
    >>> )

    :param str device_spec: device to attach to; see
      :class:`ttbl.device_resolver_c`

      Unfortunately, it lacks a serial number to ease up multiple
      devices. See :class:`ttbl.device_resolver_c` to map
      based on other devices with a USB serial #, eg:

      >>> "usb,#200443183011BA51985F,##_1:1.0"

      meaning: use a device with USB serial number
      *200443183011BA51985F* as reference; go one level up (_) in it's
      BUS device path (eg: from 13-1.4.3.2 to 13-1.4.3) and add *.1:1.0*
      to it (13-1.4.3.1:1.0) -- this works when we don't move devices
      in the hubs and basically says "use the Noyito that is in port 1
      of the hub where this other device is".

      Note the USB Vendor and Product IDs are 1a86:7523, thus to match any:

      >>> "usb,idVendor=1a86,idProduct=7523,##:1.0"

      note we need to specify the interface (:1.0)

    """

    def __init__(self, device_spec, **kwargs):
        assert isinstance(device_spec, str)

        ttbl.power.daemon_c.__init__(
            self,
            cmdline = [
                "/usr/bin/ncat",
                "--listen", "--keep-open",
                "-U", '%(path)s/%(component)s-ncat.socket'
            ],
            check_path = "/usr/bin/ncat",
            **kwargs)
        self.stdin = None
        self.device_spec = device_spec
        self.upid_set("Noyito 12-bit 10 channel ADC",
                      device_spec = device_spec)


    def on(self, target, component):
        # open serial port to set the baud rate, then ncat gets
        # started and it keeps the setting; default is 9600 8n1 no
        # flow control, so we explicitly set what the device needs 115200.
        device_resolver = ttbl.device_resolver_c(
            target, self.device_spec,
            f"instrumentation.{self.upid_index}.device_spec")
        tty_dev = device_resolver.tty_find_by_spec()
        with serial.Serial(tty_dev, 115200) as f:
            self.stdin = f
            kws = dict()
            kws['name'] = 'ncat'
            kws['component'] = component
            kws['path'] = target.kws['path']
            commonl.rm_f(os.path.join(target.state_dir,
                                      f"{component}-ncat.socket"))
            ttbl.power.daemon_c.on(self, target, component)


    def verify(self, target, component, cmdline_expanded):
        kws = dict()
        kws['name'] = 'ncat'
        kws['component'] = component
        kws['path'] = target.kws['path']
        return commonl.process_alive(self.pidfile % kws, self.check_path) != None



class channel_c(ttbl.power.daemon_c, ttbl.capture.impl_c):

    def __init__(self, channels: dict,
                 mux_component: str = None, mux_obj: mux_pc = None,
                 device_spec: str = None,
                 power_kwargs: dict = None, **kwargs):
        """
        Data capturer for NOYITO USB 10-Channel 12-Bit AD Data Acquisition
        Module AKA (STM32 UART Communication USB to Serial Chip CH340
        ADC Module)

        - http://www.chinalctech.com/cpzx/Programmer/AD_DA_Module/68.html

        Two operating models:

        - non-multiplexed: only one capturer will access the device;
          specify only *device_spec*

        - multiplexed: multiple capturers will use the device

          Instantiate a multiplexor, add it to the power rail and pass
          arguments *mux_component* and *mux_obj* to this class.


        The full driver sollution consists of:

        - a power-rail component :class:`mux_pc` that
          starts a multiplexor so multiple readers can get the serial
          output--this is needed when multiple capturers will sample
          from the same device

        - for each group of signals that wants to be captured, a
          class:`channel_c` capturer has to be instantiated and added
          to the capture inteface.

        - the :file:`../noyito-capture.py` script, which actuall talks
          to the device to capture the data (see below for details on
          the data format).

        :param dict channels: dictionary keyed by channel number (0-9)
          describing the parameters for each channel; the values are
          another dictionary with the following fields:

          - *name*: string describing a name for this channel
            (optional, defaults to the channel number))

          - *mode*: string describing the operation mode (bool, onoff,
            voltages)

          - *cutoff*: (for bool, onoff) under what voltage it is
            considered *false* or *off*

            >>>  {
            >>>      3: { "mode": "bool", "cutoff": 1.2, },
            >>>      4: { "mode": "onoff", "name": "flip", "cutoff": 2.2, },
            >>>      5: { "mode": "voltages", "name": "level", },
            >>>  },

        :param str mux_component: power component we need to start
          to get the multiplexor working

        :param str mux_component: multiplexor object

        :param str device_spec: device to attach to; see
          :class:`ttbl.device_resolver_c`

          Unfortunately, it lacks a serial number to ease up multiple
          devices. See :class:`ttbl.device_resolver_c` to map
          based on other devices with a USB serial #, eg:

          >>> "usb,#200443183011BA51985F,##_1:1.0"

          meaning: use a device with USB serial number
          *200443183011BA51985F* as reference; go one level up (_) in it's
          BUS device path (eg: from 13-1.4.3.2 to 13-1.4.3) and add *.1:1.0*
          to it (13-1.4.3.1:1.0) -- this works when we don't move devices
          in the hubs and basically says "use the Noyito that is in port 1
          of the hub where this other device is".

          Note the USB Vendor and Product IDs are 1a86:7523, thus to match any:

          >>> "usb,idVendor=1a86,idProduct=7523,##:1.0"

          note we need to specify the interface (:1.0)

        **Examples**

        Multiplexed mode:

        >>> ttbl.config.target_add(target, target_type = "example", tags = {})
        >>>
        >>> data_mux_1 = ttbl.noyito.mux_pc("usb,#200443183011BA51985F,##_2:1.0",
        >>>                                 explicit = "off")
        >>>
        >>> target.interface_add("power",
        >>>                      ttbl.power.interface(data_mux_1 = data_mux_1))
        >>>
        >>> target.interface_add("store", ttbl.config._iface_store)
        >>>
        >>> target.interface_add(
        >>>     "capture",
        >>>     ttbl.capture.interface(
        >>>         ad = ttbl.noyito.channel_c(
        >>>             {
        >>>                 3: { "mode": "bool", "name": "redled", "cutoff": 1, },
        >>>                 4: { "mode": "onoff", "name": "switch-A", "cutoff": 2, },
        >>>                 5: { "mode": "voltages", "name": "sensor", },
        >>>             },
        >>>             mux_component = data_mux_1,
        >>>             mux_obj = "data_mux_1",
        >>>         ),
        >>>     ),
        >>> )
        >>>
        >>> ttbl.config.target_add(target)

        Non-multiplexed mode::

        >>> ttbl.config.target_add(target, target_type = "example", tags = {})
        >>>
        >>> target.interface_add("store", ttbl.config._iface_store)
        >>>
        >>> target.interface_add(
        >>>     "capture",
        >>>     ttbl.capture.interface(
        >>>         ad = ttbl.noyito.channel_c(
        >>>             {
        >>>                 3: { "mode": "bool", "name": "redled", "cutoff": 1, },
        >>>                 4: { "mode": "onoff", "name": "switch-A", "cutoff": 2, },
        >>>                 5: { "mode": "voltages", "name": "sensor", },
        >>>             },
        >>>             device_spec = "usb,#200443183011BA51985F,##_2:1.0",
        >>>         ),
        >>>     ),
        >>> )
        >>>
        >>> ttbl.config.target_add(target)

        **Tech details**

        This device outputs continuousy on the serial port att 115200n81 a
        stream of ASCII like::

          CH0:2016        1.622V
          CH1:2191        1.764V
          CH2:2014        1.624V
          CH3:2193        1.766V
          CH4:2018        1.626V
          CH5:2195        1.769V
          CH6:2018        1.625V
          CH7:2195        1.768V
          CH8:2014        1.622V
          CH9:2194        1.766V

        *formally*::

          CH0:<NNNN><TAB><FLOAT>V\r\n
          ...
          CH8:<NNNN><TAB><FLOAT>V\r\n
          CH9:<NNNN>	<FLOAT>V\r\n
          \r\n

        NNNN being 0000-4095 (12-bit raw sample) and FLOAT (only four
        bytes) 0 to 3.3V. Note that when floating disconnected, it
        always reports about 1.7V (because both ground and pins are in
        the air).

        There is one ground for each bank of five sampling channels.

        This device packs an stm32 MPU, can be reprogrammed, firmware at http://files.banggood.com/2018/06/SKU836210.zip

        """
        assert isinstance(channels, dict), \
            "channels: expected a dictionary, got %s" % type(channels)

        if device_spec != None:
            assert mux_component == None, \
                "mux_component: expected None, device_spec is set"
            assert mux_obj == None, \
                "mux_obj: expected None, device_spec is set"
            assert isinstance(device_spec, str), \
                "device_spec: expected str; got {type(device_spec)}"
        else:
            assert isinstance(mux_component, str), \
                "mux_component: expected str; got {type(mux_component)}"
            assert isinstance(mux_obj, mux_pc), \
                "mux_obj: expected ttbl.noyito.mux_pc; got {type(mux_obj)}"

        # the capture program is a python executable we run with this
        # interpreter so later we can choose -- if we let the system
        # choose, then we won't be able to test things starting
        python_bin = os.path.realpath(sys.executable)
        self.capture_program = commonl.ttbd_locate_helper(
            "noyito-capture.py", ttbl._install.share_path,
            log = logging, relsrcpath = ".")

        self.mux_component = mux_component
        self.mux_obj = mux_obj
        self.device_spec = device_spec

        self.channell = []
        for channel, data in channels.items():
            assert isinstance(channel, int) and channel >= 0 and channel <= 9, \
                "channel: channel descriptor has to be an integer 0-9," \
                " got %s" % type(channel)
            # matches ttbd/noyito-capture.py.transform.mode
            # verify mode and name
            mode = data.get('mode', None)
            assert mode in ( None, 'mode', 'bool', 'onoff', 'voltages' ), \
                "channel mode has to be one of: None, mode, bool, onoff; " \
                " got %s" % mode
            name = data.get('name', str(channel))
            assert isinstance(name, str), \
                "name: expected a string; got %s" % type(name)
            # now we tranform it for a command line to noyito-capture.py
            l = [ "%s" % channel ]
            for k, v in data.items():
                l.append("%s=%s" % (k, v))
            self.channell.append(":".join(l))

        ttbl.capture.impl_c.__init__(
            self, False, mimetype = "application/json",
            **kwargs)

        if power_kwargs == None:
            power_kwargs = {}

        if self.device_spec:	# non-mux mode, capture from device straight
            source = "%(capture_device)s"	# we'll resolve in start()
        else:
            source = "%(path)s/%(mux_component)s-ncat.socket"

        # we use a deamon_c to start/stop the capture program;
        # template the command line and set the params for it in
        # self.kws before calling on() from start()
        ttbl.power.daemon_c.__init__(
            self,
            cmdline = [
                "stdbuf", "-e0", "-o0",
                python_bin,
                self.capture_program,
                source,
                "%(capture_path)s/%(stream_filename)s"
            ] + self.channell,
            # the capture program is a python executable we run
            check_path = python_bin,
            **power_kwargs)

        # these are to resolve the command line set in __init__ and
        # for ttbl.power.daemon_c.on() to use
        self.kws['name'] = 'noyito-capture'
        self.kws['mux_component'] = self.mux_component

        if self.device_spec:	# non-mux mode, fill UPID
            self.upid_set("Noyito 12-bit 10 channel ADC",
                          device_spec = device_spec)
        else:			# use mux's UPID, we are virtual
            self.upid = mux_obj.upid



    def start(self, target, capturer, capture_path):

        stream_filename = capturer + ".data.json"
        log_filename = capturer + ".capture.log"

        # these are to resolve the command line set in __init__ and
        # for ttbl.power.daemon_c.on() to use
        self.kws['stream_filename'] = stream_filename
        # yesh, confusing: path vs capture_path -- a long legacy; path
        # is the target's state dir; capture_path is where we are
        # dumping the capture
        self.kws['component'] = capturer
        self.kws['capture_path'] = capture_path
        self.kws['path'] = target.state_dir
        self.stderr_name = f"{capture_path}/{capturer}.capture.log"

        if self.device_spec:	# non-mux mode, resolve %(capture_device)s
            device_resolver = ttbl.device_resolver_c(
                target, self.device_spec,
                f"instrumentation.{self.upid_index}.device_spec")
            tty_dev = device_resolver.tty_find_by_spec()
            self.kws['capture_device'] = tty_dev
        else:			# mux mode, ensure multiplexor is on
            target.power.put_on(target, ttbl.who_daemon(),
                                { "component":  self.mux_component },
                                None, None )

        pidfile = commonl.kws_expand(self.pidfile, self.kws)
        ttbl.power.daemon_c.on(self, target, capturer)

        return True, {
            "default": stream_filename,
            "log": log_filename
        }


    def verify(self, target, component, cmdline_expanded):
        self.kws['component'] = component
        return commonl.process_alive(
            commonl.kws_expand(self.pidfile, self.kws), self.check_path) \
            != None


    def stop(self, target, capturer, _capture_path):
        ttbl.power.daemon_c.off(self, target, capturer)
