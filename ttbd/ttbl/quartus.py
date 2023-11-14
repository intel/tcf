#! /usr/bin/env python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import copy
import os
import subprocess

import commonl
import ttbl
import ttbl.images
import ttbl.power

class pgm_c(ttbl.images.flash_shell_cmd_c):
    """Flash using Intel's Quartus PGM tool

    This allows to flash images to an Altera MAX10, using the Quartus
    tools, freely downloadable from
    https://www.intel.com/content/www/us/en/collections/products/fpga/software/downloads.html?s=Newest

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

    :params str usb_serial_number: (optional) device specification
      (see :class:`ttbl.device_resolver_c`), eg a USB serial number

      >>> usb_serial_number = "3211123"

      a USB path:

      >>> usb_serial_number = "usb,idVendor=34d2,idProduct=131d,bInterfaceNumber=4"

      or more complex specifications are possible

    :param dict image_map:

    :param str name: (optiona; default 'Intel Quartus PGM #<DEVICEID>')
      instrument's name.

    :param dict args: (optional) dictionary of extra command line options to
      *quartus_pgm*; these are expanded with the target keywords with
      *%(FIELD)s* templates, with fields being the target's
      :ref:`metadata <finding_testcase_metadata>`:

      FIXME: move to common flash_shell_cmd_c

    :param dict jtagconfig: (optional) jtagconfig --setparam commands
      to run before starting.

      These are expanded with the target keywords with
      *%(FIELD)s* templates, with fields being the target's
      :ref:`metadata <finding_testcase_metadata>` and then run as::

        jtagconfig --setparam CABLENAME KEY VALUE

    :param int tcp_port: (optional, default *None*) if a TCP port
      number is given, it is a assumed the flashing server is in
      localhost in the given TCP port.

    :param str sibling_serial_number (optional, default *None*) USB serial
      number of the USB device that is a sibling to the one defined by
      usb_serial_number

    :param int usb_port (optional, default *None*) port that the USB device is
      connected to, used in combination with sibling_serial_number to find
      the USB path for devices that do not have unique serial numbers (USB
      Blaster I)

    Other parameters described in :class:ttbl.images.impl_c.


    **Command line reference**

    https://www.intel.com/content/dam/www/programmable/us/en/pdfs/literature/manual/tclscriptrefmnl.pdf

    Section Quartus_PGM (2-50)

    **System setup**

    -  Download and install Quartus Programmer::

         $ wget http://download.altera.com/akdlm/software/acdsinst/20.1std/711/ib_installers/QuartusProgrammerSetup-20.1.0.711-linux.run
         # chmod a+x QuartusProgrammerSetup-20.1.0.711-linux.run
         # ./QuartusProgrammerSetup-20.1.0.711-linux.run --unattendedmodeui none --mode unattended --installdir /opt/quartus --accept_eula 1

    - if installing to a different location than */opt/quartus*,
      adjust the value of :data:`path` in a FIXME:ttbd configuration
      file.


    **Troubleshooting**

    When it fails to flash, the error log is reported in the server in
    a file called *flash-COMPONENTS.log* in the target's state
    directory (FIXME: we need a better way for this--the admin shall
    be able to read it, but not the users as it might leak sensitive
    information?).

    Common error messages:

    - *Error (213019): Can't scan JTAG chain. Error code 87*

      Also seen when manually running in the server::

        $ /opt/quartus/qprogrammer/bin/jtagconfig
        1) USB-BlasterII [3-1.4.4.3]
          Unable to read device chain - JTAG chain broken

      In many cases this has been:

      - a powered off main board: power it on

      - a misconnected USB-BlasterII: reconnect properly

      - a broken USB-BlasterII: replace unit

    - *Error (209012): Operation failed*

      this usually happens when flashing one component of a multiple
      component chain; the log might read something like::

        Info (209060): Started Programmer operation at Mon Jul 20 12:05:22 2020
        Info (209017): Device 2 contains JTAG ID code 0x038301DD
        Info (209060): Started Programmer operation at Mon Jul 20 12:05:22 2020
        Info (209016): Configuring device index 2
        Info (209017): Device 2 contains JTAG ID code 0x018303DD
        Info (209007): Configuration succeeded -- 1 device(s) configured
        Info (209011): Successfully performed operation(s)
        Info (209061): Ended Programmer operation at Mon Jul 20 12:05:22 2020
        Error (209012): Operation failed
        Info (209061): Ended Programmer operation at Mon Jul 20 12:05:22 2020
        Error: Quartus Prime Programmer was unsuccessful. 1 error, 0 warnings

      This case has been found to be because the **--bgp** option is
      needed (which seems to map to the *Enable Realtime ISP
      programming* in the Quartus UI, *quartus_pgmw*)

    - *Warning (16328): The real-time ISP option for Max 10 is
      selected. Ensure all Max 10 devices being programmed are in user
      mode when requesting this programming option*

      Followed by:

        *Error (209012): Operation failed*

      This case comes when a previous flashing process was interrupted
      half way or the target is corrupted.

      It needs a special one-time recovery; currently the
      workaround seems to run the flashing with out the *--bgp* switch
      that as of now is hardcoded.

      FIXME: move the --bgp and --mode=JTAG switches to the args (vs
      hardcoded) so a recovery target can be implemented as
      NAME-nobgp

    *Using Quartus tool with a remote jtagd*

    The service port for *jtagd* can be tunneled in and used by the
    Quartus toolsuite::

      $ tcf property-get r013s001 interfaces.power.jtagd.tcp_port
      5337
      $ tcf power-on -c jtagd TARGET
      $ tcf tunnel-add TARGET 5337 tcp 127.0.01
      SERVERNAME:1234

    Now the Quartus Qprogrammer tools need to be told which server to
    add::

      $ jtagdconfig --addserver SERVERNAME:1234 ""

    (second entry is an empty password); this adds an entry to
    *~/.jtagd.conf*::

      # /home/USERNAME/.jtag.conf
      Remote1 {
	    Host = "SERVERNAME:1234";
	    Password = "";
      }

    Note the port number changes with each tunnel, you will have to
    *jtagconfig --addserver* and delete the old one (you can edit the
    file by hand too).

    Now list remote targets::

      $ jtagconfig
      1) USB-BlasterII on SERVERNAME:1234 [3-1.4.1]
        031050DD   10M50DA(.|ES)/10M50DC
        031040DD   10M25D(A|C)

    Note this connection is open to anyone until the tunnel is removed
    or the allocation is released with *tcf alloc-rm* or
    equivalent. *PENDING* use SSL to secure access.

    [ see also for the Quartus GUI, follow
    https://www.intel.com/content/www/us/en/programmable/quartushelp/13.0/mergedProjects/program/pgm/pgm_pro_add_server.htm ]


    **Quartus Lite**

    Download from https://www.intel.com/content/www/us/en/software-kit/684215/intel-quartus-prime-lite-edition-design-software-version-21-1-for-linux.html?

    Install with::

      $ tar xf Quartus-lite-21.1.0.842-linux.tar
      $ cd components
      $ chmod a+x ./Quartus-lite-21.1.0.842-linux.tar
      $ ./Quartus-lite-21.1.0.842-linux.tar

    Quartus will use the same *~/.jtagd.conf* if you have used
    *jtagconfig* to configure as above

    1. Start Quartus::

      $ INSTALLPATH/intelFPGA_lite/21.1/quartus/bin/quartus

    2. Go to Programmer > Edit > Hardware Setup

    3. Click on *Add Hardware*

    4. Enter as *Server Name* and *Server Port* the name of the server
       that is doing the tunnel (as printed by *tcf tunnel-add*
       above); leave the password blank.

    5. Click *OK*


    **Troubleshooting**

    - can't connect to port::

        $ ./jtagconfig
        1) Remote server SERVERNAME:1234: Unable to connect

      - ensure jtagd in the target is on

      - ensure the tunnel is on

    """


    #: Path to *quartus_pgm*
    #:
    #: We need to use an ABSOLUTE PATH if the tool is not in the
    #: normal search path (which usually won't).
    #:
    #: Change by setting, in a :ref:`server configuration file
    #: <ttbd_configuration>`:
    #:
    #: >>> ttbl.quartus.pgm_c.path = "/opt/quartus/qprogrammer/bin/quartus_pgm"
    #:
    #: or for a single instance that then will be added to config:
    #:
    #: >>> imager = ttbl.quartus.pgm_c(...)
    #: >>> imager.path =  "/opt/quartus/qprogrammer/bin/quartus_pgm"
    path = "/opt/quartus/qprogrammer/bin/quartus_pgm"
    path_jtagconfig = "/opt/quartus/qprogrammer/bin/jtagconfig"


    def __init__(self, usb_serial_number, image_map, args = None, name = None,
                 jtagconfig = None, tcp_port = None,
                 sibling_serial_number = None, usb_port = None,
                 **kwargs):
        assert isinstance(usb_serial_number, str)
        commonl.assert_dict_of_ints(image_map, "image_map")
        commonl.assert_none_or_dict_of_strings(jtagconfig, "jtagconfig")
        assert name == None or isinstance(name, str)
        assert tcp_port == None or isinstance(tcp_port, int)

        self.usb_serial_number = usb_serial_number
        self.tcp_port = tcp_port
        self.image_map = image_map
        self.jtagconfig = jtagconfig
        self.sibling_serial_number = sibling_serial_number
        self.usb_port = usb_port
        if args:
            commonl.assert_dict_of_strings(args, "args")
            self.args = args
        else:
            self.args = {}

        cmdline = [
            "stdbuf", "-o0", "-e0", "-i0",
            self.path,
            # FIXME: move this to args, enable value-less args (None)
            "--bgp",		# Real time background programming
            "--mode=JTAG",	# this is a JTAG
            # when using a server, if the target is called
            # SOMETHING in SERVERNAME:PORT CABLENAME, it seems PGM
            # goes straight there. Weird
            "-c", "%(device_path)s",	# will resolve in flash_start()
            # in flash_start() call we'll map the image names to targets
            # to add these
            #
            #'--operation=PV;%(image.NAME)s@1',
            #'--operation=PV;%(image.NAME)s@2',
            #...
            # (P)rogram (V)erify, (B)lank-check [ not really needed]
            #
            # note like this we can support burning multiple images into the
            # same chain with a single call
        ]
        if args:
            for arg, value in args.items():
                if value != None:
                    cmdline += [ arg, value ]
        # we do this because in flash_start() we need to add
        # --operation as we find images we are supposed to flash
        self.cmdline_orig = cmdline

        ttbl.images.flash_shell_cmd_c.__init__(self, cmdline, cwd = '%(file_path)s',
                                   **kwargs)
        if name == None:
            self.name = "quartus"
        self.upid_set(
            f"Intel Quartus PGM @ USB#{usb_serial_number}",
            usb_serial_number = usb_serial_number)


    def flash_start(self, target, images, context):
        # Finalize preparing the command line for flashing the images

        # find the device path; quartus_pgm doesn't seem to be able to
        # address by serial and expects a cable name as 'PRODUCT NAME
        # [PATH]', like 'USB BlasterII [1-3.3]'; we can't do this on
        # object creation because the USB path might change when we power
        # it on/off (rare, but could happen). Since USB Blaster I do not
        # have unique serial numbers we use a combination of usb_port
        # and sibling_serial_number to find the correct usb_path

        if self.usb_port != None:	# DEPRECATE: use device_resolver
            usb_path, _vendor, product = ttbl.usb_serial_to_path(
                self.sibling_serial_number, self.usb_port)
        else:
            device_resolver = ttbl.device_resolver_c(
                target, self.usb_serial_number,
                f"instrumentation.{self.upid_index}.usb_serial_number")
            usb_syspath = device_resolver.device_find_by_spec()
            usb_path = os.path.basename(usb_syspath)
            product = ttbl._sysfs_read(os.path.join(usb_syspath, "product"))

        if self.tcp_port:
            # server based cable name
            device_path = f"{product} on localhost:{self.tcp_port} [{usb_path}]"
            jtag_config_filename = f"{target.state_dir}/jtag-{'_'.join(images.keys())}.conf"
            # Create the jtag client config file to ensure that
            # the correct jtag daemon is connected to, then use the
            # environment variable QUARTUS_JTAG_CLIENT_CONFIG to have
            # the quartus software find it
            with open(jtag_config_filename, "w+") as jtag_config:
                jtag_config.write(
                    f'ReplaceLocalJtagServer = "localhost:{self.tcp_port}";')
            self.env_add["QUARTUS_JTAG_CLIENT_CONFIG"] = jtag_config_filename
        else:
            # local cable name, starts sever on its own
            device_path = f"{product} [{usb_path}]"

        context['kws'] = {
            # HACK: we assume all images are in the same directory, so
            # we are going to cwd there (see in __init__ how we set
            # cwd to %(file_path)s. Reason is some of our paths might
            # include @, which the tool considers illegal as it uses
            # it to separate arguments--see below --operation
            'file_path': os.path.dirname(list(images.values())[0]),
            'device_path': device_path,
            # flash_shell_cmd_c.flash_start() will add others
        }

        # for each image we are burning, map it to a target name in
        # the cable (@NUMBER)
        # make sure we don't modify the originals
        cmdline = copy.deepcopy(self.cmdline_orig)
        for image_type, filename in images.items():
            target_index = self.image_map.get(image_type, None)
            # pass only the realtive filename, as we are going to
            # change working dir into the path (see above in
            # context[kws][file_path]
            cmdline.append("--operation=PV;%s@%d" % (
                os.path.basename(filename), target_index))
        # now set it for flash_shell_cmd_c.flash_start()
        self.cmdline = cmdline

        if self.jtagconfig:
            for option, value in self.jtagconfig.items():
                cmdline = [
                    self.path_jtagconfig,
                    "--addserver", f"localhost:{self.tcp_port}", "",  # empty password
                    "--setparam",
                    device_path,
                    option, value
                ]
                target.log.info("running per-config: %s" % " ".join(cmdline))
                subprocess.check_output(
                    cmdline, shell = False, stderr = subprocess.STDOUT)
        ttbl.images.flash_shell_cmd_c.flash_start(self, target, images, context)


