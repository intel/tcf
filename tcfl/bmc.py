#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""Common utilities for configuring and dealing with BMCs/IPMI
===========================================================

BMCs (baseboard management controllers) are included on some machines,
and can be accessed via a local interface from the machine's OS or
remotely via IPMI or Redfish protocols.

When present for use/configuration/testing in a machine, the BMCs can
be used as instrumentation (to control the machine) or as a subject of
testing and execution.

When subject for testing and execution, the following information will
be included in the inventory:

BMC Inventory
-------------

.. _inventory_bmc:

FIXME: this table has horrible formatting when rendered, figure out
how to make the columns narrower so it is readable

.. list-table:: BMC Inventory
   :header-rows: 1
   :widths: 20 10 10 60
   :width: 50%

   * - Field name
     - Type
       (str, bool, integer,
       float, dictionary)
     - Disposition
       (mandatory, recommended,
       optional[default])
     - Description

   * - bmcs
     - Dictionary
     - Optional
     - Information about the different BMCs in the system; most
       commonly there is a single BMC; the first BMC is calle *bmc0*,
       the second *bmc1*, then *bmc2*...

   * - bmcs.bmc0
     - Dictionary
     - Optional
     - Description of the first BMC; the description here apply to the
       rest of the BMCs in *bmc1*, *bmc2*, etc ...

   * - bmcs.bmc0.id
     - int (>= 0)
     - Mandatory
     - Index of this BMC in the system; this will be mapped, in an OS
       specific way. For example, in Linux, index 0 (the first BMC)
       would be mapped to */dev/ipmi0*; as well, when using the
       *ipmitool* command would use *ipmitool -d 0* to refer to it
       from within the system.

   * - bmcs.bmc0.users
     - dictionary
     - Mandatory
     - List of usernames and their passwords; these username and
       passwords are configured in the BMC to use in all the
       interfaces (IPMI from within the system or network) with admin
       privileges.

   * - bmcs.bmc0.mc
     - dictionary
     - Optional
     - Information about the BMC (eg: as returned by *ipmitool mc info*),
       keyed by string, values being strings, integers, floats or bools.

   * - bmcs.bmc0.fru
     - dictionary
     - Optional
     - Information about the FRUs (Field Replaceable Units) reported
       by the BMC (eg: as returned by *ipmitool fru info*).

   * - bmcs.bmc0.fru.FRUNAME
     - dictionary
     - Optional
     - Information about the *FRUNAME*, keyed by string, values being
       strings, integers, floats or bools.

   * - bmcs.bmc0.user0.name
     - string
     - Optional
     - Name of the first user configured to access the BMC in all the
       channels.

       Note subsequent user names would be configured using
       *bmcs.bmc1.user1.name*, *bmcs.bmc2.user.name* ...

   * - bmcs.bmc0.user0.channels
     - string
     - Optional
     - List of integers separated with colons (eg: 1:2:3) describing
       on which channels this user entry shall be created; defaults to
       those specifed in all the network entries
       (*bmcs.bmcN.network\*.channel*).

   * - bmcs.bmc0.user0.uid
     - integer (>= 0)
     - Optional
     - User ID to use (note User IDs are specific to each channel, but
       for simplicity we use the same for all channels)

   * - bmcs.bmc0.user0.password
     - string
     - Mandatory (if user name specified)
     - Password for the BMC user described in *bmcs.bmc0.user.name*.
       Note this can be considered a a security issue depending on how
       this BMC is configured and for what. If the BMC is considered
       part of what is being tested and the target is configured to be
       AC powered off once it is released, then knowing the password
       doesn't grant access to the BMC, since the BMC will be hard
       powered off.

       Note subsequent user passwords would be configured using
       *bmcs.bmc1.user.password*, *bmcs.bmc2.user.password* ...

   * - bmcs.bmc0.network0
     - dictionary
     - Optional
     - Dictionary describing the settings for the default network
       connections this BMC provides. Other network connections are
       called *network1*, *network2*, etc.... and follow the same fields
       as *bmcs.bmc0.network0*. This field is mandatory only if the BMC
       provides network access.

   * - bmcs.bmc0.network0.mac_addr
     - string
     - Optional
     - Ethernet MAC address for this BMC's network connection (if known)

   * - bmcs.bmc0.network0.ipv4_addr
     - string
     - Optional
     - IPv4 address for this BMC's network connection (if
       known). This is mandatory if the *ipv4_src* below is *static*.

   * - bmcs.bmc0.network0.ipv4_netmask
     - string
     - Optional
     - IPv4 network mask for this BMC's network connection (if
       known). This is mandatory if the *ipv4_src* below is *static*.

   * - bmcs.bmc0.network0.ipv4_gateway
     - string
     - Optional
     - IPv4 gateway address mask for this BMC's network connection (if
       known). This is always optional.

   * - bmcs.bmc0.network0.ipv4_src
     - string
     - Mandatory
     - Indicates the source of the IPv4 addressing information; valid
       settings are *static* or *dhcp*.

   * - bmcs.bmc0.network0.channel
     - integer
     - Mandatory
     - BMC channel used for this network connection (eg: 1, 3)

   * - bmcs.bmc0.network0.interface
     - integer
     - Optional
     - BMC interface to connect to this channel; this can be passed to
       the *ipmitool -I* command line option. Known values are *imb*,
       *lan*, *lanplus*, *open*, *serial-basic*, *serial-terminal*,
       *usb*.

       To obtain it for the *ipmitool* tool, for example:

       >>> interface = target.kws.get("bmcs.bmc0.network0.interface", None)
       >>> interface = f"-I {interface}" if interface else ""


   * - bmcs.bmc0.network0.cipher
     - integer
     - Optional
     - BMC cipher type to use to connect over the network; this is
       used for the *ipmitool -C* command line option. For example,
       for *OpenBMC* we need *17*.

       To obtain it for the *ipmitool* tool, for example:
     
       >>> cipher = target.kws.get("bmcs.bmc0.network0.cipher", None)
       >>> cipher = f"-C {cipher}" if cipher else ""

   * - bmcs.bmc1
     - Dictionary
     - Optional
     - Description for the second BMC, same fields as *bmcs.bmc0*

   * - bmcs.bmc2
     - Dictionary
     - Optional
     - Description for the third BMC, same fields as *bmcs.bmc0*

