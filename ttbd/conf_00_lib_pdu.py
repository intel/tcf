#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Add functions more or less alphabetically
"""
.. _conf_00_lib_pdu:

Configuration API for PDUs and other power switching equipment
--------------------------------------------------------------
"""

import logging
import urllib.parse

def target_pdu_socket_add(name, pc, tags = None, power = True):
    if tags == None:
        tags = {}
    target = ttbl.test_target(name, _tags = tags)
    target.interface_add("power", ttbl.power.interface(pc))
    ttbl.config.target_add(
        target, tags = dict(
            idle_power_off = 0, idle_poweroff = 0,     # COMPAT
            idle_power_fully_off = 0
        )
    )
    if power:
        # FIXME: untested
        target.power.put_on(target, ttbl.who_daemon(), {}, {}, None)
    return target

def apc_pdu_add(name, powered_on_start = None, hostname = None):
    """Add targets to control the individual sockets of an APC PDU power
    switch.

    The APC PDU needs to be setup and configured (refer to the
    instructions in :class:`ttbl.apc.pc`); this function exposes the
    different targets for to expose the individual sockets for debug.

    Add to a configuration file
    ``/etc/ttbd-production/conf_10_targets.py`` (or similar):

    .. code-block:: python

       apc_pdu_add("sp16")

    where *sp16* is the name (hostname of the PDU)

    yields::

      $ tcf list
      local/sp16-1
      local/sp16-2
      local/sp16-3
      ...
      local/sp16-24

    for a 24 outlet PDU

    :param bool powered_on_start: (optional) if *True*, turn on the
      sockets when we call this function; defaults to *False*.

    :param str hostname: (optional) hostname or IP address of the APC
      unit if different from the *name*.

    """
    assert name == None or isinstance(name, str)
    assert hostname == None or isinstance(hostname, str)
    assert powered_on_start == None or isinstance(powered_on_start, bool)

    if hostname == None:
        hostname = name

    _apc = ttbl.apc.pc(hostname, 1)
    for i in range(1.._apc.outlets):
        target = ttbl.test_target("%s-%d" % (name, i))
        target.interface_add(
            "power",
            ttbl.power.interface(ttbl.apc.pc(hostname, i)))
        ttbl.config.target_add(target, tags = dict(
            idle_power_off = 0, idle_poweroff = 0,	# COMPAT
            idle_power_fully_off = 0
        ))
        target.disable("")
        if powered_on_start:
            target.power.put_on(target, ttbl.who_daemon(), {}, {}, None)


