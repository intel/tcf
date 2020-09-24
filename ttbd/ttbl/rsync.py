#! /usr/bin/python2
"""
Power control module to start a rsync daemon when a network is powered-on
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""
import os
import subprocess

import prctl

import commonl
import ttbl
import ttbl.config
import ttbl.power

# FIXME: use daemon_pc
class pci(ttbl.power.impl_c):

    class error_e(Exception):
        pass

    class start_e(error_e):
        pass

    path = "/usr/bin/rsync"

    """
    This class implements a power control unit that starts an rsync
    daemon to serve one path to a network.

    Thus, when the associated target is powered on, the rsync daemon
    is started; when off, rsync is killed.

    E.g.: an interconnect gets an rsync server to share some files
    that targets might use:

    >>> ttbl.interface_add("power", ttbl.power.inteface(
    >>>     ttbl.rsync.pci("192.168.43.1", 'images',
    >>>                    '/home/ttbd/images'),
    >>>     vlan_pci()
    >>> )
    >>> ...


    Other parameters as to :class:ttbl.power.impl_c.
    """

    def __init__(self, address,
                 share_name, share_path,
                 port = 873,
                 uid = None, gid = None, read_only = True, **kwargs):
        ttbl.power.impl_c.__init__(self, **kwargs)
        self.address = address
        self.port = port
        self.share_name = share_name
        self.share_path = share_path
        self.read_only = str(read_only)
        self.uid = uid
        self.gid = gid

    def on(self, target, _component):
        """
        Start the daemon, generating first the config file
        """
        file_prefix = os.path.join(
            target.state_dir, "rsync-%s:%d" % (self.address, self.port))
        pidfile = file_prefix + ".pid"
        with open(file_prefix + ".conf", "w+") as conff:
            conff.write("""\
# We run the daemon as root and need to run as root so we can access
# folders that have root-only weird permissions
# FIXME: we could also CAP_DAC_READ_SEARCH or similar
[images]
path = {0.share_path}
read only = {0.read_only}
timeout = 300
""".format(self))
            if self.uid:
                conff.write("uid = %s" % self.uid)
            if self.gid:
                conff.write("gid = %s" % self.gid)

        def _preexec_fn():
            # We need this to access image files to serve that are
            # owned by root (because that's what the image is and we
            # want to share them with the same bits--even if we mapped
            # user to something else, some attributes and different
            # user bits would force us to do something like this)
            prctl.cap_effective.dac_read_search = True
            # rsync chroots for safety
            prctl.cap_effective.sys_chroot = True
            return

        cmdline = [
            "rsync",
            "--daemon",
            "--no-detach",
            "--address", self.address,
            "--port", str(self.port),
            "--config", file_prefix + ".conf"
        ]
        try:
            p = subprocess.Popen(
                cmdline, shell = False,
                cwd = target.state_dir, close_fds = True,
                stderr = subprocess.STDOUT, preexec_fn = _preexec_fn)
            with open(pidfile, "w+") as pidf:
                pidf.write("%s" % p.pid)
        except OSError as e:
            raise self.start_e("rsync failed to start: %s" % e)
        pid = commonl.process_started(
            pidfile, self.path,
            verification_f = commonl.tcp_port_busy,
            verification_f_args = (self.port,),
            tag = "rsync", log = target.log)
        # systemd might complain with
        #
        # Supervising process PID which is not our child. We'll most
        # likely not notice when it exits.
        #
        # Can be ignored
        if pid == None:
            raise self.start_e("rsync failed to start")
        ttbl.daemon_pid_add(pid)	# FIXME: race condition if it died?

    def off(self, target, _component):
        pidfile = os.path.join(
            target.state_dir, "rsync-%s:%d.pid" % (self.address, self.port))
        commonl.process_terminate(pidfile, path = self.path, tag = "rsync")

    def get(self, target, _component):
        pidfile = os.path.join(
            target.state_dir, "rsync-%s:%d.pid" % (self.address, self.port))
        pid = commonl.process_alive(pidfile, self.path)
        if pid != None:
            return True
        return False