class jtagd_c(ttbl.power.daemon_c):
    """Driver for the jtag daemon

    This driver starts the jtag daemon on the server for a specific
    USB Blaster II

    Does not override any of the default methods except for verify

    **Arugments**

    :params str usb_serial_number: (optional) device specification
      (see :class:`ttbl.device_resolver_c`), eg a USB serial number

      >>> usb_serial_number = "3211123"

      a USB path:

      >>> usb_serial_number = "usb,idVendor=34d2,idProduct=131d,bInterfaceNumber=4"

      or more complex specifications are possible

    :param int tcp_port: (1024 - 65536) Number of the TCP port on
      localhost where the daemon will listen

    :param str jtagd_path: (optional) orverride :data:`jtagd_path`;

    :param str explicit: (optional; default *off*) control when this
      is started on/off:

      - *None*: for normal behaviour; component will be
         powered-on/started with the whole power rail

      - *both*: explicit for both powering on and off: only
        power-on/start and power-off/stop if explicity called by
        name

      - *on*: explicit for powering on: only power-on/start if explicity
        powered on by name, power off normally

      - *off*: explicit for powering off: only power-off/stop if explicity
        powered off by name, power on normally

      By default it is set to *off*, so that when the target is powere
      off existing network connections to the daemon are maintained.

    Any other arguments as taken by :class:ttbl.power.daemon_c and
    :class:ttbl.power.impl_c.
    """

    jtagd_path = "/opt/quartus/qprogrammer/bin/jtagd"

    def __init__(self, usb_serial_number, tcp_port, jtagd_path = None,
                 check_path = None, explicit = "off", **kwargs):
        assert isinstance(usb_serial_number, str), \
            "usb_serial_number: expected a string, got %s" % type(usb_serial_number)
        assert isinstance(tcp_port, int), \
            "tcp_port: expected an integer between 1024 and 65536, got %s" \
            % type(usb_serial_number)

        if jtagd_path:
            self.jtagd_path = jtagd_path
        assert isinstance(self.jtagd_path, str), \
            "openipc_path: expected a string, got %s" % type(jtagd_path)
        self.usb_serial_number = usb_serial_number
        self.tcp_port = tcp_port

        cmdline = [
            self.jtagd_path,
            "--no-config",
            "--auto-detect-filter",
            "%(resolved_usb_serial_number)s",	# we'll be replaced by on()
            "--port", str(tcp_port),
            "--debug",
            "--foreground",
        ]

        ttbl.power.daemon_c.__init__(
            self, cmdline, precheck_wait = 0.5, mkpidfile = True,
            name = "jtagd", explicit = explicit,
            # ...linux64/jtagd renames itself to jtagd and it makes it hard to kill
            path = "jtagd",
            check_path = "/opt/quartus/qprogrammer/linux64/jtagd",
            **kwargs)

        # Register the instrument like this, so it matches pgm_c and
        # others and they all point to the same instrument
        self.upid_set(
            f"Intel Quartus PGM @ USB#{usb_serial_number}",
            usb_serial_number = usb_serial_number)

    def target_setup(self, target, iface_name, component):
        target.fsdb.set(f"interfaces.{iface_name}.{component}.tcp_port",
                        self.tcp_port)
        #Set the local ports that is able to be reached via tunneling
        target.tunnel.allowed_local_ports.add(("127.0.0.1", "tcp",
                                               self.tcp_port))
        ttbl.power.daemon_c.target_setup(self, target, iface_name, component)

    def verify(self, target, component, cmdline_expanded):
        pidfile = os.path.join(target.state_dir, component + "-jtagd.pid")
        return commonl.process_alive(pidfile, self.check_path) \
            and commonl.tcp_port_busy(self.tcp_port)

    def on(self, target, component):
        device_resolver = ttbl.device_resolver_c(
            target, self.usb_serial_number,
            f"instrumentation.{self.upid_index}.usb_serial_number")
        usb_syspath = device_resolver.device_find_by_spec()
        # set this so that the command line can be expanded with the
        # right USB serial #
        self.kws["resolved_usb_serial_number"] = ttbl._sysfs_read(os.path.join(usb_syspath, "serial"))
        return ttbl.power.daemon_c.on(self, target, component)