def dlwps7_add(hostname, powered_on_start = None, basename = None,
               user = "admin", password = "1234"):
    """Add test targets to individually control each of a DLWPS7's sockets

    The DLWPS7 needs to be setup and configured; this function exposes
    the different targets for to expose the individual sockets for debug.

    Add to a configuration file
    ``/etc/ttbd-production/conf_10_targets.py`` (or similar):

    .. code-block:: python

       dlwps7_add("sp6")

    yields::

      $ tcf list
      local/sp6-1
      local/sp6-2
      local/sp6-3
      local/sp6-4
      local/sp6-5
      local/sp6-6
      local/sp6-7
      local/sp6-8

    Power controllers for targets can be implemented instantiating an
    :py:class:`ttbl.pc.dlwps7`:

    .. code-block:: python

       pc = ttbl.pc.dlwps7("http://admin:1234@spM/O")

    where *O* is the outlet number as it shows in the physical unit and
    *spM* is the name of the power switch.

    :param str hostname: Hostname of the switch

    :param str user: User name for HTTP Basic authentication

    :param str password: password for HTTP Basic authentication

    :param str basename: (optional) use something else to generate the
      target names if we want it different than the hostname. Defaults
      to *hostname*. Has to be a simple name (a-zA-Z0-9_-).

      You will need to set this if hostname is an FQDN (eg:
      *hostname.subdomain.domain* vs just *hostname*) or an IP address
      (eg: *192.168.4.3*).

    :param bool powered_on_start: what to do with the power on the
      downstream ports:

      - *None*: leave them as they are

      - *False*: power them off

      - *True*: power them on

    **Overview**

    **Bill of materials**

    - a DLWPS7 unit and power cable connected to power plug

    - a network cable

    - a connection to a network switch to which the server is also
      connected (*nsN*)

    **Connecting the power switch**

    Choose a name for the power switch (for example: *spM*), where *M*
    is a number.

    There are multiple valid ways to connect smart PDUs to the
    network; it is recommended they are in an isolated network

    - Isolated network

      1. Ensure you have configured an class C *192.168.X.0/24*,
         configured with static IP addresses, to which maybe only this
         server has access to connect IP-controlled power
         switches.
  
         Follow :ref:`these instructions <internal_network>` to create a
         network.
  
         You might need a new Ethernet adaptor to connect to said
         network (might be PCI, USB, etc).
  
      2. connect the power switch to said network
  
      3. enter the *PDUNAME* name in ``/etc/hosts`` as described
         above.
  
         .. warning:: if your system uses proxies, you need to add
            *PDUNAME* also to the *no_proxy* environment variables in
            :file:`/etc/bashrc` and others to avoid the daemon trying
            to access the power switch through the proxy, which will
            not work.

    **Configuring the system**

    1. The power switch starts with IP address *192.168.0.100*; it needs
       to be changed.

       Determine which IP address the PDU will have (static, DHCP, etc)

       There are multiple ways to do this, but this guide is by no
       means complete:

       - routing hack on a local Linux machine: in a machine connected
         to a wired network, add a secondary IP address in the
         *192.168.0.0/24* network and access the PDU through that:

         a. select the network interface (eg: *eth0*)

         b. add routing through an alias::

              # ifconfig eth0:2 192.168.0.3/24

         c. ensure the PDU is connected to the same network switch as
            the Linux machine

       - USB Network dongle connected directly (or with a crossover
         cable if needed) to the PDU:

              # ifconfig IFACENAME 192.168.0.3/24

    2. With a web browser, access the switch's web control interface
       at *http://192.168.0.100*

    3. Enter the default user *admin*, password *1234*, select *ok*

    4. Scroll down to *Setup* menu to configure the different parts
       needed; on each of this steps, make sure to hit submit for each
       individual change.

       a. Lookup setup of IP address, change to the chosen IP address
          (or DHCP if so selected); hit the *submit* next to it.

       b. Disable the security lockout in section *Delay*

          Set *Wrong password lockout* set to zero minutes

       c. Turn on setting power after power loss:

          *Power Loss Recovery Mode > When recovering after power
          loss* select *Turn all outlets on*

       d. Extra steps needed for newer units
          (https://dlidirect.com/products/new-pro-switch)

          The new refreshed unit looks the same, but has wifi
          connectivity and pleny of new features, some of which
          need tweaking; login to the setup page again and for each
          of this, set the value/s and hit *submit* before going to
          the next one:

          - Access setings (quite important, as this allows the
            driver to access the same way for the previous
            generation of the product too):

            ENABLE: *allow legacy plaintext login methods*

            Note below it is explained why this is not a security
            problem in this kind of deployments. On shared networks,
            an upgrade to https might be needed.

       e. If the PDU is in an isolated network, keep the default user
          and password at *admin*/*1234*, the default configuration
          relies on it. It makes no sense to change it anyway as you
          will have to write them down in the
          configuration. Limitations of HTTP Basic Auth.

       f. If the routing hack method was used, remove it::

            # ifconfig eth0:2 down


    If the name of the PDU does not resolve over DNS, you might add it
    to the server's */etc/hosts*::

       IPADDRESS  PDUNAME PDUNAME.DOMAINNAME

    (the domainname is optional)

    """
    if basename == None:
        basename = hostname
    else:
        isinstance(basename, str)

    for i in range(1, 9):
        name = "%s-%d" % (basename, i)
        pc_url = "http://%s:%s@%s/%d" % (user, password, hostname, i)
        target = target_pdu_socket_add(
            name,
            ttbl.pc.dlwps7(pc_url),
            power = powered_on_start,
            # Always keep them on, unless we decide otherwise--we need
            # them to control other components
            tags = dict(
                idle_power_off = 0, idle_poweroff = 0, # COMPAT
                idle_power_fully_off = 0
            ))
        target.disable("")