From the POS execution environment, the utilities included here can be
used to reset or configure a BMC to well known settings; for example,
to power on in POS environment and setup all BMCs exposed on the
inventory:

>>> import tcfl.tc
>>> import tcfl.bmc
>>>
>>> @tcfl.tc.interconnect()
>>> @tcfl.tc.target("pos_capable")
>>> class _test(tcfl.tc.tc_c):
>>> 
>>>     def eval(self, target):
>>>         ic.power.on()
>>>         target.pos.boot_to_pos()
>>> 
>>>         tcfl.bmc.setup_discover_ipmitool(target, True)

The base utilities use the *IPMI* protocol since when the BMC is not
configured, there is no way to access it over the network to use
protocols such as *Redfish*.

See :func:`setup_discover_all_ipmitool`, :func:`setup_ipmitool` and
:func:`discover_ipmitool` for more information on inventory requirements.


PENDING
-------

- Use of redfish to pull most of the information

BMC Utility functions
---------------------
"""


import collections
import json
import pprint
import sys
import time

import commonl
import tcfl



def ipmitool_info_parse(output):
    """
    Parse output from *ipmitool <something> info* and *ipmitool
    <otherthing> print* commands into a dictionary.

    *ipmitool* informational commands output more or less in the form::

      SOMEKEY      : SOMEVALUE
       SUBKEY      : SUBVALUE
       ENUMERATION :
          VALUE1
          VALUE2

    Which we want to transate into::

      {
          'SOMEKEY': {
              'SUBKEY': 'SUBVALUE',
              'ENUMERATION': [ 'VALUE1', 'VALUE2' ]
          }
      }

    Special cases this function considers:

    - from *ipmitool fru info*, which prints as

    :param str output: command's output to parse
    :returns dict: dictionary with the parsed information

    """

    def _value_cast(value):
        # do a basic value conversion from strings
        # yes -> True
        # no -> False
        # integer -> integer
        # rest is a string
        if value.lower() == "yes":
            return True
        if value.lower() == "no":
            return False
        try:
            # convert integers to integers
            return int(value)
        except ValueError:
            pass
        # nah, a string, no casting
        return value

    data = collections.OrderedDict()
    current_group = None
    current_value = None
    current_field = []
    for line in output.splitlines():
        if 'command failed' in line:
            continue
        # don't strip fully, we need the left spaces to decide where
        # things go
        line = line.rstrip()
        if not line:
            continue
        if not line.startswith(' '):
            field, value = line.split(":", 1)
            field = field.strip()
            value = value.strip()
            if field and value:
                # Handle
                #
                ## KEYA : VALUEA
                ##  KEY1 : VALUE1
                ##  KEY2 : VALUE2
                #
                # Which shall go to
                #
                # { KEYA : { VALUEA: { KEY1: VALUE1, KEY2: VALUE2 } } }
                current_group = {}
                data.setdefault(field, {})
                value = _value_cast(value)
                data[field].setdefault(value, {})
                # like this we make sure that if we exists, we haven't
                # overriden it, but extend it
                current_group = data[field][value]
            elif value == "":
                # No value, means next is lines starting with four spaces
                # in a list of settings which we will convert into a
                # dict of True later at the inventory
                current_group = []
                data[field] = current_group
            else:
                data.setdefault(field, _value_cast(value))
                current_group = data[field]
        elif line.startswith('    '):
            # This are lines starting with four spaces
            # in a list of settings, see above in *value == ""*
            current_group.append(line.strip())
        elif line.startswith(' '):
            field, value = line.split(":", 1)
            field = field.strip()
            value = value.strip()
            if all(i == "." for i in value):
                continue
            current_group[field] = _value_cast(value)

    # Hack: clean up artifacts
    #
    # top levels will show up as:
    #
    ## { key: { value: {} } }
    #
    # because it gets kinda hard to figure out if it is correct or not
    # due to the output format, so we just correct this here. It is
    # late and ... well, this works
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if len(value) != 1:
            continue
        real_value = list(value.keys())[0]
        if value[real_value] != {}:
            continue
        data[key] = real_value

    return data


def ipmitool_superuser_setup(target, uid, username, password,
                             channels, bmc_id = 0):
    """
    Create a privileged user with *ipmitool* over local access

    **local**: this will use the local IPMI protocol to setup a BMC for
    remote access, thus it is assumed the host OS running on the
    target has *ipmitool* installed and the user has privilege to
    access the IPMI device node.

    :param tcfl.tc.target_c target: target on which to operate

    :param int uid: User ID to configure (eg: 2)

    :param str username: name of the user to configure; this must be
       acceptable to the BMC implementation, so keep them short and
       simple

    :param str password: password for the user to configure; this must be
       acceptable to the BMC implementation, so keep them short and
       simple

    :param list(int) channels: list of channels in which to configure
       the user; IPMI allows to configure different users to different
       access channels.

    :param int bmc_id: (optional) BMC index to use; normally this is
       zero, since most systems only have one BMC. Maps to
       */dev/ipmi<BMC_ID>*.
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(uid, int) and uid >= 0
    assert isinstance(username, str)
    assert isinstance(password, str)
    commonl.assert_list_of_types(channels, "list of channels", "channel",
                                 ( int, ))
    assert isinstance(bmc_id, int) and bmc_id >= 0

    # override whatever is there in the uid, so disable first
    target.report_info(f"bmc{bmc_id}: adding {username} as UID {uid}",
                       dlevel = 1)
    # This might fail if the user is not yet created, so just go like this
    target.shell.run(f"ipmitool -d {bmc_id} user disable {uid} || true")
    target.shell.run(f"ipmitool -d {bmc_id} user set name {uid} '{username}'")
    target.shell.run(f"ipmitool -d {bmc_id} user set password {uid} '{password}'")
    target.shell.run(f"ipmitool -d {bmc_id} user enable {uid}")
    for channel in channels:
        target.shell.run(
            f"ipmitool -d {bmc_id} channel setaccess {channel} {uid}"
            " ipmi=on privilege=4")
    target.report_info(f"bmc{bmc_id}: added {username} as UID {uid} in"
                       " channels {','.join(channels}")


