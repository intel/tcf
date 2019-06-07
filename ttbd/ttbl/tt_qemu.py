#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
.. note:: This is now deprecated and replaced by :mod:`ttbl.tt_qemu2`.
"""

import contextlib
import errno
import json
import logging
import os
import socket
import subprocess
import time

import commonl
import ttbl

class qmp_c(object):
    """
    Dirty handler for the Qemu Monitor Protocol that allows us to run
    QMP commands and report on status.
    """
    def __init__(self, sockfile):
        self.sockfile = sockfile
        self.log = logging.root.getChild("qmp")

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

    A subclass of this must provide a command line to start QEMU, as
    described in :data:`qemu_cmdlines`.

    For the console read interface to work, the configuration must export a
    logfile called BSP-console.read in the state directory. For write
    to work, it must provide a socket BSP-console.write::

      # Serial console tt_qemu.py can grok
      -chardev socket,id=ttyS0,server,nowait,path=%(path)s/%(bsp)s-console.write,logfile=%(path)s/%(bsp)s-console.read
      -serial chardev:ttyS0

    Using power_on_pre, power_on_post and power_off_pre functions, one
    can add functionality without modifying this file.

    :param bsps: list of BSPs to start in parallel (normally only one
      is set); information has to be present in the tags description
      for it to be valid, as well as command lines for starting
      each. If more than one BSP is available, this is the equivalent
      of having a multicore machine that can be asymetric. Thisis
      mostly used for testing.

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

       - :class:`VMs for Zephyr OS <conf_00_lib.tt_qemu_zephyr>`

    """

    def __init__(self, id, bsps, _tags):
        ttbl.test_target.__init__(self, id, _tags = _tags)
        ttbl.tt_power_control_mixin.__init__(self)
        ttbl.tt_power_control_impl.__init__(self)
        ttbl.test_target_images_mixin.__init__(self)
        ttbl.test_target_console_mixin.__init__(self)
        ttbl.tt_debug_mixin.__init__(self)
        # QEMU subprocesses (one for each BSP that is to be started in
        # parallel)
        self.bsps = bsps	# we need the originally sorted list
        # Verify we have BSP metadata for each
        self.pidfile = {}
        for bsp in self.bsps:
            if not bsp in self.tags['bsps']:
                raise ValueError('%s: BSP not described in tags' % bsp)
            self.pidfile[bsp] = os.path.join(self.state_dir, "%s.pid" % bsp)

        #: Command line to launch QEMU, keyed for the BSP it implements
        #: (eg: 'x86', or 'arc', or 'arm').
        #:
        #: Note this can contain %(FIELD)[sd] to replace values coming
        #: from ``self.kws``.
        #:
        #: - derivative classes can add values in their *__init__()* methods
        #: - default values:
        #:   - *path*: location of the directory where state is kept
        #:   - *targetname*: name of this target
        #:
        #:   - *bsp*: BSP on which we are acting (as a target might have
        #:     multiple BSPs)
        #:
        #: :func:power_on_do() will add a few command line options to add
        #: QMP socket that we use to talk to QEMU, to introduce a pidfile,
        #: and a GDB socket (for debugging).
        #:
        #: Note this is per-instance and not per-class as each
        #: instance might add different command line switches based on
        #: its networking needs (for example)
        self.qemu_cmdlines = {}

    def _qmp_running(self, bsp):
        """
        Connect to the Qemu Monitor socket and issue a status command,
        verify we get 'running', giving it some time to report.

        :returns: *True* if the QEMU VM is running ok, *False* otherwise
        :raises: anything on errors
        """
        try:
            with qmp_c(self.pidfile[bsp] + ".qmp") as qmp:
                r = qmp.command("query-status")
                # prelaunch is what we get when we are waiting for GDB
                return r['status'] == "running" or r['status'] == 'prelaunch'
        except RuntimeError as e:
            self.log.error("Can't connect to QMP: %s" % e)
            logfilename = self.pidfile[bsp].replace(".pid", "-strace.log")
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
    def debug_do_start(self, tt_ignored):
        pass

    def debug_do_stop(self, tt_ignored):
        pass

    def debug_do_info(self, tt_ignored):
        if self.fsdb.get('powered') != None:
            s = ""
            for bsp in self.bsps:
                gdb_tcp_port_s = self.fsdb.get("debug-%s-gdb-tcp-port" % bsp)
                if gdb_tcp_port_s == None:
                    s += "GDB server [%s]: not available\n" % bsp
                else:
                    s += "GDB server [%s]: tcp:%s:%s\n" \
                         % (bsp, socket.getfqdn('0.0.0.0'), gdb_tcp_port_s)
        else:
            s = "[target is off, no debugging support]"
        return s

    # Image management interface
    def image_do_set(self, image_type, image_name):
        _image_type = image_type[:7]
        if _image_type == "kernel":	# We default to the first BSP
            bsp = self.bsps[0]
        elif _image_type == "kernel-":
            bsp = image_type[7:]
            _image_type = "kernel"
        else:
            raise ValueError("Unknown image type %s" % image_type)

        if not bsp in self.tags['bsps']:
            raise IndexError("Unsupported bsp %s (expected %s)"
                             % (bsp, ", ".join(list(self.tags['bsps'].keys()))))
        if _image_type == "kernel":
            self.fsdb.set("qemu-image-kernel-%s" % bsp, image_name)
        else:
            raise ValueError("%s: image type '%s' not supported")

    def images_do_set(self, images):
        pass

    def _power_get_bsp(self, bsp):
        cmdline = self.fsdb.get("qemu-cmdline-%s" % bsp)
        if cmdline == None:
            return None
        r = commonl.process_alive(self.pidfile[bsp], cmdline)
        return r

    def _qmp_start(self):
        if self.fsdb.get("debug") != None:
            # Don't start yet, let a debugger command do it
            return
        for bsp in self.bsps:
            try:
                with qmp_c(self.pidfile[bsp] + ".qmp") as qmp:
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

    # power control interface
    def _qemu_launch(self, bsp, kws):
        gdb_tcp_port = commonl.tcp_port_assigner(
            1, port_range = ttbl.config.tcp_port_range)
        self.fsdb.set("debug-%s-gdb-tcp-port" % bsp, "%s" % gdb_tcp_port)
        console_out_fname = os.path.join(
            self.state_dir, "console-%s.log" % bsp)
        errfname = os.path.join(
            self.state_dir, "%s-stderr.log" % bsp)
        try:
            # Make sure we wipe the PID file -- sometimes a pidfile is
            # left over and it seems to override it, so the reading
            # becomes corrupt
            commonl.rm_f(self.pidfile[bsp])
            qemu_cmdline = \
                (self.qemu_cmdlines[bsp] % kws).split() \
                + [
                    # Don't add -daemonize! This way this is part of
                    # the process tree and killed when we kill the
                    # parent process
                    # We use QMP to find the PTY assigned
                    "-qmp", "unix:%s.qmp,server,nowait" % self.pidfile[bsp],
                    # Always start in debug mode -- this way the
                    # whole thing is stopped until we unleash it
                    # with QMP; this allows us to first start
                    # daemons that we might need to start
                    "-S",
                    "-pidfile", self.pidfile[bsp],
                    "-gdb", "tcp:0.0.0.0:%d" % gdb_tcp_port,
                ]
            self.fsdb.set("qemu-cmdline-%s" % bsp, qemu_cmdline[0])
        except KeyError as e:
            msg = "bad QEMU command line specification: " \
                  "uninitialized key %s" % e
            self.log.error(msg)
            commonl.raise_from(RuntimeError(msg), e)
        self.log.debug("QEMU cmdline %s" % " ".join(qemu_cmdline))
        self.tags['bsps'][bsp]['cmdline'] = " ".join(qemu_cmdline)
        try:
            _preexec_fn = getattr(self, "qemu_preexec_fn", None)
            def _local_preexec_fn():
                if _preexec_fn:
                    _preexec_fn()
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
            self.log.debug("QEMU %s: console @ %s" % (bsp, console_out_fname))
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
                    raise RuntimeError("QEMU %s: did not start after %.0fs\n"
                                       "%s" % (bsp, timeout, "\n".join(lines)))
                try:
                    if self._qmp_running(bsp):
                        # FIXME: race condition
                        ttbl.daemon_pid_add(p.pid)
                        return True
                except RuntimeError as e:
                    self.log.warning("QEMU %s: can't read QMP: %s"
                                     % (bsp, str(e)))
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
                                    "QEMU %s: retrying because found in "
                                    "logfile: %s", bsp, cause)
                                return False
                time.sleep(0.25)
                # nothing runs after this, either it returns or raises
        except (OSError, ValueError) as e:
            self.log.debug("QEMU %s: launch failure: %s", bsp, e)
            raise

    # power control interface
    def power_on_do(self, _target):
        for bsp in self.bsps:
            r = self._power_get_bsp(bsp)
            if r != None:
                return
        # If none of the BSPs are powered up, the target is considere off
        for bsp in self.bsps:
            # Ensure anything that might have been left around is
            # killed and destroyed
            self._power_off_do_bsp(bsp)
            kws = dict(bsp = bsp)
            kws.update(self.kws)
            for key in list(self.fsdb.keys()):
                if key.startswith("qemu-"):
                    kws[key] = self.fsdb.get(key)
            # try to start qemu, retrying if we have to
            for _ in range(5):
                if self._qemu_launch(bsp, kws):
                    break
            else:
                raise RuntimeError("QEMU %s: did not start after 5 tries"
                                   % bsp)

    def _power_off_do_bsp(self, bsp):
        # Make sure the pidfile is removed, somehow it fails to do so
        pid = self._power_get_bsp(bsp)
        if pid != None:
            commonl.process_terminate(pid, pidfile = self.pidfile[bsp],
                                      tag = "QEMU[%s]: " % bsp)

        self.fsdb.set("qemu-cmdline-%s" % bsp, None)
        commonl.rm_f(self.pidfile[bsp] + ".qmp")
        console_out_fname = os.path.join(
            self.state_dir, "console-%s.log" % bsp)
        commonl.rm_f(console_out_fname)

    def power_off_do(self, _target):
        # Make sure the pidfile is removed, somehow it fails to do so
        for bsp in self.bsps:
            self._power_off_do_bsp(bsp)

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
        for bsp in self.bsps:
            pid = self._power_get_bsp(bsp)
            if pid != None:
                return True
        return False

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
        if console_id != None and not console_id in self.bsps:
            raise RuntimeError("console ID '%s' not found" % console_id)
        if console_id == None:
            console_id = self.bsps[0]
        # Reading is simple -- QEMU is designed to leave a logfile
        # with anything that comes from each console, named
        # BSP-console.read. We just read that, because our console IDs
        # are just the BSP names.
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
        if console_id != None and not console_id in self.bsps:
            raise RuntimeError("console ID '%s' not found" % console_id)
        if console_id == None:
            console_id = self.bsps[0]
        # Reading is simple -- QEMU is designed to leave a logfile
        # with anything that comes from each console, named
        # BSP-console.read. We just read that, because our console IDs
        # are just the BSP names.
        consolefname = os.path.join(self.state_dir,
                                    "%s-console.read" % console_id)
        return os.stat(consolefname).st_size

    def console_do_write(self, data, console_id = None):
        if console_id != None and not console_id in self.bsps:
            raise ValueError
        if console_id == None:
            console_id = self.bsps[0]
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