try:
    import ttbl.raritan_emx
    def raritan_emx_add(url, outlets = 8, targetname = None,
                        https_verify = True, powered_on_start = None,
                        pdu_password = None):
        """
        Add targets to control the individual outlets of a Raritan EMX PDU

        This is usually a low level tool for administrators that allows to
        control the outlets individually. Normal power control for targets
        is implemented instantiating a power controller interface as
        described in :py:class:`ttbl.raritan_emx.pci`.

        For example add to a ``/etc/ttbd-production/conf_10_targets.py``
        (or similar) configuration file:

        .. code-block:: python

           raritan_emx_add("https://admin:1234@sp6")

        yields::

          $ tcf list
          local/sp6-1
          local/sp6-2
          local/sp6-3
          local/sp6-4
          local/sp6-5
          local/sp6-6
          local/sp6-7
          local/sp6-8

        :param str url: URL to access the PDU in the form::

            https://[USERNAME:PASSWORD@]HOSTNAME

          Note the login credentials are optional, but must be matching
          whatever is configured in the PDU for HTTP basic
          authentication and permissions to change outlet state.

        :param int outlets: number of outlets in the PDU (model specific)

          FIXME: guess this from the unit directly using JSON-RPC

        :param str targetname: (optional) base name
          to for the target's; defaults to the hostname (eg: for
          *https://mypdu.domain.com* it'd be *mypdu-1*, *mypdu-2*, etc).

        :param bool powered_on_start: what to do with the power on the
          downstream ports:

          - *None*: leave them as they are
          - *False*: power them off
          - *True*: power them on

        :param bool https_verify: (optional, default *True*) do or
          do not HTTPS certificate verification.

        **Setup instructions**

        Refer to :ref:`ttbl.raritan_emx.pci <raritan_emx_setup>`.
        """
        _url = urllib.parse.urlparse(url)
        if targetname == None:
            targetname = _url.hostname.split('.')[0]
        for outlet in range(1, outlets + 1):
            name = "%s-%d" % (targetname, outlet)
            target = target_pdu_socket_add(
                name,
                ttbl.raritan_emx.pci(url, outlet, https_verify,
                                     password = pdu_password),
                power = powered_on_start,
                # Always keep them on, unless we decide otherwise--we need
                # them to control other components
                tags = dict(
                    idle_power_off = 0, idle_poweroff = 0, # COMPAT
                    idle_power_fully_off = 0
                ))
            target.disable("")

except ImportError as e:
    logging.exception("Can't use raritan PDUs, missing libraries: %s", e)


def usbrly08b_targets_add(serial_number, target_name_prefix = None,
                          powered_on_start = None):
    """Set up individual power control targets for each relay of a
    `Devantech USB-RLY08B
    <https://www.robot-electronics.co.uk/htm/usb_rly08btech.htm>`_

    See below for configuration steps

    :param str serial_number: USB Serial Number of the relay board
      (:ref:`finding <usbrly08b_serial_number>`).

    :param str target_name_prefix: (optional) Prefix for the target
      names (which defaults to *usbrly08b-SERIALNUMBER-*)

    :param bool powered_on_start: what to do with the power on the
      downstream ports:

      - *None*: leave them as they are

      - *False*: power them off

      - *True*: power them on

    **Bill of materials**

    - A Devantech USB-RLY08B USB relay controller
      (https://www.robot-electronics.co.uk/htm/usb_rly08btech.htm)

    - a USB A-Male to B-female to connect it to the server

    - an upstream USB A-female port to the server (in a hub or root hub)

    **Connecting the relay board to the system**

    1. Connect the USB A-Male to the free server USB port

    2. Connect the USB B-Male to the relay board

    **Configuring the system for the fixture**

    1. Choose a prefix name for the target (eg: *re00*) or let it be
       the default (*usbrly08b-SERIALNUMBER*).

    2. Find the relay board's :ref:`serial number
       <usbrly08b_serial_number>` (:ref:`more methods <find_usb_info>`)

    3. Ensure the device node for the board is accessible by the user
       or groups running the daemon. See
       :py:class:`ttbl.usbrly08b.pc` for details.

    3. To create individual targets to control each individual relay,
       add in a configuration file such as
       ``/etc/ttbd-production/conf_10_targets.py``:

       .. code-block:: python

          usbrly08b_targets_add("00023456")

       which yields, after restarting the server::

         $ tcf list -a
         local/usbrly08b-00023456-01
         local/usbrly08b-00023456-02
         local/usbrly08b-00023456-03
         local/usbrly08b-00023456-04
         local/usbrly08b-00023456-05
         local/usbrly08b-00023456-06
         local/usbrly08b-00023456-07

       To use the relays as power controllers on a power rail for
       another target, create instances of
       :py:class:`ttbl.usbrly08b.pc`:

       .. code-block:: python

          ttbl.usbrly08b.pc("0023456", RELAYNUMBER)

       where *RELAYNUMBER* is 1 - 8, which matches the number of the
       relay etched on the board.

    """
    if target_name_prefix == None:
        target_name_prefix = "usbrly08b-" + serial_number
    for relay in range(1, 9):
        name = "%s-%02d" % (target_name_prefix, relay)
        target = target_pdu_socket_add(
            name,
            ttbl.usbrly08b.pc(serial_number, relay),
            power = powered_on_start,
            # Always keep them on, unless we decide otherwise--we need
            # them to control other components
            tags = dict(
                idle_power_off = 0, idle_poweroff = 0, # COMPAT
                idle_power_fully_off = 0
            ))
        target.disable("")


