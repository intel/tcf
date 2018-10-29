#! /usr/bin/python
import os
import subprocess

import commonl
import ttbl

class pci(ttbl.tt_power_control_impl):

    class error_e(Exception):
        pass

    class start_e(error_e):
        pass

    path = '/usr/bin/adb'

    """
    Power Control implementation that starts ADB

    ADB is started / stopped as the target is powered up down and made
    to listen on a port. The port is reported on a target property
    called *adb.port*.

    :param str serial_number: target's USB serial number
    :param str adb_path: (optional) path to the ADB binary
    """

    def __init__(self, server_port,
                 target_serial_number = None,
                 target_host = 'localhost', target_port = None,
                 path = None, debug = False):
        # Because there can be only one ADB daemon in here, we
        # won't give it a name including the serial name; this way
        # also the tag it generates on remote access is always
        # called adb.port
        ttbl.tt_power_control_impl.__init__(self)
        self.server_port = server_port
        self.target_port = None
        self.target_serial_number = None
        self.target_host = None
        if target_serial_number:
            self.target_serial_number = target_serial_number
            self._id = "%s-%d" % (target_serial_number, server_port)
        elif target_port:
            self.target_port = target_port
            self.target_host = target_host
            self._id = "%s:%d-%d" % (self.target_host, target_port,
                                     server_port)
        else:
            raise AssertionError(
                "either a serial number or a [HOST:]TCP have "
                "to be given to connect to")
        self.debug = debug
        if path:
            self.path = path


    def power_on_do(self, target):
        pidfile = os.path.join(target.state_dir, "adb-" + self._id + ".pid")
        cmdline = [ self.path ]
        if self.target_serial_number:
            # If the thing is connected via USB
            cmdline += [ "-s", self.target_serial_number ]
        cmdline += [
            # we are going to listen on this port on all interfaces
            "-a",
            "-P", str(self.server_port),
            "nodaemon",
            "server"
        ]
        try:
            target.log.error('DEBUG  %s' % cmdline)
            env = dict(os.environ)
            if self.debug:
                env['ADB_TRACE'] = "all"
            p = subprocess.Popen(cmdline, shell = False,
                                 cwd = target.state_dir, env = env,
                                 close_fds = True, stderr = subprocess.STDOUT)
            with open(pidfile, "w+") as pidf:
                pidf.write("%s" % p.pid)
        except OSError as e:
            raise self.start_e("adb failed to start: %s", e)
        pid = commonl.process_started(
            pidfile, self.path,
            verification_f = commonl.tcp_port_busy,
            verification_f_args = (self.server_port,),
            tag = "adb", log = target.log)
        # systemd might complain with
        #
        # Supervising process PID which is not our child. We'll most
        # likely not notice when it exits.
        #
        # Can be ignored
        if pid == None:
            raise self.start_e("adb failed to start")
        ttbl.daemon_pid_add(pid)	# FIXME: race condition if it died?

        # Connected via TCP/IP? tell the daemon to connect
        if self.target_port:
            subprocess.check_output([
                self.path,
                "-H", "localhost", "-P",  str(self.server_port),
                "connect", "%s:%d" % (self.target_port, self.target_port)
            ])
        target.property_set("adb.port", str(self.server_port))

    def power_off_do(self, target):
        target.property_set("adb.port", None)
        pidfile = os.path.join(target.state_dir, "adb-" + self._id + ".pid")
        try:
            commonl.process_terminate(pidfile, self.path, tag = "adb")
        except OSError as e:
            # adb might have died already
            if e != errno.EPROCESS:
                raise

    def power_get_do(self, target):
        pidfile = os.path.join(target.state_dir, "adb-" + self._id + ".pid")
        pid = commonl.process_alive(pidfile, self.path)
        if pid != None:
            return True
