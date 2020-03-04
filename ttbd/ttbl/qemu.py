#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Drivers to create targets on virtual machine using QEMU
-------------------------------------------------------

.. note:: This deprecates all previous ttbl/tt_qemu*.py modules

These are all raw building block which requires extra
configuration. To create targets, use functions such as:

 - :func:`conf_00_lib_pos.target_qemu_pos_add`

 - :func:`conf_00_lib_mcu.target_qemu_zephyr_add`

These drivers implement different objects needed to implement targets
that run as QEMU virtual machines:

- :class:`pc`: a power rail controller to control a QEMU virtual
  machine running as a daemon, providing interfaces for
  starting/stopping, debugging, BIOS/kernel/initrd image flashing and
  exposes serial consoles that an be interacted with the
  :class:`ttbl.console.generic_c` object.

- :class:`qmp_c`: an object to talk to QEMU's control socket

- :class:`plugger_c`: an adaptor to plug physical USB devices to QEMU
  targets with the :mod:`ttbl.things` interface

- :class:`network_tap_pc`: a power rail controller to setup tap
  devices to a (virtual or physical) network device that represents a
  network.

"""
import errno
import json
import logging
import os
import socket
import subprocess
import time

import commonl
import ttbl
import ttbl.console
import ttbl.debug
import ttbl.power
import ttbl.things
import ttbl.images

class qmp_c(object):
    """
    Simple handler for the Qemu Monitor Protocol that allows us to run
    basic QMP commands and report on status.
    """
    def __init__(self, sockfile, logfile = None):
        self.sockfile = sockfile
        self.log = logging.root.getChild("qmp")
        self.logfile = logfile
        self.sk = None

    class exception(RuntimeError):
        "Base QMP exception"
        pass

    class cant_connect_e(exception):
        "Cannot connect to QMP socket; probably QEMU didn't start"
        pass

    def __enter__(self):
        self.sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Some ops can timeout, like when adding a USB device to QEMU
        # if the device is misheaving -- we want to catch that and fail
        self.sk.settimeout(3)
        self.sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Sometimes it takes time for QEMU to get started in heavily
        # loaded systems, so we retry six times and wait .5 secs
        # before each
        tries = 20
        for count in range(tries):
            try:
                self.sk.connect(self.sockfile)
                break
            except socket.error as e:
                if e.errno == errno.ENOENT:
                    self.log.info("%s: %d/%d: failed to connect, retrying: %s",
                                  self.sockfile, count + 1, tries, str(e))
                    time.sleep(0.5)
                    continue
                raise
        else:
            self.log.error("%s: cannot connect after %d tries"
                           % (self.sockfile, tries,))
            if os.path.exists(self.logfile):
                with open(self.logfile) as logfile:
                    for line in logfile:
                        self.log.error("%s: qemu log: %s"
                                       % (self.sockfile, line.strip()))
            else:
                self.log.error("%s: (no qemu log at '%s')"
                               % (self.sockfile, self.logfile))
            raise self.cant_connect_e("%s: cannot connect after %d "
                                      "tries; QEMU is off?"
                                      % (self.sockfile, tries))

        data = self._receive('QMP')
        if not 'QMP' in data:
            raise RuntimeError("QMP: no init banner received")
        # Need to run this, somehow it seems to enable the rest of the commands
        self.command("qmp_capabilities")
        return self

    def __exit__(self, *args):
        self.sk.close()

    def _receive(self, expect = None):
        timeout = 3
        ts0 = time.time()
        while True:
            ts = time.time()
            if ts - ts0 > timeout:
                raise RuntimeError("QMP: Timeout reading status reponse")
            # The socket has a 3s timeout
            data = self.sk.recv(8096)
            if not data:
                continue
            try:
                logging.debug("got JSON data: %s", data)
                # might receive events, we only care for 'return'
                for line in data.splitlines():
                    js = json.loads(line)
                    if expect:
                        if expect in js:
                            return js
                    else:
                        return js
            except ValueError as e:
                logging.error("bad JSON data: %s", e)
                logging.debug("bad JSON data: %s", data)
                raise

    def command(self, command, **kwargs):
        """
        Send a QMP command, return response

        :param str command: command to send
        :param dict kwargs: dictionary of key/value arguments to send
          to the command

        :return: response code from QEMU
        """
        js = json.dumps({ "execute" : command, "arguments" : kwargs })
        self.sk.sendall(js)
        resp = self._receive('return')
        if not 'return' in resp:
            raise RuntimeError("QMP: %s: malformed response "
                               "missing 'return'" % command)

        return resp['return']

    def __del__(self):
        self.sk.close()
        del self.sk



class pc(ttbl.power.daemon_c,
         ttbl.images.impl_c,
         ttbl.debug.impl_c):
    """Manage QEMU instances exposing interfaces for TCF to control it

    This object exposes:

    - power control interface: to start / stop QEMU
    - images interface: to specify the kernel / initrd / BIOS images
    - debug interface: to manage the virtual CPUs, debug via GDB

    A target can be created and this object attached to the multiple
    interfaces to expose said functionalities, like for example
    (pseudo code):

    >>> target = ttbl.test_target("name")
    >>> qemu_pc = ttbl.qemu.pc([ "/usr/bin/qemu-system-x86_64", ... ])
    >>> target.interface_add("power", ttbl.power.interface(qemu_pc))
    >>> target.interface_add("debug", ttbl.debug.interface(qemu_pc))
    >>> target.interface_add("images", ttbl.images.interface(qemu_pc))

    For a complete, functional example see
    :func:`conf_00_lib_pos.target_qemu_pos_add` or
    :func:`conf_00_lib_mcu.target_qemu_zephyr_add`.

    :param list(str) qemu_cmdline: command line to start QEMU,
      specified as a list of *[ PATH, ARG1, ARG2, ... ]*.

      Don't add *-daemonize*! This way the daemon is part of the process
      tree and killed when we kill the parent process

      Note this will be passed to :class:`ttbl.power.daemon_c`, so
      '%(FIELD)s' will be expanded with the tags and runtime
      properties of the target.

    :param str nic_model: (optional) Network Interface Card emulation
      used to create a network interface.

    **General design notes**

    - the driver will add command line to create a QMP access socket
      (to control the instance and launch the VM stopped), a GDB
      control socket and a PID file. Thus, don't specify *-qmp*,
      *-pidfile*, *-S* or *-gdb* on the command line.

    - any command line is allowed as long as it doesn't interfere with
      those.

    - as in all the TCF server code, these might be called from
      different processes who share the same configuration; hence we
      can't rely on any runtime storage. Any runtime values that are
      needed are kept on a filesystem database (`self.fsdb`).

      We start the process with Python's subprocess.Popen(), but then
      it goes on background and if the parent dies, the main server
      process will reap it (as prctl() has set with SIG_IGN on
      SIGCHLD) and any subprocess of the main process might kill it
      when power-off is called on it. :class:`ttbl.power.daemon_c`
      takes care of all that.

    **Firmware interface: What to load/run**

    The :class:`images <ttbl.images.interface>` interface can be used
    to direct QEMU to load BIOS/kernel/initrd images. Otherwise, it
    will execute stuff off the disk (if the command line is set
    correctly). This is done by setting the target properties:

    - *qemu-image-bios*

    - *qemu-image-kernel*

    - *qemu-image-initrd*

    these can be set to the name of a file in the server's namespace,
    normally off the user storage area (FIXME: implement this limit in
    the flash() interface, allow specifics for POS and such).

    Additionally, *qemu-image-kernel-args* can be set to arguments to
    the kernel.

    **Serial consoles**

    This driver doesn't intervene on serial consoles (if wanted or
    not). The way to create serial consoles is to add command line
    such as:

    >>> cmdline += [
    >>>     "-chardev", "socket,id=NAME,server,nowait,path=%%(path)s/console-NAME.write,logfile=%%(path)s/console-NAME.read",
    >>>     "-serial", "chardev:NAME"
    >>> ]

    which makes QEMU write anything received on such serial console on
    file *STATEDIR/console-NAME.read* and send to the virtual machine
    anything written to socket *STATEDIR/console-NAME.write* (where
    *STATEDIR* is the target specific state directory).

    From there, a :class:`ttbl.console.generic_c` console interface
    implementation can be added:

    >>> target.interface_add("console", ttbl.console.interface(
    >>>     ( "NAME", ttbl.console.generic_c() )
    >>> )

    the console handling code in :class:`ttbl.console.generic_c` knows
    from *NAME* where the find the read/write files.

    **Networking**

    Most networking can rely on TCF creating a virtual network device
    over a TAP device associated to each target and interconnect they
    are connected to--look at :class:`ttbl.qemu.network_tap_pc`:

    >>> target = ttbl.test_target("name")
    >>> target.add_to_interconnect(
    >>>     'nwa', dict(
    >>>         mac_addr = "02:61:00:00:00:05",
    >>>         ipv4_addr = "192.168.97.5",
    >>>         ipv6_addr = "fc00::61:05")
    >>> qemu_pc = ttbl.qemu.pc([ "/usr/bin/qemu-system-x86_64", ... ])
    >>> target.interface_add("power", ttbl.power.interface(
    >>>     ( "tuntap-nwa", ttbl.qemu.network_tap_pc() ),
    >>>     qemu_pc,
    >>> )

    the driver automatically adds the command line to add correspoding
    network devices for each interconnect the target is a member of.

    It is possible to do NAT or other networking setups; the command
    line needs to be specified manually though.
    """

    def __init__(self, qemu_cmdline, nic_model = "e1000"):
        # Here we initialize part of the command line; the second part
        # is generated in on(), since the pieces we need are only
        # known at that time [e.g. network information, images to load].
        ttbl.debug.impl_c.__init__(self)
        qemu_cmdline += [
            # Common command line options which are always appended;
            # there is no way to override these because this driver
            # depends on them to work properly.

            # Debug: a QMP socket called qemu.qmp is used to
            #   control the VM. Make sure you tell QEMU to start
            #   it
            #
            "-qmp", "unix:%(path)s/qemu.qmp,server,nowait",
            # Always start in debug mode -- this way the
            # whole thing is stopped until we unleash it
            # with QMP; this allows us to first start
            # daemons that we might need to start
            "-S",
            "-gdb", "tcp:0.0.0.0:%(qemu-gdb-tcp-port)s",
            # PID file that we use to test for the process and kill it
            "-pidfile", "%(path)s/qemu.pid"
        ]
        self.nic_model = nic_model
        ttbl.power.daemon_c.__init__(
            self,
            cmdline = qemu_cmdline,
            # paranoid asks power inteface to retry if it fails to
            # power on/off and get power status; this allows QEMU
            # restarts to be automated if it fails for retryable
            # conditions such as race condition in port acquisition.
            paranoid = True,
            pidfile = "%(path)s/qemu.pid",
            # qemu makes its own PID files
            mkpidfile = False)
        # set the power controller part to paranoid mode; this way if
        # QEMU fails to start for a retryable reason (like port
        # taken), it will be retried automatically
        self.power_on_recovery = True
        self.paranoid_get_samples = 1
        self.paranoid = True
        ttbl.images.impl_c.__init__(self)
        self.upid_set(
            "QEMU virtual machine",
            # if multiple virtual machines are created associated to a
            #   target, this shall generate a different ID for
            #   each...in most cases
            serial_number = commonl.mkid(" ".join(qemu_cmdline) + nic_model)
        )

    #
    # Images interface (ttbl.images.impl_c)
    #
    def flash(self, target, images):
        # for flashing we set target's runtime properties which point
        # to what files shall be loaded; when the QEMU command is run,
        # those properties are read by ttbl.power.daemon_c() as things
        # to use to template the command line arguments.
        for image_type, image_name in images.iteritems():
            if image_type == "kernel":
                target.fsdb.set("qemu-image-kernel", image_name)
            elif image_type.startswith("kernel-"):
                # kernel-ARCHITECTURE/BSP -> this is used by things
                # like Zephyr, who add the BSP to the kernel spec
                _, bsp = image_type.split("-", 1)
                if bsp not in target.tags['bsps']:
                    raise ValueError(
                        "unknown BSP '%s' when attempting to flash image-type '%s'"
                        % (bsp, image_type))
                target.fsdb.set("qemu-image-kernel", image_name)
            elif image_type == "initrd":
                target.fsdb.set("qemu-image-initrd", image_name)
            elif image_type == "bios":
                target.fsdb.set("qemu-image-bios", image_name)
            else:
                raise ValueError("unknown image type %s" % image_type)

    #
    # Power Control Interface (ttbl.power.impl_c via ttbl.power.daemon_c)
    #
    # ttbl.power.daemon_c implements on(), off(), get(); we override
    # on() to add command line extras we need before we call daemon_c.on().
    #
    # verify() is needed by daemon_c.on() to tell if the daemon
    # actually started; we use paranoid mode so the power interface
    # automatically retries it if something failed; causes for retry:
    #
    # - race condition in port allocation: since we chose the port we
    #   wanted to use and until we started using it someone took it.
    #
    # - any other general failure which might be enviromental

    def verify(self, target, component, cmdline_expanded):
        # ttbl.power.daemon_c -> verify if the process has started
        # returns *True*, *False*
        #
        # Connect to the QEMU Monitor socket and issue a status command,
        # verify we get 'running', giving it some time to report.
        #
        # Returns *True* if the QEMU VM is running ok, *False* otherwise;
        # raises anything on errors

        stderr_fname = os.path.join(target.state_dir,
                                    component + "-" + self.name + ".stderr")
        with open(stderr_fname) as stderrf:
            if 'Address already in use' in stderrf:
                stderrf.seek(0, 0)
                return False
        try:
            with qmp_c(os.path.join(target.state_dir, "qemu.qmp"),
                       stderr_fname) as qmp:
                r = qmp.command("query-status")
                # prelaunch is what we get when we are waiting for GDB
                return r['status'] == "running" or r['status'] == 'prelaunch'
        except RuntimeError as e:
            target.log.error("can't connect to QMP: %s" % e)
            # ttbl.power.daemon_c.on() has created this file with the
            # stderr for QEMU
            self.log_stderr(target, component)
            raise
        except IOError as e:
            if e.errno == errno.ENOENT:
                return False
            if e.errno == errno.ECONNREFUSED:
                return False
            raise

    def on(self, target, component):
        # Start QEMU
        #
        # We first assign a port for GDB debugging, if someone takes
        # it before we do, start will fail and paranoid mode (see
        # above) will restart it.
        base = ttbl.config.tcp_port_range[0]
        top = ttbl.config.tcp_port_range[1]
        if base < 5900:		# we need ports >= 5900 for VNC
            base = 5900
        tcp_port_base = commonl.tcp_port_assigner(
            2 , port_range = ( base, top ))
        target.fsdb.set("qemu-gdb-tcp-port", "%s" % tcp_port_base)
        # This might not be used at all, but we allocate and declare
        # it in case the implementation will use it; allocating in a
        # higher layer makes it more complicated.
        # this one is the port number based on 5900 (VNC default 0)
        if top < 5900:
            logging.warning(
                "ttbl.config.tcp_port_range %s doesn't include ports "
                "between above 5900, needed for VNC services. "
                "QEMU targets needing VNC support will fail to start "
                "complaining about 'vnc-port' not defined",
                ttbl.config.tcp_port_range)
        else:
            target.fsdb.set("vnc-port", "%s" % (tcp_port_base + 1 - 5900))
            # this one is the raw port number
            target.fsdb.set("vnc-tcp-port", "%s" % (tcp_port_base + 1))

        self.cmdline_extra = []
        image_keys = target.fsdb.keys("qemu-image-*")
        #
        # Images interface: flash() below has been used to set images
        # to run, this will feed them into QEMU
        #
        if 'qemu-image-bios' in image_keys:
            self.cmdline_extra += [ "-bios", "%(qemu-image-bios)s" ]
        if 'qemu-image-kernel' in image_keys:
            self.cmdline_extra += [ "-kernel", "%(qemu-image-kernel)s" ]
        if 'qemu-image-kernel-args' in image_keys:
            self.cmdline_extra += [ "-append", "%(qemu-image-kernel-args)s" ]
        if 'qemu-image-initrd' in image_keys:
            self.cmdline_extra += [ "-initrd", "%(qemu-image-initrd)s" ]

        #
        # Network support bits--add command line options to connect
        # this VM to the networks the target declares
        #
        # For each network we are connected to, there must be a
        # network_tap_pc power rail controller that sets up the
        # network devices for us before starting QEMU.
        #
        # We look at it to setup the QEMU side of things as extra
        # command line options.
        #
        # - network name/icname: comes from the tuntap-ICNAME property
        #   created by the network_tap_pc power rail controller that
        #   the configuration must put on before the qemu power rail
        #   controller.
        #
        # - model: comes from what HW it has to emulate; each arch has a
        #   default or you can set for all with property qemu-model or
        #   qemu-model-ICNAME (for that specifc interconnect).
        #
        #   It has to be a valid QEMU model or QEMU will reject it
        #   with an error. You can find valid models with::
        #
        #     qemu-system-ARCH -net nic,model=help
        #
        # Zephyr, e.g., supports a few: lan9118 stellaris e1000 (from)::
        #
        #   $ grep --color -nH --null -rie ETH_NIC_MODEL
        #   drivers/ethernet/Kconfig.smsc911x:13:config ETH_NIC_MODEL$
        #   drivers/ethernet/Kconfig.stellaris:15:config ETH_NIC_MODEL$
        #   drivers/ethernet/Kconfig.e1000:16:config ETH_NIC_MODEL$
        fds = []
        try:
            for tap, if_name in target.fsdb.get_as_dict("tuntap-*").iteritems():
                # @tap is tuntap-NETWORK, the property set by
                # powe rail component network_tap_pc.
                _, ic_name = tap.split("-", 1)
                mac_addr = target.tags['interconnects'][ic_name]['mac_addr']
                model = commonl.name_make_safe(
                    target.fsdb.get("qemu-model-" + ic_name,
                                    target.fsdb.get("qemu-model",
                                                    self.nic_model)))

                # There is no way to cahole QEMU to say: hey, we
                # already have a tap interface configured for you, use
                # it...other than to open it and pass the file
                # descriptor to it.
                # So this finds the /dev/tap* file which matches the
                # interface created with tuntap- (class
                # network_tap_pc), opens it and passes the descriptor
                # along to qemu, then closes the FD, since we don't
                # need it.
                tapindex = commonl.if_index(if_name)
                # Need to wait for udev to reconfigure this for us to have
                # access; this is done by a udev rule installed
                # (/usr/lib/udev/rules.d/80-ttbd.rules)
                tapdevname = "/dev/tap%d" % tapindex
                ts0 = time.time()
                ts = ts0
                timeout = 5
                fd = None
                while ts - ts0 < timeout:
                    try:
                        fd = os.open(tapdevname, os.O_RDWR, 0)
                        fds.append(fd)
                        break
                    except OSError as e:
                        target.log.error(
                            "%s: couldn't open %s after"
                            " +%.1f/%.1fs, retrying: %s",
                            ic_name, tapdevname, ts - ts0, timeout, e)
                        time.sleep(0.25)
                        ts = time.time()
                else:
                    raise RuntimeError(
                        "%s: timedout (%.1fs) opening /dev/tap%d's;"
                        " udev's /usr/lib/udev/rules.d/80-ttbd.rules"
                        " didn't set permissions?"
                        % (ic_name, timeout, tapindex))

                self.cmdline_extra += [
                    "-nic",
                    "tap,fd=%d,id=%s,model=%s,mac=%s,br=_b%s" \
                    % (fd, ic_name, model, mac_addr, ic_name )
                ]

            if not fds:
                # No tuntap network attachments -> no network
                # support. Cap it.
                self.cmdline_extra += [ '-nic', 'none' ]

            #
            # Ok, so do actually start
            #
            # if the debug port is snatched before we start by someone
            # else, this will fail and we'll have to retry--this is
            # why the power component is set to paranoid mode, so the
            # power interface automatically retries it if it fails.
            ttbl.power.daemon_c.on(self, target, component)

            # Those consoles? update their generational counts so the
            # clients can know they restarted
            if hasattr(target, "console"):
                for console in target.console.impls.keys():
                    ttbl.console.generation_set(target, console)

        finally:
            for fd in fds:		# close fds we opened for ...
                os.close(fd)            # ... networking, unneeded now
        #
        # Debugging interface--if the target is not in debugging mode,
        # tell QEMU to start right away
        #
        if target.fsdb.get("debug") == None:
            self.debug_resume(target, component)

    #
    # Debug interface
    #
    def debug_list(self, target, component):
        if self.get(target, component):	# power is on?
            return {
                'GDB': "tcp:%s:%s" % (
                    socket.getfqdn('0.0.0.0'),
                    target.fsdb.get("qemu-gdb-tcp-port")
                )
            }
        # power is off, but debugging is on
        return {}

    def debug_start(self, target, components):
        # nothing to do here, QEMU is always started with debugging enabled
        pass

    def debug_stop(self, target, components):
        # nothing to do here, QEMU is always started with debugging enabled
        pass

    def debug_halt(self, target, _components):
        with qmp_c(os.path.join(target.state_dir, "qemu.qmp")) as qmp:
            r = qmp.command("stop")
            if r != {}:
                raise RuntimeError("command 'stop' failed: %s" % r)
            # prelaunch is what we get when we are waiting for GDB
            r = qmp.command("query-status")
            if r['status'] != "paused":
                raise RuntimeError("command 'stop' didn't halt: %s" % r)

    def debug_resume(self, target, _components):
        with qmp_c(os.path.join(target.state_dir, "qemu.qmp")) as qmp:
            r = qmp.command("cont")
            if r != {}:
                raise RuntimeError("command 'cont' failed: %s" % r)
            # prelaunch is what we get when we are waiting for GDB
            r = qmp.command("query-status")
            if r['status'] != "running":
                raise RuntimeError("command 'cont' didn't start: %s" % r)

    def debug_reset(self, target, _components):
        with qmp_c(os.path.join(target.state_dir, "qemu.qmp")) as qmp:
            r = qmp.command("system_reset")
            if r != {}:
                raise RuntimeError("command 'system_reset' failed: %s" % r)
            # prelaunch is what we get when we are waiting for GDB
            r = qmp.command("query-status")
            if r['status'] not in ( "running", "prelaunch" ):
                raise RuntimeError("command 'system_reset' "
                                   "didn't halt: %s" % r)


class plugger_c(ttbl.things.impl_c):
    """
    Adaptor class to plug host-platform USB devices to QEMU VMs

    :param str name: thing's name

    :param dict kwargs: parameters for :meth:`qmp_c.command`'s
      `device_add` method, which for example, could be:

      - driver = "usb-host"
      - hostbus = BUSNUMBER
      - hostaddr = USBADDRESS

    Sadly, there is no way to tell  QEMU to hotplug a device by serial
    number, so according to docs, the  only way to do it is hardcoding
    the device and bus number.

    eg:

    >>> ttbl.config.target_add(
    >>>     ttbl.test_target("drive_34"),
    >>>     tags = { },
    >>>     target_type = "usb_disk")
    >>>
    >>> ttbl.config.targets['qu04a'].interface_add(
    >>>     "things",
    >>>     ttbl.things.interface(
    >>>         drive_34 = ttbl.qemu.plugger_c(
    >>>             "drive_34", driver = "usb-host", hostbus = 1, hostaddr = 67),
    >>>         usb_disk = "drive_34",	# alias for a101_04
    >>>     )
    >>> )


    """
    def __init__(self, name, **kwargs):
        self.kwargs = kwargs
        self.name = name
        ttbl.things.impl_c.__init__(self)

    def plug(self, target, thing):
        assert isinstance(target, ttbl.test_target)

        # Now with QMP, we add the device
        with qmp_c(target.pidfile + ".qmp") as qmp:
            r = qmp.command("device_add", id = self.name, **self.kwargs)
            # prelaunch is what we get when we are waiting for GDB
            if r == {}:
                return
            raise RuntimeError("%s: cannot plug '%s': %s"
                               % (self.name, thing.id, r))

    def unplug(self, target, thing):
        assert isinstance(target, ttbl.test_target)

        # Now with QMP, we add the device
        with qmp_c(target.pidfile + ".qmp") as qmp:
            r = qmp.command("device_del", **self.kwargs)
            # prelaunch is what we get when we are waiting for GDB
            if r == {}:
                return
            raise RuntimeError("%s: cannot plug '%s': %s"
                               % (self.name, thing.id, r))

    def get(self, target, thing):
        # FIXME: this should query QEMU for the devices plugged, but
        # need to do more research on how
        return target.fsdb.get("thing-" + thing.id) ==  'True'


class network_tap_pc(ttbl.power.impl_c):
    """Creates a tap device and attaches it to an interconnect's network
    device

    A target declares connectivity to one or more interconnects; when
    this object is instantiated as part of the power rail:

    >>> target.interface_add(
    >>>     "power",
    >>>     ttbl.power.interface(
    >>>         ...
    >>>         ( "tuntap-nwka", pc_network_tap() ),
    >>>         ...
    >>>     )
    >>> )

    because the component is called *tuntap-nwka*, the driver assumes
    it needs to tap to the interconnect *nwka* because that's where
    the target is connected::

      $ tcf list -vv TARGETNAME | grep -i nwka
        interconnects.nwka.ipv4_addr: 192.168.120.101
        interconnects.nwka.ipv4_prefix_len: 24
        interconnects.nwka.ipv6_addr: fc00::a8:78:65
        interconnects.nwka.ipv6_prefix_len: 112
        interconnects.nwka.mac_addr: 94:c6:91:1c:9e:d9

    Upon powering on the target, the *on()* method will create a
    network interface and link it to the network interface that
    represents the interconnect has created when powering on
    (:class:`conf_00_lib.vlan_pci`)--it will assign it in the TCF
    server the IP addresses described above.

    The name of the interface created is stored in a target property
    called as the component (for our example, it will be a property
    called *tuntap-nwka*) so that other components can use it:

    - For QEMU, for example, you need a command line such as::

        -nic tap,model=ETH_NIC_MODEL,script=no,downscript=no,ifname=IFNAME

      however, the :class:`ttbl.qemu.pc` driver automatically
      recognizes a *tuntap-NETWORKNAME* is there and inserts the
      command line needed.

    When the target is powered off, this component will just remove
    the interface.

    """
    def __init__(self):
        ttbl.power.impl_c.__init__(self)
        if not commonl.prctl_cap_get_effective() & 1 << 12:
            # If we don't have network setting privilege,
            # don't even go there
            # CAP_NET_ADMIN is 12 (from /usr/include/linux/prctl.h
            raise RuntimeError("daemon lacks CAP_NET_ADMIN: unable to"
                               " add networking capabilities ")


    @staticmethod
    def _component_validate(target, component):
        # component must be tap-ICNAME
        # Create a TAP interface to ICNAME
        # target must be in ICNAME interfaconnce
        if not component.startswith("tuntap-"):
            raise ValueError(
                "%s: can't create TAP interface:"
                " cannot recognize component name as something we"
                " can use to create a TAP interface (expect tap-ICNAME)"
                % component)
        _, ic_name = component.split("-", 1)
        # ensure target is a member of icname
        if ic_name not in target.tags.get('interconnects', {}):
            raise ValueError(
                "%s: can't create TAP interface:"
                " target '%s' is not connected to interconnect '%s'"
                % (component, target.id, ic_name))
        # we need a system unique name, since what this creates is
        # global to the whole system--we can easily run out of naming
        # space though, as network interfaces are limited in size --
        # this probably could just hash it all, but then tracing would
        # be a pain...
        if_name = "t%s%s" % (ic_name, target.id)
        if len(if_name) >= 15:	# Linux's max network interface name is 15
            # so we do tHASH
            if_name = "t" + commonl.mkid(if_name, 6)
        return if_name, ic_name


    def on(self, target, component):
        if_name, ic_name = self._component_validate(target, component)

        kws = dict(
            id = target.id,
            ic_name = ic_name,
            if_name = if_name,
        )
        ic_data = target.tags['interconnects'][ic_name]
        try:
            kws['ipv4_addr'] = ic_data['ipv4_addr']
            kws['ipv4_prefix_len'] = ic_data['ipv4_prefix_len']
            kws['ipv6_addr'] = ic_data['ipv6_addr']
            kws['ipv6_prefix_len'] = ic_data['ipv6_prefix_len']
            kws['mac_addr'] = ic_data['mac_addr']
        except KeyError as e:
            raise ValueError(
                "%s: can't create TAP interface:"
                " target '%s' declares connection to interconnect '%s'"
                " but is missing field '%s'"
                % (component, target.id, ic_name, str(e)))

        if not commonl.if_present("_b%(ic_name)s" % kws):
            target.log.info("%(ic_name)s: assuming network off since netif "
                            "_b%(ic_name)s is not present", kws)
            return

        commonl.if_remove_maybe(if_name)	# ensure no leftovers
        subprocess.check_call(
            "ip link add "
            "  link _b%(ic_name)s"		# created by the interconnect
            "  name %(if_name)s"
            "  address %(mac_addr)s"
            "  up"
            "  type macvtap mode bridge" % kws,
            shell = True, stderr = subprocess.STDOUT)
        subprocess.check_call(
            "ip link set %(if_name)s"
            "  promisc on "	# needed so we can wireshark in
            "  up" % kws,
            shell = True, stderr = subprocess.STDOUT)
        # We don't assign IP addresses here -- we leave it for the
        # client; if we do, for example QEMU won't work as it is just
        # used to associate the interface
        target.fsdb.set(component, if_name)

    def off(self, target, component):
        target.fsdb.set(component, None)
        if_name, _ = self._component_validate(target, component)
        commonl.if_remove_maybe(if_name)

    def get(self, target, component):
        if_name, _ = self._component_validate(target, component)
        # if there is a network interface, it will be symlinked to
        # from /sys/class/net/IFNAME -> place
        return os.path.isdir("/sys/class/net/" + if_name)