def ykush_targets_add(ykush_serial, pc_url = None, powered_on_start = None):
    """Given the :ref:`serial number <ykush_serial_number>` for an YKUSH
    hub connected to the system, set up a number of targets to
    manually control it.

    - (maybe) one target to control the whole hub

    - One target per port *YKNNNNN-1* to *YKNNNNN-3* to control the three
      ports individually; this is used to debug powering up different
      parts of a target.

    .. code-block:: python

       ykush_targets_add("YK34567", "http://USER:PASSWD@HOST/4")

    yields::

      $ tcf list
      local/YK34567
      local/YK34567-1
      local/YK34567-2
      local/YK34567-3

    To use then the YKUSH hubs as power controllers, create instances of
    :py:class:`ttbl.pc_ykush.ykush`:

    .. code-block:: python

       ttbl.pc_ykush.ykush("YK34567", PORT)

    where *PORT* is 1, 2 or 3.

    :param str ykush_serial: USB Serial Number of the hub
      (:ref:`finding <ykush_serial_number>`).

    :param str pc_url: (optional) Power Control URL

     - A DLPWS7 URL (:py:class:`ttbl.pc.dlwps7`), if given, will create a
       target *YKNNNNN* to power on or off the whole hub and wait for it
       to connect to the system.

     - If *None* (default) no power control targets for the whole hub
       will be created. It will just be expected the hub is connected
       permanently to the system.

    :param bool powered_on_start: what to do with the power on the
      downstream ports:

      - *None*: leave them as they are

      - *False*: power them off

      - *True*: power them on

    **Bill of materials**

    - YKUSH hub and it's :ref:`serial number <ykush_serial_number>`

      Note the hub itself has no serial number, but an internal device
      connected to its downstream port number 4 does have the *YK34567*
      serial number.

    - a male to mini-B male cable for power

    - a USB brick for power

      - (optional) a DLWPS7 power switch to control the hub's power

      - or an always-on connection to a power plug

    - a male to micro-B male cable for upstream USB connectivity

    - an upstream USB B-female port to the server (in a hub or root hub)

    Note the *YKNNNNN* targets are always tagged *idle_poweroff = 0*
    (so they are never automatically powered off) but not
    *skip_cleanup*; the later would never release them when idle and
    if a recovery fails somewhere, then none would be able to
    re-acquire it to recover.

    """
    assert isinstance(ykush_serial, str)
    if pc_url != None:
        assert isinstance(pc_url, str)
    if powered_on_start != None:
        assert isinstance(powered_on_start, bool)

    # Now try to add the one that expects to find the USB device; this
    # can fail if the USB device doesn't show up for whichever reason
    pcl = []
    if pc_url:
        pcl.append(( "main", ttbl.pc.dlwps7(pc_url) ))
    pcl.append(( "usb-device-check",
                 ttbl.pc.delay_til_usb_device(serial = ykush_serial)))

    target = ttbl.test_target(ykush_serial)
    target.interface_add("power", ttbl.power.interface(*pcl))
    # Always keep them on, unless we decide otherwise--we need
    # them to control other components
    ttbl.config.target_add(target, tags = dict(
        idle_power_off = 0, idle_poweroff = 0, # COMPAT
        idle_power_fully_off = 0
    ))
    target.disable("")
    if powered_on_start:
        target.power.put_on(target, ttbl.who_daemon(), {}, {}, None)

    for i in [ 1, 2, 3]:
        target = ttbl.test_target("%s-%d" % (ykush_serial, i))
        target.interface_add(
            "power",
            ttbl.power.interface(ttbl.pc_ykush.ykush(ykush_serial, i)))
        # Always keep them on, unless we decide otherwise--we need
        # them to control other components
        ttbl.config.target_add(target, tags = dict(
            idle_power_off = 0, idle_poweroff = 0, # COMPAT
            idle_power_fully_off = 0
        ))
        target.disable("")
        if powered_on_start:
            target.power.put_on(target, ttbl.who_daemon(), {}, {}, None)
