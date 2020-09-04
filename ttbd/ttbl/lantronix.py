#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Drivers for Lantronix hardware
------------------------------

"""
import re

import commonl
import ttbl.capture
import ttbl.console

class console_spider_duo_pc(ttbl.console.ssh_pc):

    """
    Serial console driver over a Lantronix Spider Duo KVM.

    https://www.lantronix.com/products/lantronix-spiderduo/

    These KVMs can get a UART connected to them and they expose the
    data over an SSH connection

    :param str kvm_hostname: *USER[:PASSWORD]@HOSTNAME* for the KVM;
      note the KVM needs to be accessible over the network from the
      server.

      For values the PASSWORD field can have (to eg: store the
      password in a file or in a keyring) see
      :func:commonl.password_get.


    If the serial console is set to no flow control, it is advisable
    to chunk the input to avoid dropping characters, adding

    >>> chunk_size = 5, interchunk_wait = 0.2

    see :class:ttbl.console.generic_c for an explanation about chunking.

    Other parameters as to :class:ttbl.console.ssh_pc and
    :class:ttbl.console.generic_c.

    **System setup**

    1. connect a serial port to the Lantronix Spider KVM
    2. login to the KVM with an account that has admin permission
       (https://kvm_hostname.somewhere)
    3. Navigate to *Interfaces / Network* in section *Network
       Miscellaneous Settings* (bottom right) and:
       - make sure SSH port is set (to 22 default)
       - ensure SSH access is enabled
       - Click *Save*
    4. Navigate to *Interfaces / Serial Port*
       - ensure Passthrough Access to Serial Port 1 via Telnet/SSH is selected
       - ensure baud rate is set to 115200, data bits to 8, Parity to
         None, Stop bits to 1 (these are standard settings), or
         whatever your target requires.
       - ensure Flow control is set to RTS/CTS (most targets) or none;
         if none, please look above re chunking.
       - Click *Save*

    5. create an account with SSH access in user *Accounts /
       Permissions* to give in the KVM hostname parameter as
       USER:PASSWORD@KVMHOSTNAME.

    **Manual SSH connection**

    The KVM supports an old version of the SSH protocol, so it needs a
    few special settings::

      $ ssh -o "KexAlgorithms diffie-hellman-group1-sha1" -o "Ciphers aes128-cbc,3des-cbc" ACCOUNTNAME@KVMHOSTNAME
      Welcome to the Lantronix SLSLP
      Firmware: version 030025, build 38118
      Last login: Sat Jan 17 23:36:07 1970 from 10.213.171.71
      Current time: Sat Jan 17 23:50:17 1970
      For a list of commands, type 'help'
      [sysadmin@10.219.137.150]>

    Now issue connect serial to get connected::

      To exit serial port connection, type 'ESC exit'.

    Type the escape key followed by word *exit* to disconnect, then
    logout to leave the connection.

    **Troubleshooting**

    - Serial console doesn't take input, but output can be seen

      This might be due to the flow control configuration in the KVM's
      serial port (see above in configuration).

      Symptoms:

        interactive console (tcf console-write -i TARGETNAME) shows
        serial output, but any input seems to be ignored; automation
        fails to control the boot process or any other process.

      Solution:

        flip the configuration from RTS/CTS to None or viceversa
    """
    def __init__(self, kvm_hostname, **kwargs):
        ttbl.console.ssh_pc.__init__(
            self,
            kvm_hostname,
            command_sequence = [
                ## Welcome to the Lantronix SLSLP^M$
                ## Firmware: version 030031, build 38120^M$
                ## Last login: Thu Jan  1 00:04:20 1970 from 10.24.11.35^M$
                ## Current time: Thu Jan  1 00:02:03 1970^M$
                ## For a list of commands, type 'help'^M$

                # command prompt, 'CR[USERNAME@IP]> '... or not, so just
                # look for 'SOMETHING> '
                # ^ will not match because we are getting a CR
                ( "",
                  re.compile("For a list of commands") ),
                ( "\x1bexit",	# send a disconnect just in case
                  # wait for nothing, the prompt expect will be done by
                  # the next one -- somehow this works better, otherwise
                  # sometimes it doesn't see the prompt if there actually
                  # was no need for the exit command
                  "" ),
                ( "\r\n",	# just get us a prompt
                  re.compile("[^>]+> ") ),
                ( "connect serial\r\n",
                  "To exit serial port connection, type 'ESC exit'." ),
            ],
            extra_opts = {
                # Lantronix dropbear 0.45 server (or its configuration)
                # needs this setting for it to work. old, but nothing we
                # can do.
                "KexAlgorithms": "diffie-hellman-group1-sha1",
                "Ciphers" : "aes128-cbc,3des-cbc",
            },
            chunk_size = 5, interchunk_wait = 0.2,
            crlf = "\r",
            **kwargs)
        # it is reliable on reporting state
        self.get_samples = 1
        # power interface
        self.timeout = 40
        self.wait = 1
        # if the connection dies (network blip, who knows), restart it
        self.re_enable_if_dead = True
        # This is running over a Lantronix KVM, which needs to be escaped
        # when we send an escape character -- it uses ESCexit as a
        # sequence to leave the console mode and we don't want this to
        # happen if we type ESCexit...so we escape ESC :P
        self.escape_chars['\x1b'] = '\x1b'
        # depending on how this serial console sometimes drops stuff, so we feed it
        # carefully (not sure which piece of the HW has the issue)
        self.chunk_size = 5
        self.interchunk_wait = 0.2
        _, _, hostname = commonl.split_user_pwd_hostname(kvm_hostname)
        self.upid_set("Spider KVM %s" % hostname, hostname = hostname)


class screenshot_spider_c(ttbl.capture.generic_snapshot):
    """
    Driver to capture screenshots from a Lantronix Spider Duo KVM

    https://www.lantronix.com/products/lantronix-spiderduo/

    When properly configured, these KVMs allow to download a low
    resolution screenshot of the screen.

    :param str kvm_hostname: hostname for the KVM; no user/password is
    needed, and if provided, it will be ignored.

    Other parameters as per :class:ttbl.capture.generic_snapshot

    **KVM setup**

    - Connect the KVM to power, the SUT's VGA/HDMI output, etc,
      configure the network.

    - login to the KVM with an account that has admin permission
      (https://KVMHOSTNAME)

    - navigate to *Services/ Security*: in section *Authentication
      Limitation* (top right):

      - ensure *Enable Screenshot Access without Authentication* is
        enabled

      - click Save

    Verify operation manually; from a Linux console::

      $ wget http://KVMHOSTNAME/screenshot.jpeg

    shall yield a file called screenshot.jpg with the current screen
    displayed by the target (do not use from a browser, as it will
    have the authentication credentials from logging in to the KVM so
    you won't be sure if it is actually working or not).

    **Server Configuration**

    To any target, when defining the capture interface:

    >>> import ttbl.capture
    >>> import ttbl.lantronix
    >>>
    >>> target.interface_add(
    >>>     "capture",
    >>>     ttbl.capture.interface(
    >>>         screen = "kvm_screenshot",
    >>>         kvm_screenshot = ttbl.lantronix.screenshot_spider_c(hostname)
    >>> ))

    or extending it

    >>> target.capture.impl_add(
    >>>     "kvm_screenshot",
    >>>     ttbl.lantronix.screenshot_spider_c(hostname)
    >>> )

    Once the configuration is reloaded, the capture devices show up::

      $ tcf capture-ls r51s04
      screen:snapshot:image/jpeg:ready
      kvm_screenshot:snapshot:image/jpeg:ready

    **Pending**

    Enable capturing high definition data via websocket / HTML5
    """

    def __init__(self, kvm_hostname, **kwargs):
        _, _, hostname = commonl.split_user_pwd_hostname(kvm_hostname)
        ttbl.capture.generic_snapshot.__init__(
            self,
            # dont set the port for the name, otherwise the UPID keeps
            # changing when the instrument is actually the same
            "Spider KVM %s" % hostname,
            # NOTE: there is no way to enable screenshots with
            # username/password -- they just don't work -- need to dig
            # more into the auth mechanism
            "timeout 40"
            " curl -s -k https://%s/screenshot.jpg --output %%(output_file_name)s"
            % hostname,
            mimetype = "image/jpeg",
            extension = ".jpg",
            **kwargs
        )
        self.upid_set("Spider KVM %s" % hostname, hostname = hostname)
