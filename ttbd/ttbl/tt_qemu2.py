#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
General driver to create targets that implement a virtual machine using QEMU.

.. note:: This is now replacing :mod:`ttbl.tt_qemu` which is now
          deprecated.

:class:`ttbl.tt_qemu2.tt_qemu` is a generic class that implements a
target which supports the following interfaces:

- power control
- serial consoles
- image flashing
- debugging
- networking
- :ref:`provisioning mode <provisioning_os>`

it is however a raw building block which requires extra
configuration. To create targets, use :func:`conf_00_lib.qemu_pos_add`
(for example).

"""
import contextlib
import errno
import json
import logging
import os
import re
import socket
import subprocess
import time

import commonl
import ttbl
import ttbl.things

class qmp_c(object):
    """
    Dirty handler for the Qemu Monitor Protocol that allows us to run
    QMP commands and report on status.
    """
    def __init__(self, sockfile):
        self.sockfile = sockfile
        self.log = logging.root.getChild("qmp")
        self.sk = None

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
            logfilename = self.sockfile.replace(".pid.qmp", "-stderr.log")
            if os.path.exists(logfilename):
                with open(logfilename) as logfile:
                    for line in logfile:
                        self.log.error("%s: qemu log: %s"
                                       % (self.sockfile, line.strip()))
            else:
                self.log.error("%s: (no qemu log at '%s')"
                               % (self.sockfile, logfilename))
            raise RuntimeError("%s: cannot connect after %d tries"
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



class plugger(ttbl.things.impl_c):
    """Plugger class to plug external devices to QEMU VMs

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
    >>>         drive_34 = ttbl.tt_qemu2.plugger(
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
        assert isinstance(target, tt_qemu)

        # Now with QMP, we add the device
        with qmp_c(target.pidfile + ".qmp") as qmp:
            r = qmp.command("device_add", id = self.name, **self.kwargs)
            # prelaunch is what we get when we are waiting for GDB
            if r == {}:
                return
            raise RuntimeError("%s: cannot plug '%s': %s"
                               % (self.name, thing.id, r))

    def unplug(self, target, thing):
        assert isinstance(target, tt_qemu)

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


class tt_qemu(
        ttbl.test_target,
        ttbl.tt_power_control_mixin,
        ttbl.tt_power_control_impl,
        ttbl.test_target_images_mixin,
        ttbl.tt_debug_mixin,
        ttbl.test_target_console_mixin):
    """
    Implement a test target that runs under a QEMU subprocess.

    Supports power control, serial consoles and image flashing.

    :param str qemu_cmdline: command line to start QEMU, as
      described in :data:`tt_qemu.qemu_cmdline`.

      FIXME: describe better

    :param list(str) consoles: names of serial consoles to start by
      adding command line configuration. Note each string needs to be
      a simple string [a-zA-Z0-9].

      For the console read interface to work, the configuration must
      export a logfile called ``NAME-console.read`` in the state
      directory. For write to work, it must provide a socket
      ``NAME-console.write``::

        -chardev socket,id=ttyS0,server,nowait,path=%(path)s/NAME-console.write,logfile=%(path)s/NAME-console.read
        -serial chardev:ttyS0

    Using power_on_pre, power_on_post and power_off_pre functions, one
    can add functionality without modifying this file.

    **WARNING**

    Note this might be called from different processes who share the
    same configuration; hence we can't rely on any runtime
    storage. Any values that are needed are kept on a filesystem
    database (`self.fsdb`). We start the process with Python's
    subprocess.Popen(), but then it goes on background and if the
    parent dies, the main server process will reap it (as prctl() has
    set with SIG_IGN on SIGCHLD) and any subprocess of the main
    process might kill it when power-off is called on it.

    .. admonition:: Examples

       - :class:`VMs for Zephyr OS <conf_00_lib_mcu.tt_qemu_zephyr>`

    """

    def __init__(self, name, qemu_cmdline, consoles = None,_tags = None):
        assert isinstance(name, basestring)
        assert isinstance(qemu_cmdline, basestring)
        assert consoles == None or \
            all(isinstance(i, basestring) for i in consoles)
        assert isinstance(qemu_cmdline, basestring)
        assert _tags == None or isinstance(_tags, dict)
        if _tags == None:
            _tags = {}
        ttbl.test_target.__init__(self, name, _tags = _tags)
        ttbl.tt_power_control_mixin.__init__(self)
        ttbl.tt_power_control_impl.__init__(self)
        ttbl.test_target_images_mixin.__init__(self)
        ttbl.test_target_console_mixin.__init__(self)
        ttbl.tt_debug_mixin.__init__(self)
        #: Command line to launch QEMU
        self.qemu_cmdline = qemu_cmdline
        #: Runtime additions to QEMU's command line
        self.qemu_cmdline_append = ""
        self.pidfile = None
        self.bsp = self.tags['bsp_models'].keys()[0]
        if not self.bsp in self.tags['bsps']:
            raise ValueError('%s: BSP not described in tags' % self.bsp)
        if len(self.tags['bsps']) > 1:
            raise ValueError("%s: target contains more than on BSP, "
                             "not supported" % name)
        self.pidfile = os.path.join(self.state_dir, "qemu.pid")
        # every time we are going to power up the virtual machine,
        # clean the list of command line options we are going to
        # append before getting started, as the power up sequence
        # might generate new ones or refresh them.
        self.power_on_pre_fns.append(self._power_on_pre_clear)
        self.consoles = consoles
        self.tags['consoles'] = consoles

    def _qmp_running(self):
        """
        Connect to the Qemu Monitor socket and issue a status command,
        verify we get 'running', giving it some time to report.

        :returns: *True* if the QEMU VM is running ok, *False* otherwise
        :raises: anything on errors
        """
        try:
            with qmp_c(self.pidfile + ".qmp") as qmp:
                r = qmp.command("query-status")
                # prelaunch is what we get when we are waiting for GDB
                return r['status'] == "running" or r['status'] == 'prelaunch'
        except RuntimeError as e:
            self.log.error("Can't connect to QMP: %s" % e)
            logfilename = self.pidfile.replace(".pid", "-strace.log")
            if os.path.exists(logfilename):
                with open(logfilename) as logfile:
                    for line in logfile:
                        self.log.error("%s: qemu log: %s"
                                       % (logfilename, line.strip()))
            else:
                self.log.error("%s: (no qemu log)" % (logfilename))
            raise
        except IOError as e:
            if e.errno == errno.ENOENT:
                return False
            if e.errno == errno.ECONNREFUSED:
                return False
            raise

    # Debugging interface
    def debug_do_start(self, _tt_ignored):
        pass

    def debug_do_stop(self, _tt_ignored):
        pass

    def debug_do_info(self, _tt_ignored):
        if self.fsdb.get('powered') != None:
            s = ""
            gdb_tcp_port_s = self.fsdb.get("debug-gdb-tcp-port")
            if gdb_tcp_port_s == None:
                s += "GDB server: not available\n"
            else:
                s += "GDB server: tcp:%s:%s\n" \
                     % (socket.getfqdn('0.0.0.0'), gdb_tcp_port_s)
        else:
            s = "[target is off, no debugging support]"
        return s

    # Image management interface
    def image_do_set(self, image_type, image_name):
        if image_type == "kernel":
            pass
        elif image_type == "kernel-" + self.bsp:
            _image_type = "kernel"
        else:
            raise ValueError("Unknown image type %s" % image_type)

        self.fsdb.set("qemu-image-kernel", image_name)

    def images_do_set(self, images):
        pass

    def _power_get(self):
        cmdline = self.fsdb.get("qemu-cmdline")
        if cmdline == None:
            return None
        r = commonl.process_alive(self.pidfile, cmdline)
        return r

    def _power_on_pre_clear(self, _target):
        # we always start with no command line additions, we determine
        # these as we are powering on
        self.qemu_cmdline_append = ""

    _r_ident = re.compile('[^a-z0-9A-Z]+')

    def _power_on_pre_consoles(self, _target):
        # Configure serial consoles
        for console in self.consoles:
            self.qemu_cmdline_append += \
                "-chardev socket,id=%s,server,nowait" \
                ",path=%%(path)s/%s-console.write" \
                ",logfile=%%(path)s/%s-console.read" \
                " -serial chardev:%s " % \
                (console, console, console, console)

    # hooks for starting/stopping networking
    def _power_on_pre_nw(self, _target):
        # We need the __init__ part doing it earlier because remember,
        # these might be running different processes, and the basic
        # self.qemu_cmdline array has to be initialized so we can
        # find the actual binary being used.
        kws = dict(self.kws)
        # Get fresh values for these keys
        for key in self.fsdb.keys():
            if key.startswith("qemu-"):
                kws[key] = self.fsdb.get(key)

        # Setup network stuff, create virtual tap interfaces
        for ic_name, ic_kws in self.tags.get('interconnects', {}).iteritems():
            if 'ipv4_addr' in ic_kws or 'ipv6_addr' in ic_kws:
                _kws = dict(kws)
                _kws.update(ic_kws)
                _kws['ic_name'] = ic_name
                # QEMU device ident only allows a-zA-Z0-9-, starting
                # with letter
                _kws['ident'] = "id" + self._r_ident.sub("", _kws['mac_addr'])
                # CAP_NET_ADMIN is 12 (from /usr/include/linux/prctl.h
                if not commonl.prctl_cap_get_effective() & 1 << 12:
                    # If we don't have network setting privilege,
                    # don't even go there
                    self.log.warning("daemon lacks CAP_NET_ADMIN: unable to "
                                     "add networking capabilities ")
                    continue

                if not commonl.if_present("_b%s" % ic_name):
                    self.log.warning("network %s powered off? networking "
                                     "disabled" % ic_name)
                    # If the network is not powered up, skip it
                    # FIXME: replace with it calling vlan_pci.something()
                    # that brings up the basic interface (_bICNAME) so
                    # that once we power the network, it works
                    continue

                commonl.if_remove_maybe("t%s%s" % (ic_name, self.id))
                subprocess.check_call(
                    "ip link add "
                    "  link _b%(ic_name)s "
                    "  name t%(ic_name)s%(id)s"
                    "  address %(mac_addr)s"
                    "  up"
                    "  type macvtap mode bridge; "
                    "ip link set t%(ic_name)s%(id)s"
                    "  promisc on "
                    "  up" % _kws, shell = True)

                # Add to the command line
                # note model=virtio WORKS with QEMU's BIOS OVMW_CODE.fd
                self.qemu_cmdline_append += \
                    " -net nic,id=%(ident)s,model=virtio,macaddr=%(mac_addr)s" \
                    " -net tap,fd=0,name=%(ident)s" % _kws

            # Add a nat/host interface?
            if ic_name == 'nat_host':
                raise RuntimeError("NAT configuration is currently broken")
                # we hardcode the MAC address of the NAT ethernet
                # interface, which we'll also add in the configuration
                # for systemd-network in /etc/systemd/network for it
                # to do DHCP. There is only one of those interfaces
                # per virtual host, so it will never conflict with
                # anything and we don't use the form of addressing in
                # any MAC we generate.
                mac_addr = "02:01:01:01:01:01"
                self.qemu_cmdline_append += \
                    " -net nic,name=nat_host,model=virtio,macaddr=%s" \
                    " -net user,id=nat_host,net=192.168.200.0/24,dhcpstart=192.168.200.10 " \
                     % mac_addr

        # If no network interfaces we added, remove the default
        # networking QEMU does
        if "-net" not in self.qemu_cmdline \
           and "-net" not in self.qemu_cmdline_append:
            self.qemu_cmdline_append += "-net none "


    def _power_off_post_nw(self, _target):
        # Tear down network stuff
        for ic_name, _ in self.tags.get('interconnects', {}).iteritems():
            commonl.if_remove_maybe("t%s%s" % (ic_name, self.id))

    def _qmp_start(self, _target):
        if self.fsdb.get("debug") != None:
            # Don't start yet, let a debugger command do it
            return False
        try:
            with qmp_c(self.pidfile + ".qmp") as qmp:
                r = qmp.command("cont")
                if r != {}:
                    raise RuntimeError("Command 'cont' failed: %s" % r)
                # prelaunch is what we get when we are waiting for GDB
                r = qmp.command("query-status")
                if r['status'] != "running":
                    return False
        except IOError:
            raise
        return True

    def _qemu_preexec_nw(self):
        # This is called by subprocess.Popen after spawning to run
        # qemu from tt_qemu.power_on_do() right before spawning Qemu
        # for us.
        #
        # See doc block on top of this class and on :class:`vlan_pci`
        # for why file descriptor 0.
        #
        # We will find out which is the index of the TAP device
        # assigned to this, created on _image_power_on_pre and open
        # file desctriptor 0 to it, then leave it open for Qemu to
        # tap into it.
        count = 0
        for ic_name, ic_kws in self.tags.get('interconnects', {}).iteritems():
            if not 'ipv4_addr' in ic_kws and not 'ipv6_addr' in ic_kws:
                continue
            if count > 0:
                raise NotImplementedError(
                    "QEMU Networking cannot implement "
                    "multiple networks at this time "
                    "(when trying to connec to %s)" % ic_name)
            kws = dict(ic_kws)
            kws.update(self.kws)
            kws['ic_name'] = ic_name
            if not commonl.if_present("_b%s" % ic_name):
                self.log.warning("network %s powered off? networking "
                                 "disabled" % ic_name)
                # If the network is not powered up, skip it
                # FIXME: replace with it calling vlan_pci.something()
                # that brings up the basic interface (_bICNAME) so
                # that once we power the network, it works
                continue

            tapindex = commonl.if_index("t%(ic_name)s%(id)s" % kws)
            assign = 0
            # Need to wait for udev to reconfigure this for us to have
            # access; this is done by a udev rule installed
            # (/usr/lib/udev/rules.d/80-ttbd.rules)
            tapdevname = "/dev/tap%d" % tapindex
            count = 1
            top = 4
            while not os.access(tapdevname, os.R_OK | os.W_OK):
                if count >= top:
                    msg = "%s: timed out waiting for udev to set " \
                        "permissions in /usr/lib/udev/rules.d/80-ttbd.rules" \
                        % tapdevname
                    self.log.error(msg)
                    raise RuntimeError(msg)
                time.sleep(0.25)
                count += 1
            fd = os.open("/dev/tap%d" % tapindex, os.O_RDWR, 0)
            if fd != assign:
                # there, reassign it to fd @assign
                os.dup2(fd, assign)
                os.close(fd)
                # leave fd assign open for QEMU!
            count += 1

    # power control interface
    def _qemu_launch(self, kws):
        gdb_tcp_port = commonl.tcp_port_assigner(
            1 , port_range = ttbl.config.tcp_port_range)
        self.fsdb.set("debug-gdb-tcp-port", "%s" % gdb_tcp_port)
        console_out_fname = os.path.join(
            self.state_dir, "console-0.log")
        errfname = os.path.join(
            self.state_dir, "stderr.log")
        try:
            # Make sure we wipe the PID file -- sometimes a pidfile is
            # left over and it seems to override it, so the reading
            # becomes corrupt
            commonl.rm_f(self.pidfile)
            qemu_cmdline = \
                (self.qemu_cmdline % kws).split() \
                + (self.qemu_cmdline_append % kws).split() \
                + [
                    # Don't add -daemonize! This way this is part of
                    # the process tree and killed when we kill the
                    # parent process
                    # We use QMP to find the PTY assigned
                    "-qmp", "unix:%s.qmp,server,nowait" % self.pidfile,
                    # Always start in debug mode -- this way the
                    # whole thing is stopped until we unleash it
                    # with QMP; this allows us to first start
                    # daemons that we might need to start
                    "-S",
                    "-pidfile", self.pidfile,
                    "-gdb", "tcp:0.0.0.0:%d" % gdb_tcp_port,
                ]
            self.fsdb.set("qemu-cmdline", qemu_cmdline[0])
        except KeyError as e:
            msg = "bad QEMU command line specification: " \
                  "uninitialized key %s" % e
            self.log.error(msg)
            commonl.raise_from(RuntimeError(msg), e)
        self.log.debug("QEMU cmdline %s" % " ".join(qemu_cmdline))
        try:
            def _local_preexec_fn():
                self._qemu_preexec_nw()
                # Open file descriptors for stdout/stderr to a
                # logfile, because -D is not really working. We
                # need it to check startup errors for things that
                # need a retry.
                commonl.rm_f(errfname)
                logfd = os.open(errfname,
                                # O_CREAT: Always a new file, so
                                # we can check for errors and not
                                # get confused with previous runs
                                os.O_WRONLY | os.O_EXCL |os.O_CREAT, 0o0644)
                os.dup2(logfd, 1)
                os.dup2(logfd, 2)
                os.close(logfd)

            p = subprocess.Popen(qemu_cmdline,
                                 shell = False, cwd = self.state_dir,
                                 close_fds = True,
                                 preexec_fn = _local_preexec_fn)
            self.log.debug("QEMU: console @ %s" % console_out_fname)
            # Give it a few secs to start, the pidfile has been
            # deleted before starting -- note 4 was found by
            # ad-hoc experimentation, sometimes depending on system load it
            # takes more or less.
            timeout = 10
            ts0 = time.time()
            while True:
                if time.time() - ts0 > timeout:
                    lines = []
                    with open(errfname) as f:
                        count = 0
                        for line in f:
                            lines.append("log: " + line)
                            if count > 5:
                                lines.append("log: ...")
                                break
                    raise RuntimeError("QEMU: did not start after %.0fs\n"
                                       "%s" % (timeout, "\n".join(lines)))
                try:
                    if self._qmp_running():
                        # FIXME: race condition
                        ttbl.daemon_pid_add(p.pid)
                        return True
                except RuntimeError as e:
                    self.log.warning("QEMU: can't read QMP: %s"
                                     % str(e))
                    # fall through, let it retry
                # Check errors during startup
                with open(errfname, "r") as logf:
                    causes_for_retry = [
                        # bah, race condition: since we chose the
                        # port we wanted to use and until we
                        # started using it someone took it. Retry
                        'Failed to bind socket: Address already in use',
                    ]
                    for line in logf:
                        for cause in causes_for_retry:
                            if cause in line:
                                self.log.info(
                                    "QEMU: retrying because found in "
                                    "logfile: %s", cause)
                                return False
                time.sleep(0.25)
                # nothing runs after this, either it returns or raises
        except (OSError, ValueError) as e:
            self.log.debug("QEMU: launch failure: %s", e)
            raise

    # power control interface
    def power_on_do(self, _target):
        r = self._power_get()
        if r != None:
            return
        # Ensure anything that might have been left around is
        # killed and destroyed
        self._power_off_do()
        kws = dict(bsp = self.bsp)
        kws.update(self.kws)
        for key in self.fsdb.keys():
            if key.startswith("qemu-"):
                kws[key] = self.fsdb.get(key)
        # try to start qemu, retrying if we have to
        for _ in range(5):
            if self._qemu_launch(kws):
                break
        else:
            raise RuntimeError("QEMU: did not start after 5 tries")

    def _power_off_do(self):
        # Make sure the pidfile is removed, somehow it fails to do so
        pid = self._power_get()
        if pid != None:
            commonl.process_terminate(pid, pidfile = self.pidfile,
                                      tag = "QEMU: ")

        self.fsdb.set("qemu-cmdline", None)
        commonl.rm_f(self.pidfile + ".qmp")
        console_out_fname = os.path.join(self.state_dir, "console-1.log")
        commonl.rm_f(console_out_fname)

    def power_off_do(self, _target):
        self._power_off_do()

    # We just don't implement it
    # We could use QMP to ask QEMU to reset, but then re-setting up
    # all the network stuff becomes a pain because we are not using
    # QEMU's scripts (we can't yet, as we need to open an FD to pass a
    # macvtap interface).
    # So just default to a power cycle, which is what happens when
    # reset is not implemented
    #def reset_do(self, target):
    #    pass

    def power_get_do(self, _target):
        pid = self._power_get()
        if pid != None:
            return True
        return False

    # Console mixin
    # Any file SOMETHING-console.read describes a console that is available.
    def console_do_list(self):
        return self.consoles

    def _console_id_get(self, console_id):
        if console_id == None:
            console_id = self.consoles[0]
        elif not console_id in self.consoles:
            raise ValueError("unknown console %s (target has %s)"
                             % (console_id, "m ".join(self.consoles)))
        return console_id

    def console_do_read(self, console_id = None, offset = 0):
        console_id = self._console_id_get(console_id)
        # Reading is simple -- QEMU is designed to leave a logfile
        # with anything that comes from each console, named
        # NAME-console.read. We just read that, because our console IDs
        # are just those names.
        consolefname = os.path.join(self.state_dir,
                                    "%s-console.read" % console_id)
        if os.path.isfile(consolefname):
            #self.log.log(6, "QEMU %s: read @ %d from %s"
            #             % (console_id, offset, consolefname))
            # don't open codecs.open() UTF-8, as that will trip Flask
            # when passing the generator up to serve to the client
            ifd = open(consolefname, "rb")
            if offset > 0:
                ifd.seek(offset)
            return ifd
        else:
            return iter(())

    def console_do_size(self, console_id = None):
        console_id = self._console_id_get(console_id)
        consolefname = os.path.join(self.state_dir,
                                    "%s-console.read" % console_id)
        return os.stat(consolefname).st_size

    def console_do_write(self, data, console_id = None):
        console_id = self._console_id_get(console_id)
        # Reading is easy -- QEMU is designed to create a named socket
        # for read/writing the console named BSP-console.write. We
        # just open and write to it, because our console IDs are just
        # the BSP names.
        pipename = os.path.join(self.state_dir,
                                "%s-console.write" % console_id)
        if os.path.exists(pipename):
            with contextlib.closing(socket.socket(socket.AF_UNIX,
                                                  socket.SOCK_STREAM)) as s:
                s.connect(pipename)
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
                l = len(data)
                while l > 0:
                    if l >= chunk_size:
                        s.sendall(data[count:count + chunk_size])
                    else:
                        s.sendall(data[count:count + l])
                    time.sleep(0.15)
                    l -= chunk_size
                    count += chunk_size
        elif self.power_get_do(self) == False:
            raise RuntimeError("target is off")
        else:
            raise RuntimeError("This QEMU does not support writing to console")
