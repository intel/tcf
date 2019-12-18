#! /usr/bin/python
"""
Power control module to start an ADB daemon
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""
import subprocess

import commonl
import ttbl.power

class pc(ttbl.power.daemon_c):
    """
    Power Control implementation that starts an ADB daemon

    ADB is started / stopped as the target is powered up down and made
    to listen on a port. The port is reported on a target property
    called *adb.port*.

    :param int server_port: TCP port number where to listen
    :param str usb_serial_number: target's USB serial number
    :param str adb_path: (optional) path to the ADB binary
    """

    def __init__(self, server_port,
                 usb_serial_number = None,
                 target_host = 'localhost', target_port = None,
                 path = "/usr/bin/adb", debug = False):
        # Because there can be only one ADB daemon in here, we
        # won't give it a name including the serial name; this way
        # also the tag it generates on remote access is always
        # called adb.port
        self.server_port = server_port
        self.target_port = None
        self.usb_serial_number = None
        self.target_host = None
        if usb_serial_number:
            self.usb_serial_number = usb_serial_number
            name = "%s-%d" % (usb_serial_number, server_port)
        elif target_port:
            self.target_port = target_port
            self.target_host = target_host
            name = "%s:%d-%d" % (self.target_host, target_port, server_port)
        else:
            raise AssertionError(
                "either a serial number or a [HOST:]TCP have "
                "to be given to connect to")
        cmdline = [ path ]
        if usb_serial_number:
            # If the thing is connected via USB
            cmdline += [ "-s", usb_serial_number ]
        cmdline += [
            # we are going to listen on this port on all interfaces
            "-a",
            "-P", str(self.server_port),
            "nodaemon",
            "server"
        ]
        env_add = {}
        if debug:
            env_add['ADB_TRACE'] = "all"
        ttbl.power.daemon_c.__init__(self, cmdline, precheck_wait = 0.5,
                                     env_add = env_add, name = name)

    def verify(self, target, component, _cmdline_expanded):
        return commonl.tcp_port_busy(self.server_port)

    def on(self, target, _component):
        ttbl.power.daemon_c.on(self, target, _component)
        # Connected via TCP/IP? tell the daemon to connect
        if self.target_port:
            subprocess.check_output([
                self.path,
                "-H", "localhost", "-P",  str(self.server_port),
                "connect", "%s:%d" % (self.target_port, self.target_port)
            ])
        target.property_set("adb.port", str(self.server_port))

    def off(self, target, _component):
        target.property_set("adb.port", None)
        ttbl.power.daemon_c.off(self, target, _component)
