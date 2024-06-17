#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Drivers for Dell hardware
-------------------------

"""
import commonl

import ttbl.console

class idrac_console_solssh_c(ttbl.console.ssh_pc):
    """
    Serial console driver over Dells iDRAC SSH.


    :param str hostname: *USER[:PASSWORD]@HOSTNAME* for iDRAC;

      For values the PASSWORD field can have (to eg: store the
      password in a file or in a keyring) see
      :func:commonl.password_get.

    If the serial console is set to no flow control, it is advisable
    to chunk the input to avoid dropping characters, adding

    >>> chunk_size = 5, interchunk_wait = 0.2

    see :class:ttbl.console.generic_c for an explanation about chunking.

    Other parameters as to :class:ttbl.console.ssh_pc and
    :class:ttbl.console.generic_c.

    **iDRAC setup**

    User needs to be SSH enabled

    1. Navigate to http://idracname

    2. login

    3. Select *iDRAC Settings* > *Users* > *Local Users*

    4. Select the right user, click *Edit*

    5. Ensure *Login to iDRAC* and *Access Virtual Console* are selected

    6. Click *Save*

    """
    def __init__(self, hostname, **kwargs):
        ttbl.console.ssh_pc.__init__(
            self,
            hostname,
            command_sequence = [
                # just wait for a prompt
                ( "",
                  "racadm>>" ),
                # issue a binary connection command, wait for the
                # prompt and we are in
                ( "connect -b com2\r\n",
                  "WARNING: binary mode!" ),
            ],
            **kwargs)
        # it is reliable on reporting state
        self.get_samples = 1
        # power interface
        self.timeout = 40
        self.wait = 1
        # if the connection dies (network blip, who knows), restart it
        self.re_enable_if_dead = True
        self.chunk_size = 5
        self.interchunk_wait = 0.2
        _, _, hostname = commonl.split_user_pwd_hostname(hostname)
        self.upid_set(f"Dell iDRAC @{hostname}",
                      hostname = hostname)
        self.name = "idrac"
