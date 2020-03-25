#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME: experiment, not sure this is the best way to do this
# FIXME: move as method under *images*
"""
Interface to flash the target using *ioc_flash_server_app* 
----------------------------------------------------------
"""

import os
import subprocess

import commonl
import ttbl


class interface(ttbl.tt_interface):
    """
    Remote tool interface

    An instance of this gets added as an object to the main target
    with:


    >>> ttbl.test_target.get('TARGETNAME').interface_add(
    >>>     "ioc_flash_server_app",
    >>>     ttbl.ioc_flash_server_app.interface("/dev/tty-TARGETNAME-FW")
    >>> )

    Where ``/dev/tty-TARGETNAME-FW`` is the serial line for the IOC
    firmware interface for *TARGETNAME*.

    Note this requires the Intel Platform Flash Tool installed in your
    system; this driver will expect the binary available in a location
    described by :data:`path`.

    :param str tty_path: path to the target's IOC firmware serial port
    """
    def __init__(self, tty_path):
        ttbl.tt_interface.__init__(self)
        self.tty_path = tty_path

    def _target_setup(self, target):
        self.instrumentation_publish_component(
            target, "ioc_flash_server_app",
            commonl.mkid(self.tty_path, l = 4), "RS-232C serial port",
            { 'serial_port': self.tty_path })

    def _release_hook(self, target, _force):
        # nothing needed here
        pass

    #: path to the binary
    #:
    #: can be changed globally:
    #:
    #: >>> ttbl.ioc_flash_server_app.interface.path = "/some/other/ioc_flash_server_app"
    #:
    #: or for an specific instance
    #:
    #: >>> ttbl.test_target.get('TARGETNAME').ioc_flash_server_app._path = "/some/other/ioc_flash_server_app"
    #:
    path = "/opt/intel/platformflashtool/bin/ioc_flash_server_app"

    #: allowed operation modes
    #:
    #: these translate directly to the command line option ``-MODE``
    #:
    #: - *fabA*
    #: - *fabB*
    #: - *fabC*
    #: - *grfabab*
    #: - *grfabc*
    #: - *grfabd*
    #: - *grfabe*
    #: - *hadfaba*
    #: - *kslfaba*
    #: - *generic* (requires the *generic_id* parameter too)
    #: - *w*
    #: - *t*
    allowed_modes = (
        'fabA', 'fabB', 'fabC',
        'grfabab', 'grfabc', 'grfabd', 'grfabe',
        'hadfaba', 'kslfaba',
        'generic', 'w', 't'
    )

    def put_run(self, target, who, args, _files, user_path):
        baudrate = args.get('baudrate', None)
        mode = args.get('mode', None)
        assert mode in self.allowed_modes, \
            "invalid mode '%s' (allowed: %s)" \
            % (mode, " ".join(self.allowed_modes))
        filename = args.get('filename', None)
        if filename:
            _filename = os.path.join(user_path, filename)
        else:
            _filename = None
        generic_id = args.get('generic_id', None)
        if mode == 'generic':
            assert generic_id, "mode `generic` requires an `id`"
        else:
            assert not generic_id, "only mode `generic` requires an `id`"

        cmdline = [
            self.path,
            "-b", baudrate,
            "--debug",	# always be quite verbose
            "-s", self.tty_path,
            "-" + mode
        ]
        if mode == 'generic':
            cmdline += [ generic_id, _filename ]
        else:
            cmdline.append(_filename)
        with target.target_owned_and_locked(who):
            try:
                target.log.info("running: %s" % " ".join(cmdline))
                # have the monitor release the serial port so the tool can
                # open it
                with target.console_takeover():
                    output = subprocess.check_output(
                        cmdline, stderr = subprocess.STDOUT,
                        shell = False, cwd = target.state_dir)
                target.log.warning("ran: %s" % " ".join(cmdline))
                for line in output.split('\n'):
                    target.log.debug("output: " + line)
                return {}
            except subprocess.CalledProcessError as e:
                msg = "error %d: %s" % (e.returncode, " ".join(cmdline))
                target.log.error(msg)
                for line in e.output.split('\n'):
                    target.log.warning("error output: " + line)
                    msg += "\n" + "error output: " + line
                raise RuntimeError(msg)