class plugger(ttbl.thing_plugger_mixin):
    """
    Plugger class to plug external devices to QEMU VMs

    :param dict kwargs: parameters for :meth:`qmp_c.command`'s
      `device_add` method, which for example, could be:

      - driver = "usb-host"
      - hostbus = BUSNUMBER
      - hostaddr = USBADDRESS
    """
    def __init__(self, name, **kwargs):
        self.kwargs = kwargs
        self.name = name
        ttbl.thing_plugger_mixin.__init__(self)

    def plug(self, target, thing):
        assert isinstance(target, tt_qemu)

        # FIXME: only one BSP supported -- we are going to deprecate
        # them anyway
        bsp = target.bsps[0]
        # Now with QMP, we add the device
        with qmp_c(target.pidfile[bsp] + ".qmp") as qmp:
            r = qmp.command("device_add", id = self.name, **self.kwargs)
            # prelaunch is what we get when we are waiting for GDB
            if r == {}:
                return
            raise RuntimeError("%s: cannot plug '%s': %s"
                               % (self.name, thing.id, r))

    def unplug(self, target, thing):
        assert isinstance(target, tt_qemu)

        # FIXME: only one BSP supported -- we are going to deprecate
        # them anyway
        bsp = target.bsps[0]
        # Now with QMP, we add the device
        with qmp_c(target.pidfile[bsp] + ".qmp") as qmp:
            r = qmp.command("device_del", **self.kwargs)
            # prelaunch is what we get when we are waiting for GDB
            if r == {}:
                return
            raise RuntimeError("%s: cannot plug '%s': %s"
                               % (self.name, thing.id, r))
