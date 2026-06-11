#! /usr/bin/python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Module for router management
----------------------------

The classes in this module help manage and configure routers in an
SDN style.

For example, :class:`ttbl.router.vlan_manager_c` is a power
controller that when powered on configures a virtual LAN in a switch,
limiting which ports can be access to those machines in active
reservation. When powered off, it destroys the VLAN.

This allows implementing networks that are only up when they are
supposed to be up, removing any existing state.

"""
import json
import logging
import os
import pexpect
import re
import requests
import threading
import time
import traceback

import commonl
import ttbl.power

class router_c:
    """
    A base class to help managing routers

    Currently it is limited to create/destroy VLANs and get if they
    are created.
    """
    def __init__(self, hostname, username = None, password = None,
                 logger = None):
        self.hostname = None
        self.username = None
        self.password = None
        if hostname:
            self.username, self.password, self.hostname = \
                commonl.split_user_pwd_hostname(hostname, expand_password = False)
        # override username and password from args, if present
        if username:
            self.username = username
        if password:
            self.password = password
        if logger == None:
            self.logger = logging.getLogger(f"switch-{self.hostname}")
        else:
            self.logger = logger


    def server_link_setup(self, target: ttbl.test_target, component: str):
        """
        Setup the server's connection to the switch

        This is used to configure anything in the switch needed
        for the ttbd server to access any VLAN created in the
        switch.

        It might be run multiple times, so it has to be idempotent
        and do no effect
        """
        pass


    def vlan_create(self, vlan_id, vlan_name, switch_ports):
        """
        Create VLAN

        :param int vlan_id: VLAN's number
        :param str vlan_name: VLAN's name
        :param (set|list,tuple) switch_ports: list of port
          specifications (this can be an integer or string which
          matches the switch's language specification)

          >>> { 'Eth1/41', 'Eth1/40' }
        """
        raise NotImplementedError


    def vlan_destroy(self, vlan_id, vlan_name):
        """
        Destroy a VLAN

        :param int vlan_id: VLAN's number
        """
        raise NotImplementedError


    def vlan_get(self, vlan_id):
        """
        Report if a VLAN exists

        :param int vlan_id: VLAN's number
        :returns: *None* if the VLAN does exist, a dict of information
          about the VLAN:

          >>> {
          >>>     'name': 'NAME',
          >>>     'raw': RAWDATASWITCHSPECIFIC
          >>> }
        """
        # return True/False
        raise NotImplementedError



class cisco_c(router_c):
    """
    Class for managing Cisco Nexus 9k switches


    **Methodology**

    The switch might be spoken to with using a:

    - SSH sessions, in a CLI send/expect sequence

    - HTTP API
      (https://developer.cisco.com/docs/nx-os-n3k-n9k-api-ref-7-x/#!cisco-nexus-3000-and-9000-series-nx-api-rest-sdk-user-guide-and-api-reference-release-7-x/faults)
      using CLI commands.


    This uses the HTTP API, since it is kinda easier to parse later on
    and we get responses in JSON, such as::

      r = requests.post(
          'https://10.45.134.158/ins',
          json = [
              {
                  "jsonrpc": "2.0",
                  "method": "cli",
                  "params": {
                      "cmd": "show version",
                  },
                  "id": 1
              },
              {
                  "jsonrpc": "2.0",
                  "method": "cli",
                  "params": {
                      "cmd": "conf",
                  },
                  "id": 2
              },
              {
                  "jsonrpc": "2.0",
                  "method": "cli",
                  "params": {
                      "cmd": "vlan 4",
                      "version": 1,
                  },
                  "id": 3
              },
          ],
          headers = {'content-type':'application/json-rpc'},
          auth = ( USERNAME, PASSWORD ),
          verify = False
      )

    In a way, this simplifies handling it, which replies::

      [
          {
              "jsonrpc": "2.0",
              "result": null,
              "id": 0
          },
          {
              "jsonrpc": "2.0",
              "result": null,
              "id": 1
          },
          ...
      ]

    As well, since the commands we send over this HTTP API are the
    same as in the CLI, it is easy for a human to reproduce/debug
    when needed.


    Misc commands for the switch's console
    --------------------------------------

    - Disable paging in the terminal with::

        terminal length 0

    - Display interface status with::

        show interface status
        show interface status | i connected
        show interface status | ex notconnected

    - Show the MAC addresses seen on an interface::

        sh mac address-table
        sh mac address-table interface X/Y

      (note it will not work if there is no traffic)

      Can *grep* using, eg::

        show interface status | inc connected

        show interface status | ex notconnected

    - Show the current time configuration::

        sh clock

    - Show logs::

        sh logging log | last 100


    Configuration for the TTBD server
    ---------------------------------

    If we need the TTBD server to connect to the private networks
    (NUTs) created by the switches (in general, yes), the server
    needs to be connected to a switch and it needs to be set to
    allow all traffic (tagged/trunk access)--see
    :meth:`server_link_setup` for details.

    this is accomplished with a power adaptor
    :class:`ttbl.router.router_manager_c` that will do this on
    switch power on -- thus needs to be added to the power rail of
    the target that adds it, eg::

      target = target_infra_server_add(
          name, ipv4_addr = ssh_ipaddr,
          consoles_extra = { "ssh0": ssh0 },
          power_rail_extra = {
              "ssh0": ssh0,
              # object that can be used to configure the router
              "setup": router_manager_c(ttbl.router.cisco_c),
          },
          bsps_do_setup = False,
          bios_do_setup = False,
          pos_do_setup = False,
          **kwargs)

    The code will look for the switch port in the tag in the
    object describing the switch *server.switch_port*


    Configuration for the SUT ports
    -------------------------------

    Each SUT is connected to a port and the port is enabled to only
    allow communication in the VLAN the SUT is made part of; this
    is done in :meth:`vlan_create`; that operation is triggered
    when creating a VLAn with :class:`vlan_manager`, which first
    pulls the ports and then calls :meth:`vlan_create`.


    Configuration for the switch
    ----------------------------

    We need to enable the HTTP API interface (NXAPI) for some
    functionality; :meth:`server_link_setup` will do this as part of
    the switch setup, which basically is::

      conf t
      ...
      feature nxapi
      exit

    **References**

    - https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/layer2/configuration/guide/b_Cisco_Nexus_9000_Series_NX-OS_Layer_2_Switching_Configuration_Guide/b_Cisco_Nexus_9000_Series_NX-OS_Layer_2_Switching_Configuration_Guide_chapter_011.html

    """
    def __init__(self, hostname, username = None, password = None, logger = None):
        router_c.__init__(self, hostname, username, password, logger)


    def _is_it_an_error(self, command_list, result):
        # {
        #     "jsonrpc": "2.0",
        #     "result": null,
        #     "error": {                # or
        #        "code": -32602,
        #        "message": "Invalid params",
        #        "data": {
        #            "msg": "% Invalid command\n"
        #        },
        #     },
        #     "id": 1
        # },
        if not isinstance(result, dict):		# not something we know
            return "can't handle result {type(result)}"
        if result.get("jsonrpc", None) != "2.0":
            return "missing 'jsonrpc' field"
        command_id = result.get("id", None)
        if command_id == None:
            return "missing 'id' field"
        try:
            command = command_list[command_id]
        except IndexError as e:
            command = "<invalid index {command_id}>"
        error = result.get("error", None)
        if error != None:
            # assume is a dict
            return f"error in command '{command}': {error}"
        # No Issues
        return None



    def _sequence_run(self, *args, **kwargs):
        dl = []
        count = 0
        command_list = []
        for what in args:
            _what = what % kwargs
            dl.append({
                "jsonrpc": "2.0",
                "method": "cli",
                "params": {
                    "cmd": _what,
                    "version": 1,
                },
                "id": count
            })
            command_list.append(_what)
            self.logger.info("command #%d: %s", count, _what)
            count += 1
        try:
            password = commonl.password_get(self.hostname, self.username, self.password)
            r = requests.post(
                f'https://{self.hostname}/ins', json = dl,
                headers = {'content-type':'application/json-rpc'},
                auth = ( self.username, password ),
                verify = False
            )
            self.logger.info(f"execution r {r}")
            if r.status_code == 200:
                return r.json()
            try:
                j = r.json()
            except json.decoder.JSONDecodeError as e:
                self.logger.debug(f"execution: can't decode JSON response: %s", e)
                j = { "rawtext": r.text}
            msg = f"execution: error status {r.status_code}: " \
                f"{json.dumps(j, indent = True)}"
            if isinstance(j, list):
                for result in j:
                    e = self._is_it_an_error(command_list, result)
                    if not e:
                        continue
                    self.logger.error("error running %s: %s", dl, e)
                    raise RuntimeError(e, j)
            self.logger.error(msg)
            raise RuntimeError(msg, j)
        except requests.exceptions.RequestException as e:
            # FFS, we might get a requests.exceptions.ConnectionError
            # which in theory subclasses a lot of good stuff but it
            # turns out in other environments it just wraps and wraps
            # and wraps a string that says "connection refused" ($!#@$#)
            if e.errno == errno.ECONNREFUSED \
               or "connection refused" in str(e).lower():
                # this might mean the router is not properly
                # configured to accept the HTTP[S] interface
                self.logger.error(
                    "can't connect to router's HTTP API, is it enabled?"
                    " check ttbl.router.cisco_c doc: %s", e)
            else:
                self.logger.error("execution HTTP error %s: ", e)
            raise

    def _copy_running_config_retrying(self):
        #
        # Tells the switch to copy running config to startup (so
        # if we restart, the state is the same)
        #
        # Note sometimes this fails because another op like this
        # is in progress; sleep, retry.
        #
        # Assumes switch console is in conf mode

        top = 4
        count = 0
        while True:
            count += 1
            try:
                self._sequence_run(
                    # make this permanent
                    # FIXME: retry if it fails?
                    "copy running-config startup-config",
                )
                return
            except RuntimeError as e:
                if len(e.args) <= 1:
                    self.logger.error(f"re-raising: less than 2 args")
                    raise
                if not isinstance(e.args[1], dict):
                    self.logger.error(f"re-raising: args[1] not a dict")
                    raise
                info = e.args[1]   # from error processor above
                # if it fails like
                #
                ## {
                ##     "jsonrpc": "2.0",
                ##     "error": {
                ##         'code': -32602,
                ##         'message': 'Invalid params',
                ##         'data': {
                ##             'msg': 'Configuration update aborted: another request for config change is already in progress\n'
                ##         }
                ##     }
                ## }
                #
                msg = info.get('error', {}).get('data', {}).get('msg', "n/a")
                if 'another request for config change is already in progress' not in msg:
                    raise
                if count >= top:
                    self.logger.error("copy running-config: retried %d "
                                      "times, giving up", count)
                    raise
                self.logger.info("copy running-config: retrying %d/%d",
                                 count, top)
                time.sleep(0.5)
                continue



    def server_link_setup(self, target, component):
        """
        Setup the server's connection to the switch

        This is used to configure anything in the switch needed
        for the ttbd server to access any VLAN created in the
        switch.

        It might be run multiple times, so it has to be idempotent
        and do no effect

        In Cisco 9k series, we need to set the port to be layer2
        trunk mode (switchport; switchport mode trunk)
        """

        server_switch_port = target.tags.get("server.switch_port", None)
        if not server_switch_port:
            return
        self._sequence_run(
            "conf",
            # this enables the HTTPS interface we use to talk to the
            # server when running _sequence_run()
            "feature nxapi",
            # select the interface/port where the server is
            # connected
            f"int {server_switch_port}",
            # convert from layer 3 -> layer2 switching (vs
            # noswitchport that converts to layer 3)
            "switchport",
            # set the port to mode trunk, so multiple VLANs can be
            # routed over it.
            "switchport mode trunk",
            # ensure trunk ports can access all vlans, since we use
            # them to provide services to all of them
            "switchport trunk allowed vlan all",
            # FIXME: we need to be able to pass extra commands
            "no shut",	# actully enable it
            # done!
            "exit",
        )
        self._copy_running_config_retrying()
        self._sequence_run('exit')


    def vlan_create(self, vlan_id, vlan_name, switch_ports):
        sequence = [
            "conf",
            # wipe first
            f"no vlan {vlan_id}",
            f"vlan {vlan_id}",
            f"name {vlan_name}",
            "exit"
        ]
        if switch_ports:
            # allow acces only to certain ports
            sequence += [
                # select all affected ports--use f'{i}' so we
                # support both int and str transparently
                f"int {','.join(f'{i}' for i in switch_ports)}",
                # For untagged traffic use layer2, access can do a
                # single VLAN
                "switchport",
                "switchport mode access",
                f"switchport access vlan {vlan_id}",
                # For tagged traffic; disabled for now because we
                # can't get both untagged and tagged modes to work
                # and we prefer untagged since it is easier to
                # work with on the OS side
                #f"switchport mode trunk",
                #f"switchport trunk allowed vlan {vlan_id}",
                # enable the ports
                "no shut",
                "exit",
            ]
        self._sequence_run(*sequence)
        self._copy_running_config_retrying()
        self._sequence_run('exit')
        # FIXME: make this a target WARNING! Takes a long time
        # until pinging works after a vlan creation power-cycle


    def vlan_destroy(self, vlan_id, vlan_name):
        if self.vlan_get(vlan_id):
            # since this has to copy the running config, do it only if
            # the vlan is there.
            self._sequence_run(
                "conf",
                # wipe first
                f"no vlan {vlan_id}",
            )
            self._copy_running_config_retrying()
            self._sequence_run('exit')



    def vlan_get(self, vlan_id):
        r = self._sequence_run(
            # wipe first
            f"show vlan id {vlan_id}",
        )
        # If it exists
        # {
        #  "jsonrpc": "2.0",
        #  "result": {
        #   "body": {
        #    "vlanshowrspan-vlantype": "notrspan",
        #    "is-vtp-manageable": "enabled",
        #    "TABLE_mtuinfoid": {
        #     "ROW_mtuinfoid": {
        #      "vlanshowinfo-vlanid": "34",
        #      "vlanshowinfo-media-type": "enet",
        #      "vlanshowinfo-vlanmode": "ce-vlan"
        #     }
        #    },
        #    "TABLE_vlanbriefid": {
        #     "ROW_vlanbriefid": {
        #      "vlanshowbr-vlanid": "34",
        #      "vlanshowbr-vlanid-utf": "34",
        #      "vlanshowbr-vlanname": "nw34",
        #      "vlanshowbr-vlanstate": "active",
        #      "vlanshowbr-shutstate": "noshutdown"
        #     }
        #    }
        #   }
        #  },
        #  "id": 0
        # }
        #
        # If it doesn't
        #
        # {
        #     "jsonrpc": "2.0",
        #     "result": null,
        #     "id": 0
        # }
        result = r.get('result', None)
        if result == None:
            return None
        return {
            'name': result['body']["TABLE_vlanbriefid"]["ROW_vlanbriefid"]["vlanshowbr-vlanname"],
            'raw': result
        }



class cisco_catalyst_c(router_c):

    def __init__(self, hostname: str, username: str = None,
                 password: str = None, logger = None,
                 port: int = 22, timeout = 20):
        """
        Cisco Catalyst IOS-XE configurator

        Uses SSH login to configure the switch and VLANs.

        **Switch setup**

        Needs basic manual config:

        1. connect a serial console at 96008n1 to leftmost console port
           on left (looking from back) RJ45 port; open serial terminal

        2. connect manager network to the RJ45 on its right

        3. reset (if needed):

           c. power cycle switch to reset, press mode button
              should go to "infra:" in the serial console prompt; wipe
              configuration with commands::

                enable   # goes to admin mode
                write erase
                delete flash:vlan.dat
                reload

        4. Enable SSH access; in the serial console:

           a. go admin mode::

                 > enable
                 # config terminal

              prompt chages to *#(config)*

           b. generate an SSH key and enable SSH::

                (config)# crypto key generate rsa modulus 2048
                (config)# ip ssh version 2

           c. restrict access to SSH + local login::

                (config)# line vty 0 15
                (config)#  transport input ssh
                (config)#  login local
                (config)#  exit

           d. create user::

               (config)# username USERNAME privilege 15 secret PASSWORD
               (config)# end

           e. write config::

               # write memory

        5. Test you coan login with a command such as::

             $ /usr/bin/sshpass -p PASSWORD \
                 ssh -v -o "PubkeyAcceptedAlgorithms +ssh-rsa" \
                        -o "HostKeyAlgorithms +ssh-rsa" \
                        -o "KexAlgorithms +diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1" \
                        USERNAME@HOSTNAME

           Note Nexus uses older SSH algorithms, hence why we have to
           enable them.

        **System setup**

        In Fedora 43 and other >2026 Linux OSs we need to enable SHA1::

          $ sudo update-crypto-policies --set LEGACY
        """
        # this sets self.{hostname,username,password} -- note it gets
        # created every time we use the router_manager_c class, so no
        # need to extract stuff from the FSDB, since the manager does
        router_c.__init__(self, hostname, username, password, logger)
        self.timeout = timeout
        self.port = port
        self.p = None
        self.p_lock = threading.Lock()


    # - # superuser
    # - > normal user
    # - \s?: sometimes it ends in space, sometimes doesn't
    prompt_regex = re.compile(rb'^([A-Za-z0-9._()-]+(?:\(config[^\)]*\))?[#>])\s?$', re.MULTILINE)



    class exception(RuntimeError):
        pass

    class command_e(exception):
        pass

    # yes, this is global to the class -- why? because we want, if
    # possible, to keep the connection open until it closes on its own
    # so we don't take for ever to bring it up--this can be a problem
    # if two threads are trying to connect; however, the server is
    # multiprocess, not multithread
    #
    # Ideally this needs to be a changed to a SERVER that would handle
    # connection to this switch with a single connection and everyone
    # would talk to it. SSH mastering could work, but the context of
    # each connection is the killer here, since they are not atomic
    # commands.
    ssh_connections = {}

    def _open_maybe(self):

        # by default, inventory
        # instrumentation.{self.upid_index}.hostname will always be
        # set to USER@HOSTNAME:OUTLET, whatever we configured; we
        # censored whatever password it had. So if splitting yields an
        # empty password but the rest of the fields are the same, we
        # need to redo with self.device_spec
        password = commonl.password_get(self.hostname, self.username, self.password)

        self.p = self.ssh_connections.get(
            ( self.hostname, self.username, password ),
            None)

        if self.p != None:
            try:
                self.logger.info("reuse previous connection: checking if possible")
                self.p.send(b"\x03")	# send a Ctrl-C to clear and get prompt
                try:	# flush as much as we find
                    r = self.p.expect(b".*", timeout = 0.1)
                    self.logger.info(f"reuse previous connection: flushed {r}B")
                except pexpect.exceptions.TIMEOUT:
                    self.logger.info("reuse previous connection: done flushing")
                self.p.send(b"\x03")	# send a Ctrl-C to clear and get prompt
                self.p.expect(self.prompt_regex, timeout = 0.1)
                self.logger.info("reusing previous connection: found prompt")
                return
            except Exception as e:
                self.p = None
                self.logger.info(f"reopening connection because {e}")
                self.ssh_connections[( self.hostname, self.username, password )] = None

        try:
            self.logger.info("opening connection")
            env = dict(os.environ)
            env['SSHPASS'] = self.password
            self.p = pexpect.spawn(
                "sshpass",
                [
                    "-e",	# use SSHPASS env
                    "ssh",
                    # be verbose (for debugging) and allocate a terminal
                    "-vtt",
                    "-p", str(self.port),
                    # We place the control file for the shared
                    # connection in /var/cache/ttbd-production/ssh-NAME-HOSTNAME.control;
                    # this way is shared by all targets that same the
                    # same PDU and username to it.
                    #
                    # IF DISABLED IT WILL OVERWHELM WITH CONNECTIONS
                    "-oControlMaster auto",
                    f"-oControlPath {ttbl.test_target.files_path}/ssh-{self.username}-{self.hostname}.control",
                    # old SSH impl in the switch requires old algorithms
                    "-o", "PubkeyAcceptedAlgorithms +ssh-rsa",
                    #"-oHostKeyAlgorithms +ssh-rsa,ssh-dss",
                    "-o", "HostKeyAlgorithms +ssh-rsa",
                    "-o", "KexAlgorithms +diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1",
                    # we can't do any of this registering, so we
                    # disable it so SSH doesn't ask for it
                    # interactively and makes a mess
                    "-oUserKnownHostsFile /dev/null",
                    "-oCheckHostIP no",
                    "-oStrictHostKeyChecking no",
                    f"{self.username}@{self.hostname}"
                ],
                env = env,
                # this timeout seems to overtake the rest we specify
                # manually, so we set the max, what it takes to get
                # the Welcome message which is longish
                timeout = 30)
            self.p.expect(
                # this comes because we run ssh with -v, helps catch connection done
                b"debug1: Entering interactive session",
                # original prompt message takes longish
                timeout = 30)
            self.logger.info("found welcome message")
            self.p.send(b'\r')
            r = self._expect_prompt(b"")
            self.logger.info(f"found prompt: {r}")
            # disable pagination
            self._cmd("ter len 0")
            self.ssh_connections[( self.hostname, self.username, password )] = self.p
            return

        except Exception as e:

            self.logger.info(f"opening connection to {self.username}@{self.hostname} failed: {e}")
            if self.p:
                self.logger.info(f"log before: {self.p.before}")
                self.logger.info(f"log after: {self.p.after}")
            del self.p	# connection died, so clean it up so it is redone
            #self.ssh_connections[( self.hostname, self.username, password )] = None
            self.p = None
            raise

    # output for errors starts with "% " at the beginning of the line
    error_regex = re.compile(b"^% ", re.MULTILINE)

    def _expect(self, expectation, timeout: int = 5):
        try:
            self.logger.info(f"expecting {expectation}")
            self.p.expect(expectation, timeout = timeout)
            if self.error_regex.search(self.p.before):
                raise self.command_e(
                    f"{self.hostname}: command failed: {self.p.before}"
                )
            return self.p.match.group(0)
        except pexpect.exceptions.EOF as e:
            self.logger.info(f"didn't find (EOF): {expectation}")
            del self.p	# connection died, so clean it up so it is redone
            self.p = None
            raise self.exception(
                f"{self.username}@{self.hostname}: connection died; is it on?") \
                from e
        except pexpect.exceptions.TIMEOUT as e:
            self.logger.info(f"didn't find (TIMEOUT): {expectation}")
            raise self.exception(
                f"{self.username}@{self.hostname}: timeout ({timeout}s)"
                f" receiving '{expectation}'") from e


    def _expect_prompt(self, r):
        count = -1
        while True:
            count += 1
            try:
                # keep reading the prompt until it times out;
                # otherwise sometimes it gets out of sync; prompt
                # regexing is hard
                self.p.expect(self.prompt_regex, timeout = 0.1)
                r += self.p.before
                self.logger.info("prompt received[%d]: %s", count, r)
                self.logger.info("prompt received[%d]: after: %s", count, self.p.after)
            except pexpect.exceptions.TIMEOUT:
                self.logger.info("prompt received[%d]: exiting", count)
                # can't read a prompt no more, prolly we are at it
                break
        if self.error_regex.search(r):
            raise self.command_e(
                f"{self.hostname}: command failed: {r}"
            )
        return r



    def _cmd(self, command, expect = None,):
        r = b""
        self.p.send(command + "\r")
        self.logger.info("%s@%s: sent command: %s",
                         self.username, self.hostname, command)
        if expect:
            r = self._expect(expect)
            self.logger.info("%s@%s: found response %s",
                             self.username, self.hostname, expect)
        else:
            r = self.p.before
        r = self._expect_prompt(r)
        self.logger.info("%s@%s: command output %s", self.username, self.hostname, r)
        return r



    def _sequence_run(self, *args, **kwargs):
        dl = []
        count = -1
        command_list = []
        for what in args:
            count += 1
            _what = commonl.kws_expand(what, kwargs)
            self.logger.info("running command #%d: %s", count, _what)
            self._cmd(_what)
            self.logger.info("ran command #%d: %s", count, _what)



    def _copy_running_config_retrying(self):
        #
        # Tells the switch to copy running config to startup (so
        # if we restart, the state is the same)
        #
        # Note sometimes this fails because another op like this
        # is in progress; sleep, retry.
        #
        # Assumes switch console is in conf mode

        top = 4
        count = 0
        while True:
            count += 1
            try:
                self._cmd(
                    # make this permanent we nee \r\r because Nexus
                    # doesn't have a way to override con
                    "copy run start\r\r",
                    # backslash, so expect doesn't thing it's a regex
                    "\[OK\]")
                return
            except RuntimeError as e:
                if count >= top:
                    self.logger.error("copy running-config: retried %d "
                                      "times, giving up", count)
                    raise
                self.logger.info("copy running-config: retrying %d/%d: %s",
                                 count, top, e)
                time.sleep(0.5)
                continue



    def _copy_running_config_retrying(self):
        #
        # Tells the switch to copy running config to startup (so
        # if we restart, the state is the same)
        #
        # Note sometimes this fails because another op like this
        # is in progress; sleep, retry.
        #
        # Assumes switch console is in conf mode

        top = 4
        count = 0
        while True:
            count += 1
            try:
                self._cmd(
                    # make this permanent we nee \r\r because Nexus
                    # doesn't have a way to override con
                    "copy run start\r\r",
                    # backslash, so expect doesn't thing it's a regex
                    "\[OK\]")
                return
            except RuntimeError as e:
                if count >= top:
                    self.logger.error("copy running-config: retried %d "
                                      "times, giving up", count)
                    raise
                if self.p == None:	# connection died, bump it up
                    raise
                self.logger.info("copy running-config: retrying %d/%d: %s",
                                 count, top, e)
                time.sleep(0.5)
                continue



    def server_link_setup(self, target, component):
        """
        Setup the server's connection to the switch

        This is used to configure anything in the switch needed
        for the ttbd server to access any VLAN created in the
        switch.

        It might be run multiple times, so it has to be idempotent
        and do no effect

        In Cisco 9k series, we need to set the port to be layer2
        trunk mode (switchport; switchport mode trunk)
        """

        server_switch_port = target.tags.get("server.switch_port", None)
        if not server_switch_port:
            return

        @commonl.retry_cb_tries(
            ( pexpect.exceptions.ExceptionPexpect, RuntimeError, self.exception ),
            tries = 4,
            header = "server_link_setup: ", logger = self.logger.info)
        def _server_link_setup():
            self._open_maybe()
            self._sequence_run(
                "config terminal",
                # select the interface/port where the server is
                # connected
                f"int {server_switch_port}",
                "shutdown",	# disable it while we reconfigure
                # convert from layer 3 -> layer2 switching (vs
                # noswitchport that converts to layer 3)
                "switchport",
                # set the port to mode trunk, so multiple VLANs can be
                # routed over it.
                "switchport mode trunk",
                # ensure trunk ports can access all vlans, since we use
                # them to provide services to all of them
                "switchport trunk allowed vlan all",
                # FIXME: we need to be able to pass extra commands
                "no shut",	# enable it
                # done!
                "exit",	# exit int config
                'exit'      # exit config
            )
            self._copy_running_config_retrying()

        with self.p_lock:
            _server_link_setup()



    def vlan_create(self, vlan_id, vlan_name, switch_ports):

        @commonl.retry_cb_tries(
            ( pexpect.exceptions.ExceptionPexpect, RuntimeError, self.exception ),
            tries = 4,
            header = "vlan_create: ", logger = self.logger.info)
        def _vlan_create():
            self._open_maybe()

            sequence = [
                "conf terminal",
                # wipe first
                f"no vlan {vlan_id}",
                f"vlan {vlan_id}",
                f"name {vlan_name}",
            ]
            if switch_ports:
                # allow acces only to certain ports
                sequence += [
                    # select all affected ports--use f'{i}' so we
                    # support both int and str transparently
                    f"int range {', '.join(f'{i}' for i in switch_ports)}",
                    # For untagged traffic use layer2, access can do a
                    # single VLAN
                    "switchport",
                    "switchport mode access",
                    f"switchport access vlan {vlan_id}",
                    # For tagged traffic; disabled for now because we
                    # can't get both untagged and tagged modes to work
                    # and we prefer untagged since it is easier to
                    # work with on the OS side
                    #f"switchport mode trunk",
                    #f"switchport trunk allowed vlan {vlan_id}",
                    # enable the ports
                    "no shut",
                    "exit",	# exit port config
                ]
            sequence += [
                'exit'	# exit conf terminal
            ]
            self._sequence_run(*sequence)
            self._copy_running_config_retrying()
            return

        with self.p_lock:
            _vlan_create()



    def vlan_destroy(self, vlan_id, vlan_name):

        @commonl.retry_cb_tries(
            ( pexpect.exceptions.ExceptionPexpect, RuntimeError, self.exception ),
            tries = 4,
            header = "vlan_destroy: ", logger = self.logger.info)
        def _vlan_destroy():
            self._open_maybe()
            if self._vlan_get(vlan_id) != None:
                # since this has to copy the running config, do it only if
                # the vlan is there.
                self._sequence_run(
                    "conf terminal",
                    # wipe first
                    f"no vlan {vlan_id}",
                    "exit",
                )
                self._copy_running_config_retrying()

        with self.p_lock:
            _vlan_destroy()



    def _vlan_get(self, vlan_id):
        # False would do
        #
        ## PROMPT#show vlan id 3
        ## VLAN id 3 not found in current VLAN database
        #
        # True is for something like
        #
        ## #show vlan id 3
        ##
        ## VLAN Name                             Status    Ports
        ## ---- -------------------------------- --------- -------------------------------
        ## 3    VLAN0003                         active    Gi1/0/24
        ##
        ## VLAN Type  SAID       MTU   Parent RingNo BridgeNo Stp  BrdgMode Trans1 Trans2
        ## ---- ----- ---------- ----- ------ ------ -------- ---- -------- ------ ------
        ## 3    enet  100003     1500  -      -      -        -    -        0      0
        ##
        ## Remote SPAN VLAN
        ## ----------------
        ## Disabled
        ##
        ## Primary Secondary Type              Ports
        ## ------- --------- ----------------- ------------------------------------------
        ##
        ## PROMPT#
        ##
        #
        try:
            self._open_maybe()
            bad_count = 0
            while True:
                o = self._cmd(f"show vlan id {vlan_id}")
                # We only do a VLAN at the time, so this works to detect
                if b'VLAN Name' in o:
                    return True
                elif b"not found in current" in o:
                    return None		# None for not found, that's the API
                else:
                    bad_count += 1
                    if bad_count > 10:
                        self.logger.warning("unknown output to show vlan id; reached max count, returning None state: %s", o)
                        return None
                    self.logger.warning("unknown output to show vlan id: %s", o)
                    continue
        except Exception as e:
            self.logger.exception("exception running 'show vlan id': %s",
                                  e, exc_info = True)
            return None



    def vlan_get(self, vlan_id):

        @commonl.retry_cb_tries(
            ( pexpect.exceptions.ExceptionPexpect, RuntimeError, self.exception ),
            tries = 4,
            header = "vlan_get: ", logger = self.logger.info)
        def _vlan_get_retry():
            return self._vlan_get(vlan_id)

        with self.p_lock:
            return _vlan_get_retry()



class fake_c(router_c):
    """
    Class for creating a fake router for testing
    """
    def __init__(self, hostname, username = None, password = None, logger = None):
        router_c.__init__(self, hostname, username, password, logger)
        self.logger = logger

    def server_link_setup(self, target, component):
        self.logger.error(f"{component}: set up server link")

    def vlan_create(self, vlan_id, vlan_name, switch_ports):
        self.logger.error(f"{vlan_id}: created for {vlan_name=}")

    def vlan_destroy(self, vlan_id, vlan_name):
        self.logger.error(f"{vlan_id}: destroying for {vlan_name=}")

    def vlan_get(self, vlan_id):
        self.logger.error(f"{vlan_id}: getting")
        return True	# always active



class router_manager_c(ttbl.power.impl_c):
    """
    Power adaptor that will create a VLAN when powered on, remove it
    when off
    """
    def __init__(self,
                 switch_class = None, switch_console = "ssh0", **kwargs):
        ttbl.power.impl_c.__init__(self, off_on_release = True, **kwargs)
        self.name = "router-manager"
        self.upid_set(f"Manager for router/switch {switch_class}")
        # let this be a class NAME so we can initialize with URLs from
        # config files that are parameterized
        if isinstance(switch_class, str):
            self.switch_class = \
                ttbl.value_from_str_casting("class:" + switch_class)
        else:
            self.switch_class = switch_class
        self.switch_console = switch_console


    def _router_make(self, target):
        # we create a router right now because we need to get user
        # name / password, which might change during the lifetime of
        # the object -- meaning: at initialization time we don't know
        # a lot of these parameters.
        # So pull the data from SSH console (hackish) and create a
        # router object; they are lightweight anyway
        console, _name = target.power.impl_get_by_name(self.switch_console)
        username = target.fsdb.get(
            f"interfaces.console.{self.switch_console}.parameter_user",
            console.kws['username'])
        password = console.keyring.get_password(
            f"{ttbl.config.instance}.{target.id}",
            f"interfaces.console.{self.switch_console}.parameter_password")
        if not password:
            password = console.password
        hostname = console.kws['hostname']
        router = self.switch_class(
            hostname, username = username, password = password,
            logger = target.log.logger.getChild("switch")
            #logger = target.log.info,
        )
        return router



    # State is stored in interfaces.power.COMPONENT, so it in the
    # right inventory in the namespace and it doesn't collide with
    # *state*, which is set by the upper layers.
    def on(self, target, component):
        router = self._router_make(target)
        router.server_link_setup(target, component)

    def off(self, target, component):
        pass

    def get(self, target, component):
        return None



class vlan_manager_c(ttbl.power.impl_c):
    """
    Power component that will create a VLAN when powered on, remove it
    when off

    :param ttbl.test_target switch_target: target representing the
      switch

    :param ttbl.router.router_c switch_class: class (derivative of
      router_c) that implements the details of each router
      model/make

      >>> switch_class = ttbl.router.router_cisco_c

    **Implementation Details**

    This class assumes that the switch has an SSH component
    (*switch_console*) from which we extract the username,
    password and hostname for accessing the switch over the
    network.

    For any operation, we create an router object of a class
    derived from :class:`ttbl.router_c` that represents the
    router, which allows us to manipulate it. Which class to use
    is passed in the *switch_class* argument
    (:data:`switch_class`)(e.g.: Cisco Nexus 9k use an SSH
    console; see :class:`ttbl.router.cisco_c`).

    When turning on, we use the :class:`ttbl.router_c` interface
    to tell the switch to create the VLAN; if we have information
    for which ports to enable, we use it so only machines in the
    allocation can access the VLAN.

    When turning off, we tell the switch to destroy the VLAN, so
    no rogue traffic can go through.

    The power state is represented as the VLAN existing or not.

    The 802.11 VLAN ID is taken from the inventory's key *vlan*
    (so it matches what :class:`vlan_pci` does too) and the name
    from the target's name.

    """
    def __init__(self, switch_target,
                 switch_class = None, switch_console = "ssh0", **kwargs):
        assert isinstance(switch_target, ttbl.test_target), \
            "switch_target: expected ttbl.test_target describing the" \
            " switch, got {type(switch_target)}"
        assert issubclass(switch_class, ttbl.router.router_c)
        _console, _name = switch_target.console.impl_get_by_name(
            switch_console,
            arg_name = f"console for switch {switch_target.id}")

        self.switch_target = switch_target
        self.switch_class = switch_class
        self.switch_console = switch_console
        ttbl.power.impl_c.__init__(self, off_on_release = True, **kwargs)
        self.name = "vlan-manager"
        self.upid_set(f"VLAN Manager for switch {switch_target.id}",
                      id = switch_target.id)


    def _router_make(self, target):
        # we create a router right now because we need to get user
        # name / password, which might change during the lifetime of
        # the object
        # So pull the data from SSH console (hackish) and create a
        # router object; they are lightweight anyway
        console, _name = self.switch_target.power.impl_get_by_name(self.switch_console)
        if console.kws == None:
            console.kws = {}
        username = self.switch_target.fsdb.get(
            f"interfaces.console.{self.switch_console}.parameter_user",
            console.kws.get('username', None))
        password = None
        if hasattr(console, "keyring"): # SSH/telnet consoles have this
            password = console.keyring.get_password(
                f"{ttbl.config.instance}.{target.id}",
                f"interfaces.console.{self.switch_console}.parameter_password")
        if not password and hasattr(console, "password"): # SSH/telnet consoles have this
            password = console.password
        hostname = console.kws.get('hostname', None)
        router = self.switch_class(
            hostname, username = username, password = password,
            logger = target.log.logger.getChild("switch")
        )
        return router


    # State is stored in interfaces.power.COMPONENT, so it in the
    # right inventory in the namespace and it doesn't collide with
    # *state*, which is set by the upper layers.
    def on(self, target, component):

        # pull out the list of targets in this allocation; for
        # each one that declares a switch port in this network, we
        # extract the information so we can tell the switch to
        # allow that port's traffic to run on the vlan
        allocid = target.fsdb.get('_alloc.id', None)
        switch_ports = set()
        if allocid:
            # we for the allocation ID, so pull the allocation
            # database structure
            allocdb = ttbl.allocation.get_from_cache(allocid)
            allocdb.target_info_reload()
            for itr_target_name, itr_target in allocdb.targets_all.items():
                # the switch port is stored in the property
                # interconnects.NETWORKNAME[__QUALIFIER].switch_port, so get
                # that
                #switch_port = self._target_property_get(
                interconnect_data = itr_target.property_get("interconnects")
                for ic_name, ic_data in interconnect_data.items():
                    if "__" in ic_name:
                        # this is
                        # interconnects.NETWORKNAME[__QUALIFIER] for
                        # multiple connections from a single target to
                        # the same network
                        _ic_name, qualifier = ic_name.split("__", 1)
                    else:
                        _ic_name, qualifier = ic_name, None
                    if _ic_name == target.id:
                        switch_port = ic_data.get("switch_port", None)
                        if switch_port:
                            target.log.info(
                                f"adding port {switch_port} for {ic_name}")
                            switch_ports.add(switch_port)
        target.log.info("allowed switch_ports: %s", switch_ports)

        # ok, we have all the info now, create the vlan using the
        # router manager object--which we create on the spot, in
        # case username/password/hostname info changed in the inventory
        router = self._router_make(target)
        router.vlan_create(target.tags['vlan'], target.id, switch_ports)


    def off(self, target, component):
        # wipe the VLAN using the router manager
        router = self._router_make(target)
        try:
            router.vlan_destroy(target.tags['vlan'], target.id)
        except requests.exceptions.RequestException as e:
            # we ignore this, there is not much we can do
            target.log.error("can't destroy VLAN %s: %s", target.tags['vlan'], e)


    def get(self, target, component):
        # ask the router manager if the VLAN exists
        router = self._router_make(target)
        r = router.vlan_get(target.tags['vlan'])
        return r != None