def ipmitool_ipv4_setup(target, channel, ipaddr, netmask, gateway,
                        mac_addr = None, bmc_id = 0, dhcp = False):
    """
    Configure an IPMI network channel with static IPv4 with *ipmitool*
    via local access.

    **local**: this will use the local IPMI protocol to setup a BMC for
    remote access, thus it is assumed the host OS running on the
    target has *ipmitool* installed and the user has privilege to
    access the IPMI device node.

    :param tcfl.tc.target_c target: target on which to operate

    :param int uid: User ID to configure (eg: 2)

    :param str ipaddr: IPv4 address to give to the channel (numeric). eg:

      >>> 192.168.4.4

    :param str netmask: IPv4 netmask to give to the channel. eg:

       >>> 255.255.252.0

    :param str gateway: (optional) IPv4 address for the routing
       gateway; note this has to be in the same network as the
       *ipaddr* itself. eg:

       >>> 192.168.4.1

    :param list(int) channels: list of channels in which to configure
       the user; IPMI allows to configure different users to different
       access channels. eg:

       >>> [ 1, 3, 4 ]

    :param int bmc_id: (optional) BMC index to use; normally this is
       zero, since most systems only have one BMC. Maps to
       */dev/ipmi<BMC_ID>*. 
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(channel, int) and channel >= 0
    assert dhcp == None or isinstance(dhcp, bool)
    if dhcp:
        assert isinstance(ipaddr, str)
        assert isinstance(netmask, str)
        assert isinstance(gateway, str)
    assert isinstance(bmc_id, int) and bmc_id >= 0
    target.report_info(f"bmc{bmc_id}: configuring network channel {channel}")
    if dhcp == None:
        target.report_pass(
            f"bmc{bmc_id}: not touching network config")
    elif dhcp:
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} access off")
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} ipsrc dhcp")
        target.report_pass(
            f"bmc{bmc_id}: configured network channel {channel} to DHCP")
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} access on")
    else:
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} access off")
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} ipsrc static")
        if mac_addr:
            target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} macaddr {mac_addr}")
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} ipaddr {ipaddr}")
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} netmask {netmask}")
        # need to set this after the netmask, in some platforms it might
        # get wiped
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} defgw ipaddr {gateway}")
        target.report_pass(
            f"bmc{bmc_id}: configured network channel {channel}"
            f" to {ipaddr}/{netmask} via {gateway}"
        )
        target.shell.run(f"ipmitool -d {bmc_id} lan set {channel} access on")

    # verify network settings
    output = target.shell.run(f"ipmitool lan print {channel}",
                              output = True, trim = True)
    if dhcp == False:
        musthave = [
            f'IP Address Source       : Static Address',
            f'IP Address              : {ipaddr}',
            f'Subnet Mask             : {netmask}',
            f'Default Gateway IP      : {gateway}'
        ]
    else:
        musthave = []
    if mac_addr:
        musthave.append(
            f'MAC Address             : {mac_addr.lower()}')
    for s in musthave:
        if s not in output:
            raise tcfl.tc.failed_e(
                f"bmc{bmc_id}: configuration w/ ipmitool failed, can't find "
                f"expected string: {s}", dict(output = output))
    # FIXME: extract current MAC addr and update inventory?
    target.report_pass(
        f"bmc{bmc_id}: configuration of network channel {channel} verified")


def ipmitool_ipv4_static_setup(target, channel, ipaddr, netmask, gateway,
                               mac_addr = None, bmc_id = 0):
    return ipmitool_ipv4_setup(target, channel, ipaddr, netmask, gateway,
                               mac_addr = mac_addr, bmc_id = 0, dhcp = False):


def ipmitool_mc_reset(target, bmc_id = 0, reset_type = "cold",
                      reset_command = None, selector = None):
    """
    Rest an MC via *ipmitool* and wait for it to come back

    :param tcfl.tc.target_c target: target on which to operate

    :param str reset_type: (optional; default *cold*) Type of reset to
      execute; *cold* or *warm*.

    :param int bmc_id: (optional) BMC index to use; normally this is
       zero, since most systems only have one BMC. Maps to
       */dev/ipmi<BMC_ID>*. 

    :param str selector: (optional) how to select which BMC device to
      use; these are passed directly to the *ipmitool* command line.

      It will default to a local BMC access via IPMI instance
      *bmc_id* (which also defaults to zero), becoming::

          ipmitool -d 0 mc reset cold

      However, to use for example a remote BMC, the argument

      >>> "-C 17 -H 192.168.1.2 -U username -P password -I lanplus"

      would become::

          ipmitool -C 17 -H 192.168.1.2 -U username -P password -I lanplus mc reset cold

      allowing us to reset a remote BMC.

    :param str reset_command: (optional) use this command to
      *ipmitool* to reset the MC (instead of the default *mc reset
      RESET_TYPE*
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(bmc_id, int) and bmc_id >= 0
    assert reset_type in [ "cold", "warm" ] 
    assert selector == None or isinstance(selector, str)

    if selector == None:
        selector = f"-d {bmc_id}"

    if reset_command:
        target.shell.run(f"ipmitool {selector} {reset_command}")
    else:
        target.shell.run(f"ipmitool {selector} mc reset {reset_type}")
    wait_period = 20
    target.report_info(f"bmc{bmc_id}: waiting {wait_period}s for controller to reset")
    time.sleep(wait_period)
    # Wait for BMC to be online again by just running the mc info
    # command until it works. If it fails, it'll return something
    # like
    #
    ## Get Device ID command failed: 0xff Unspecified error
    ## Get Device ID command failed: Unspecified error
    #
    # or something like
    #
    ## Unable to establish IPMI v2 / RMCP+ session
    top = 10
    for count in range(top):
        try:
            target.shell.run(f"ipmitool {selector} -c mc guid")
            break
        except tcfl.tc.error_e as e:
            if 'error detected in shell' not in str(e):
                raise
            # this could be failing for a bunch of things not
            # necessary specifc to the MC not being yet up, but
            # because they'll be unlikely and will make the
            # code way harder to follow, just power through
            # retrying and if it is a known bad condition, it will
            # timeout and break
        target.report_info(f"bmc{bmc_id}: waiting {wait_period}s more"
                           f" ({count}/{top}) for MC to reset")
        time.sleep(wait_period)
    else:
        raise tcfl.tc.error_e(f"bmc{bmc_id}: MC didn't come back from"
                              f" cold reset after {wait_period * count}s")


def setup_ipmitool(target, bmc_id, bmc_name, bmc_data, dhcp = False):
    """
    Setup a **local** BMC using *ipmitool* with information from the
    inventory.

    **local**: this will use the local IPMI protocol to setup a BMC for
    remote access, thus it is assumed the host OS running on the
    target has *ipmitool* installed and the user has privilege to
    access the IPMI device node.

    This needs at least in the inventory the following information for
    each BMC (*bmcs.bmc0*, *bmcs.bmc1*, *bmcs.bmc2*, ...):

    - The ID field: *bmcs.bmc0.id: 0*

    For basic static IPv4 access on one or more channels:

    - bmcs.bmc0.network0.
    - bmcs.bmc0.network0.channel: 3
    - bmcs.bmc0.network0.ipv4_addr: <IPADDRESS>
    - bmcs.bmc0.network0.ipv4_netmask: <NETMASK>
    - bmcs.bmc0.network0.ipv4_gateway: <GATEWAY'S IPADDRESS>
    - bmcs.bmc0.network0.ipv4_src: static

    For users to be configured, networking has to be configured and:

    - bmcs.bmc0.user0.name: USERNAME
    - bmcs.bmc0.user0.password: PASSWORD
    - bmcs.bmc0.user0.uid: 2             # example
    - bmcs.bmc0.user0.channel: 2:3:4     # example

    if the uid is not given, 2 is used as default; if channels are not
    given, the ones declared in the network section are used.

    """
    # This shall be a general BMC extraction function using
    # ipmitool and no Intel secret sauces

    network_channels = []
    networks = collections.OrderedDict()
    users = collections.OrderedDict()
    
    # From the inventory data, collect the channels from
    #
    # bmcs.bmc0.network[N].channel
    #
    # and the users
    for key, value in bmc_data.items():
        if key.startswith("network"):
            if not 'channel' in value:
                continue
            networks[key] = value
            network_channels.append(value['channel'])
        elif key.startswith("user"):
            user = {}
            if not 'name' in value:
                target.report_data(
                    "Warnings [%(type)s]",
                    f"bmc{bmc_id}: no field 'name' in user descriptor 'bmcs.{bmc_name}.{key}'",
                    1
                )
                continue
            username = value.get('name')
            if not 'password' in value:
                target.report_data(
                    "Warnings [%(type)s]",
                    f"bmc{bmc_id}: no field 'password' in user descriptor 'bmcs.{bmc_name}.{key}'",
                    1
                )
                continue
            password = value.get('password')
            uid = value.get('uid', 2)
            users[username] = dict(
                password = password,
                uid = uid
            )

    # okie, so we have all the user info now then
    for username, data in users.items():
        channels = []
        # specified as C1[:C2[:C3[:...]]]
        for i in data.get('channels', '').split(":"):
            if i:
                channels.append(int(i))
        if not channels:
            # if we didn't specify user channels to set in the
            # inventory, just use the ones declared in the network
            # sections
            target.report_info(f"BMC: user {username} configured in"
                               f" general network channels {':'.join(channels)}")
            channels = network_channels
        else:
            target.report_info(f"BMC: user {username} configured in"
                               f" user-specific channels {':'.join(channels)}")
        ipmitool_superuser_setup(target, data['uid'], username,
                                 data['password'], channels, bmc_id = bmc_id)

    for network, data in networks.items():
        if dhcp == True or dhcp == None:
            ipmitool_ipv4_setup(
                target, data['channel'],
                None, None, None,
                mac_addr = data.get('mac_addr', None),
                bmc_id = bmc_id, dhcp = dhcp)
        else:
            ipmitool_ipv4_setup(
                target, data['channel'],
                data['ipv4_addr'], data['ipv4_netmask'], data['ipv4_gateway'],
                mac_addr = data.get('mac_addr', None),
                bmc_id = bmc_id,  dhcp = False)


def discover_ipmitool(target, bmc_id, selector, update_inventory = False):
    """
    Discover information from a BMC using *ipmitool*

    Pull information from the BMC using the *mc info* and *fru print*
    subcommands to gather microcontroller and FRU
    information. Optionally updates the inventory with said
    information in the trees:
    
    - *bmcs.bmc<BCM_ID>.mc*
    - *bmcs.bmc<BCM_ID>.fru*

    :param tcfl.tc.target_c target: target on which to operate

    :param int bmc_id: BMC index to use; normally this is
       zero, since most systems only have one BMC. Maps to
       */dev/ipmi<BMC_ID>*. 

    :param str selector: how to select which BMC device to
      use; these are passed directly to the *ipmitool* command line.

      It will default to a local BMC access via IPMI instance
      *bmc_id*, becoming::

          ipmitool -d 0 COMMANDS

      However, to use for example a remote BMC, the argument

      >>> "-C 17 -H 192.168.1.2 -U username -P password -I lanplus"

      would become::

          ipmitool -C 17 -H 192.168.1.2 -U username -P password -I lanplus COMMANDS

      allowing us to discover a remote BMC.

    :param bool update_inventory: (optional, default *False*) update
      the inventory with the discovered data.

    :returns dict: dictionary of information discovered.

    """
    # Gather mc info by both methods, compare them
    # Can we gather data via the network?
    target.report_info(f"bmc{bmc_id}: collecting MC and FRU information",
                       dlevel = 1)
    target.shell.run(f"ipmitool {selector} mc info > /tmp/mc.info")
    target.shell.run(f"ipmitool {selector} fru print > /tmp/fru.info")

    # info.local seems to be more complete in some platforms
    mc_info_name = target.testcase.report_file_prefix + "mc.info"
    fru_info_name = target.testcase.report_file_prefix + "fru.info"
    target.ssh.copy_from("/tmp/mc.info", mc_info_name)
    target.ssh.copy_from("/tmp/fru.info", fru_info_name)
    mc_data = ipmitool_info_parse(open(mc_info_name).read())
    fru_data = ipmitool_info_parse(open(fru_info_name).read())

    bmc_name = f"bmc{bmc_id}"

    target.report_info(f"bmc{bmc_id}: updating inventory with MC and FRU information",
                       dlevel = 1)
    target.property_set(f"bmcs.{bmc_name}.id", bmc_id)
    # this dictionary is just single level
    d = {}
    for key, value in tcfl.inventory_keys_fix(mc_data).items():
        # inventory supports only escalars or dicts, so lists are
        # dicts of bools
        if isinstance(value, list):
            for i in value:
                d[f"bmcs.{bmc_name}.mc.{key}.{i}"] = True
        else:
            d[f"bmcs.{bmc_name}.mc.{key}"] = value
    for key, value in commonl.dict_to_flat(
            tcfl.inventory_keys_fix(fru_data["FRU Device Description"])):
        if isinstance(value, list):
            d[f"bmcs.{bmc_name}.fru." + key] = ":".join(value)
        else:
            d[f"bmcs.{bmc_name}.fru." + key] = value
    # clean whatever is there now, re-populate it
    target.property_set(f"bmcs.{bmc_name}.mc", None)
    target.property_set(f"bmcs.{bmc_name}.fru", None)
    target.properties_set(d)
    target.report_pass(f"bmc{bmc_id}: updated inventory with MC and FRU information")
    return dict(mc = mc_data, fru = fru_data)


def setup_discover_all_ipmitool(target, discover = True):
    """
    Setup all the local BMCs using *ipmitool*

    This iterates over all the available BMCs in the system (as
    described by the inventory entries) *bmcs.bmc*, *bmcs.bmc1*,
    *bmcs.bmc2*... and calls :func:`setup_ipmitool` (refer to it
    for more details).

    :param bool discover: (optional, default *True*) this function
      will also discover BMC and system information using the IPMI
      tooling and publish it in the inventory.

    :returns dict: if *discover* is enabled, returns a dictionary
      keyed by BMC name of information discovered.
    """
    d = {}
    for bmc_name, bmc_data in target.kws.get("bmcs", {}).items():
        if bmc_name.startswith("bmc"):
            # bmc_name is always bmc<NUMBER> by inventory spec; there
            # is always bmc0 if there is a bmc.
            bmc_id = int(bmc_name[3:])
        else:
            # recoverable error
            target.report_data(
                "Warnings [%(type)s]",
                f"BMC: bad name '{bmc_name}', does not start with *bmc*",
                1
            )
            continue
        setup_ipmitool(target, bmc_id, bmc_name, bmc_data)
        if discover:
            # clean whatever is there now, re-populate it
            target.property_set(f"bmcs.{bmc_name}.mc", None)
            target.property_set(f"bmcs.{bmc_name}.fru", None)
            d[bmc_name] = discover_ipmitool(target, bmc_id, f"-d {bmc_id}",
                                            update_inventory = True)
    return d


def setup_all_ipmitool(target):
    """
    Setup all the local BMCs using *ipmitool*

    This iterates over all the available BMCs in the system (as
    described by the inventory entries) *bmcs.bmc*, *bmcs.bmc1*,
    *bmcs.bmc2*... and calls :func:`setup_ipmitool` (refer to it
    for more details).
    """
    setup_discover_all_ipmitool(target, False)
