#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import subprocess

from tcfl import commonl
import ttbl.pc
import ttbl.tt

class reap_pci_t0(ttbl.tt_power_control_impl):
    # So this will start a daemon and then properly reap it, so it
    # doesn't zombie if our child signal handling in ttbd is working
    # ok (where we only reap daemons that we have registered).

    def power_on_do(self, target):
        p = subprocess.Popen([ "/usr/bin/sleep", "10000d" ])
        ttbl.daemon_pid_add(p.pid)
	# ttbl.daemon_pid_rm() happens in the process that gets the SIGCHLD
        target.fsdb.set('daemon_pid', "%d" % p.pid)

    def power_off_do(self, target):
        _pid = target.fsdb.get('daemon_pid')
        if _pid:
            pid = int(_pid)
            commonl.process_terminate(pid)
	    # ttbl.daemon_pid_rm() happens in the process that gets the SIGCHLD
            target.fsdb.set('daemon_pid', None)

    def power_get_do(self, target):
        pid = target.fsdb.get('daemon_pid')
        if pid == None:
            return False
        else:
            return True

ttbl.config.target_add(
    ttbl.tt.tt_power("t0", reap_pci_t0(), False),
    tags = {
        'skip_cleanup' : True,
    }
)

class reap_pci_t1(ttbl.tt_power_control_impl):

    def power_on_do(self, target):
        # Set before, so we can call power_Off to verify it works ok
        # even if this fails
        target.fsdb.set('power_state', 'True')
        # So this will fail if our child signal handling in ttbd is
        # working ok (where we only reap daemons that we have
        # registered).
        subprocess.check_output("false", shell = True)

    def power_off_do(self, target):
        target.fsdb.set('power_state', None)
        subprocess.check_output("true", shell = True)

    def power_get_do(self, target):
        if target.fsdb.get('power_state'):
            return True
        else:
            return False

ttbl.config.target_add(
    ttbl.tt.tt_power("t1", reap_pci_t1(), False),
    tags = {
        'skip_cleanup' : True,
    }
)
