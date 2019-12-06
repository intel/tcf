.. _server_deployment_guide:
.. _ttbd_guide_deployment:

=======================
Server deployment guide
=======================

Deploying *ttbd* is not complicated; it can grow as large as you need
it.

Bear in mind:

- Only Fedora is supported at this point; other distros should work,
  but we do not have resources to support them.

- Recent kernels are needed; when deployed in full force, ttbd puts a
  lot of stress on the USB bus and interfaces and it has uncovered
  bugs that are known to be fixed around Linux kernel > v4.5.

- Follow these instructions as verbatim as possible. The fixtures
  described here have been designed to maximize reliability and
  minimize false positives or negatives.

- There are security matters you :ref:`should consider
  <security_considerations>`

Bill of materials
=================

You will need the following depending on what hardware you plan to
test

- A Linux machine running Fedora >= v24 to run the ttbd server/s

  - plenty of USB ports

  - (optional) space to connect secondary USB cards to (:ref:`rationale
    <ttbd_cannot_find_ykush_serial>`)

  - USB hubs, externally powered, to provide upstream connectivity to
    the server's root USB ports

  - More than one network interface and network switches to
    interconnect the server with your power switches and targets
    (:ref:`rationale <separated_networks>`)

- Power control (to power targets up and down)

  - IP controlled AC power switch `Digital Logger Web Power Switches
    <http://www.digital-loggers.com/lpcfaqs.html>`_, for
    infrastructure, hubs and targets powered by AC

  - `YKush power-switching USB hubs
    <https://www.yepkit.com/products/ykush>`_, for hardware that is
    USB powered

  (other power switches are possible, but drivers need to be written
  for them)

- Miscelaneous cables (it is recommended to buy in bulk to avoid
  wasting time looking for them)

  * USB cables https://commons.wikimedia.org/wiki/File:Usb_connectors.JPG

    - A male to B male
    - A male to mini-B male
    - A male to micro-B male

  * M/M jumper `cables
    <https://www.adafruit.com/products/1957?gclid=CKSjy5mErc0CFYiVfgod1XkK7Q>`_

- USB `power bricks
  <https://en.wikipedia.org/wiki/AC_adapter#Use_of_USB>`_ (2ma) at
  least (mostly for powering the YKUSH hubs)

- USB serial terminal `adaptors
  <https://www.adafruit.com/products/954?&main_page=product_info&products_id=954>`_

- MCU boards (Arduino101, Quark C1000, Quark D2000, FRDM k64f, etc)

It is recommended to get extra spare components, for quick replacement
in case of failures.

.. _conventions:

Conventions
===========

To execute a *command* as a normal user we'll use::

  $ command ...

to execute a *comand* as super-user (loging in as root or using
*sudo*), we'll use::

  # command ...

Links will come in different flavours:

- example link to a :ref:`section <conventions>`
- example link to another :py:func:`section <conf_00_lib_pdu.dlwps7_add>`

.. _system_install:

Server installation
===================

.. include:: 03-server-setup-LL-system-install.rst

.. _install_tcf_server_rpms:

Install and setup the TCF software
==================================

The software is available as RPM packages with all the dependencies
(alternatively there are the *not recommended* :ref:`manual
installation steps <manual_install>`).

.. include:: 03-server-setup-LL-ttbd-install.rst

- ``--allowerasing`` is needed so conflicting packages (like
  *ModemManager*) are removed.

- Replace *-v0.11* with *-master* in the URL to get the development
  repository instead of the stable *v0.11* tree.

.. _ttbd_guide_install_default_config:

The default configuration brings up an instance called *production*
with a number of virtual networks, QEMU-based targets suitable for
running the Zephyr OS on different architecture (*qz*\*) and Cloud
versions of Fedora Core (*qlf\**). Any local user can access.

Directories for the instance are */etc/ttbd-production* for
configuration, */var/run/ttbd-production* for state and
*/var/cache/ttbd-production* for temporary data.

.. include:: 03-server-setup-LL-ttbd-post-install.rst

From here you can (optional):

- :ref:`allow the server to be used remotely <ttbd_config_bind>`
- :ref:`configure LDAP authentication <ttbd_config_auth_ldap>`
- :ref:`configure simple authentication <ttbd_config_authdb>`
- :ref:`configure more instances <ttbd_config_multiple_instances>`

As well, you can add

- physical targets, such as :ref:`MCUs <ttbd_config_mcus>`
- read on for information about :ref:`networking targets
  <ttbd_config_vlan>`, default QEMU targets for running :ref:`Zephyr
  OS <ttbd_config_qemu_zephyr>`.

.. _ttbd_config_vlan:

Target networking
-----------------

The default configuration in
``/etc/ttbd-production/conf_05_default.py`` is setup to create two IP
networks for virtual (and physical) targets to intercomunicate with
each other::

  $ tcf list | grep nw
  local/nwa                 # 192.168.61.0/24 fc00::61:0/112
  local/nwb                 # 192.168.62.0/24 fc00::62:0/112

QEMU targets defined in the default configuration are made
members of each subnetwork. The server host is always the *.1*
address.

Note that for for two targets to be able to do IP communication, the
network target has to be powered-on before the targets.

More networks can be added by creating configuration files
*/etc/ttbd-production/conf_NAME.py* containing:

.. code-block:: python

   ttbl.config.target_add(
       ttbl.tt.tt_power('nwd', vlan_pci()),
       tags = dict(
           ipv4_addr = '192.168.63.1',
           ipv4_prefix_len = 24,
       )
   )
   ttbl.config.targets['NAME'].tags['interfaces'].append('interconnect_c')

Be sure to not assign conflicting IP blocks, or IP blocks that route
to the public internet or intranet--in the example the convention is
followed to use network *192.168.X.0/24*, where X is 61 for *a* in *nwa*, 62 for
*b* in *nwb*, 63 for *c* in *nwc*, etc ... following ASCII values and
keeping network names short (otherwise system tools might start
cutting them off).

The default configuration creates *virtual* networks for the virtual
machines to communicate. It is possible to bridge a physical device by
connecting it to the system and indicating so to the
configuration. See :py:class:`conf_00_lib.vlan_pci` for setup details, but
it basically consists on:

- connect a network interface to the server (USB or PCI); said network
  interface shall be connected to a network switch to which all the
  physical targets we want to interconnect are also connected

- find the network interface's MAC address (using something like *ip
  link show*)

- add the tag *mac_addr* with said address to the network to which
  said interface is to be connected; for example the network *nwc* of
  the example:

  .. code-block:: python

     ttbl.config.target_add(
         ttbl.tt.tt_power('nwc', vlan_pci()),
         tags = dict(
             mac_addr = "a0:ce:c8:00:18:73",
             ipv4_addr = '192.168.63.1',
             ipv4_prefix_len = 24,
         )
     )
     ttbl.config.targets['NAME'].tags['interfaces'].append('interconnect_c')

  or for an existing network (such as the configuration's default
  *nwa*):

  .. code-block:: python

     # eth dongle mac 00:e0:4c:36:40:b8 is assigned to NWA
     ttbl.config.targets['nwa'].tags_update(dict(mac_addr = '00:e0:4c:36:40:b8'))

- for each target that is connected to said network, report it as part
  of the network *nwc*:

  .. code-block:: python

     ttbl.config.targets['TARGETNAME-NN'].tags_update({ 'ipv4_addr': "192.168.10.130" },
                                                      ic = 'nwc')

- the network switch itself can be also power switched; if you
  connect it, for example to a Digital Loggers Web Power Switch 7
  named *spX* on port *N*, you can can add

  .. code-block:: python

     ttbl.config.targets['nwc'].pc_impl.append(
         ttbl.pc.dlwps7("http://admin:1234@spX/M"))

  thus, when powering up the network *nwc*, the last step will be to
  power up the network switch, and when powering it down, the first
  step done will be to power it off.

Be aware of the following when doing networking with TCF:

- you can configure any number of targets to a TCF network, as long as
  you configure your IP space accordingly.

  Recommended space assignment (and the one followed by default) is:

  - .1: is the server
  - .2 - .10: Virtual Linux machines
  - .30 - .45: Virtual Zephyr machines
  - .100 - .254: Real HW targets

  likewise, target naming will go long ways on making it easy to
  identify which targets are in which networks. It is recommended to
  assign a number to each targets that matches the last nibble of
  their IP (v4/v6) address and append the letter of the network they
  are in, for example:

  - a101-32a: is an Arduino 101, IP 192.168.10.132 in *nwa*
  - same70-54b: is 192.168.11.154 in *nwb*

- a network will own the physical network interface **exclusively**
  (in fact, it will even rename it)

- a single testcase execution will use a network in an exclusive way,
  thus if your networks are composed of many independent targets,
  there might be low reutilization. You might be off creating smaller
  networks to improve paralellism.

  However, you can create targets Ta1, Ta2 and Ta3 from *nwa* in a
  testcase (including *nwa*) and target Ta4 (without netwokring) in
  another one. What cannot be shared is the *nwa* interconnect target.

- a network switch can be shared amongst many networks, but this will
  introduce noise that can alter test results. Not recommended unless
  the switch can split LANs.

- a test will try to run in many different ways in the same network

  For example, if your test allocates three targets A, B and C and
  there are seven T1-T7 available, it will try to run in different
  assignment permutations:

  === === ===
  A   B   C
  === === ===
  T1  T2  T3
  T1  T3  T2
  T2  T3  T1
  ...
  ...
  === === ===

  how the targets are picked depends on what the test is asking for,
  but TCF is trying to ensure maximum coverage, so it might pick up
  way more combinations than you expect. Use the *mode* paramater
  to :func:`tcfl.tc.target` in the testcase to indicate how each
  target shall be picked. Targets for which you have no interest in
  doing coverage shall be selected as *mode='any'*, while the ones you
  want to make sure all types are covered shall be set as
  *mode='one-per-type'*.

  Use the ``-P`` command line to limit how many permutations you want
  *tcf run* to go with.

.. _ttbd_config_qemu_zephyr:

Configure QEMU Zephyr OS targets
--------------------------------

The default installation provies a list of QEMU-based targets that are
suitable for Zephyr OS development; they are defined in
``/etc/ttbd-production/conf_07_zephyr.py`` (you can add more or less as
you please modifying said file).

Now, ``tcf list`` should show, after you login::

  # tcf list | grep ^qz
  local/qz30a-x86
  local/qz30b-x86
  local/qz30c-x86
  ...
  local/qz39c-arm
  local/qz40a-nios2
  ..
  local/qz45a-riscv32
  ...

Output may vary based on configuration, but there targets called *qz*
(for QEMU Zephyr), five for each supported architecture (x86, ARM,
NiosII, RiscV32).  Test cases may be run against these targets now as
explained :ref:`here <tcf_run_automating_intro>`, but in a nutshell,
running as a local user (never root!!), we ask TCF to run the *Hello
World* Zephyr OS sample in all the different available targets::

  $ git clone http://github.com/zephyrproject-rtos/zephyr zephyr.git
  $ cd zephyr.git
  $ export ZEPHYR_BASE=$PWD
  $ tcf run -v /usr/share/tcf/examples/test_zephyr_hello_world.py
  PASS1/bfgv	/usr/share/tcf/examples/test_zephyr_hello_world.py#_test @local/qz32c-x86:x86: build passed
  PASS1/r7rf	/usr/share/tcf/examples/test_zephyr_hello_world.py#_test @local/qz46a-riscv32:riscv32: build passed
  PASS1/3opq	/usr/share/tcf/examples/test_zephyr_hello_world.py#_test @local/qz44b-nios2:nios2: build passed
  PASS1/qyjy	/usr/share/tcf/examples/test_zephyr_hello_world.py#_test @local/qz36a-arm:arm: build passed
  PASS1/bfgv	/usr/share/tcf/examples/test_zephyr_hello_world.py#_test @local/qz32c-x86:x86: evaluation passed
  PASS1/qyjy	/usr/share/tcf/examples/test_zephyr_hello_world.py#_test @local/qz36a-arm:arm: evaluation passed
  PASS1/r7rf	/usr/share/tcf/examples/test_zephyr_hello_world.py#_test @local/qz46a-riscv32:riscv32: evaluation passed
  PASS1/3opq	/usr/share/tcf/examples/test_zephyr_hello_world.py#_test @local/qz44b-nios2:nios2: evaluation passed
  PASS0/	toplevel @local: 4 tests (4 passed, 0 failed, 0 blocked, 0 skipped) - passed

Here it is saying that for each target, it built the test image and
then ran the steps in the test script
``/usr/share/tcf/examples/test_zephyr_hello_world.py``, that builds
the Zephyr OS sample in ``samples/hello_world``, all of them
evaluating succesfully, so the ran was considered a sucess (*PASS*).

.. _ttbd_config_qemu:

Configure QEMU targets
----------------------

QEMU targets can be configured to boot a VM with 


Configure physical test targets and power switches
--------------------------------------------------

Everything in *ttbd* is a test target; they need to be added by
creating Python objects that represent them in the configuration
files. Helper functions have been created to simplify the process.

Power switches (PDUs) are used to build power rails to power on or off the
different test targets and other infrastructure components

Create a configuration file
``/etc/ttbd-production/conf_10_targets.py`` and start adding
configuration statements as described in the links below:

- :ref:`PDUs / power switches <conf_00_lib_pdu>`:
  
  - :py:func:`Digital Loggers Web Power Switch 7
    <conf_00_lib_pdu.dlwps7_add>` PDUs / wall-power switches
    
  - :py:func:`Raritan EMX
    <conf_00_lib_pdu.raritan_emx_add>` based PDUs  / wall-power
    switches
    
  - :py:func:`YKUSH USB power switches <conf_00_lib_pdu.ykush_targets_add>`
    USB data/power switchable hub
    
  - :py:func:`Devantech USB-RLY08B USB controlled relays
    <conf_00_lib_pdu.usbrly08b_targets_add>`

- to add targets for just controlling power to something, see
  :ref:`these instructions<tt_power>`
- :ref:`physical Linux servers <ttbd_config_phys_linux>` boards

.. _ttbd_config_mcus:

MCU boards supported by default require :ref:`different fixtures
<conf_00_lib_mcu>`, for example:

- :py:func:`Arduino 101 <conf_00_lib_mcu.arduino101_add>` boards
- :py:func:`Arduino Due <conf_00_lib_mcu.arduino2_add>` boards
- :py:func:`Atmel SAM e70 <conf_00_lib_mcu.sam_xplained_add>` boards
- :py:func:`FRDM k64f <conf_00_lib_mcu.frdm_add>` boards
- :py:func:`STM32 / Nucleo <conf_00_lib_mcu.stm32_add>` boards
- :py:func:`Quark C1000 <conf_00_lib_mcu.quark_c1000_add>` boards
- :py:func:`Quark D2000 <conf_00_lib_mcu.mv_add>` boards
- :py:func:`Synopsis EMSK <conf_00_lib_mcu.emsk_add>` boards
- :py:func:`TinyTILEs <conf_00_lib_mcu.tinytile_add>` boards

.. include:: 03-server-setup-LL-boards.rst

There are other ways they can be fixtured and you are welcome to add
configuration scripts to support them and new hardware.

Each target you add can be healhchecked with, for a basic
functionality check::

  $ tcf healthcheck TARGETNAME
  Acquiring
  ...
  Power is reported correctly as 1
  power test passed
  Releasing
  Released
  TARGETNAME: healthcheck completed

Note this concludes the server installation process; the sections that
follow are configuration examples.

.. _ttbd_config_phys_linux:

Configure physical Linux (or other) targets
-------------------------------------------

There are multiple ways a Linux target can be connected as a target to
a TCF server. However, dependending on the intended use, different
configuration steps can be followed:


- A Linux target can be setup to :ref:`just power on and off
  <tt_linux_simple>`.

  This provides no control over the OS installed in the target

- A Linux target can be setup to boot off a read-only live filesystem
  (to avoid modifications to the root filesystem) following
  :ref:`these steps <ttbd_config_phys_linux_live>`.

  Serial access to a console can be provided and through it networking
  can be configured.

- A PC-class machine can be setup so that via the control of a
  Provisioning OS, it can be imaged to partition disks or install
  whichever operating systems in the disks.

  This allows testcases to start by ensuring the machine is properly
  imaged to a well known setup before starting.

  POS imaging can allow for very fast deployment times (below 1
  minute) to fresh OS versions. It requires a more complex setup that
  depends on the characteristics of the machines to support and it is
  described :ref:`here <pos_setup>`.

Configuring things that get plugged to the targets
--------------------------------------------------

A target can declare there are things that are connected to it and
that the user might decide to plug or unplug from the command line
(see :ref:`connecting things <connecting_things>`).

For implementing this, you need:

- a target
- a thing (which is also a target)
- a plugger, which is the driver that implements the actual physical
  act of plugging one target into another, implementing the interface
  defined in :class:`ttbl.thing_plugger_mixin`.

For this, the target to which the thing is connected has to be
properly configured; if you are coonecting a *THINGNAME* using method
*METHODNAME*, in your ``conf_10_targets.py`` you would have:

.. code-block:: python

   sometarget_add('TARGETNAME' ...)
   ttbl.config.targets['TARGETNAME'].thing_add(
       'THINGNAME', someplugger(ARG1, ARG2...))

A plugger, such as :class:`ttbl.usbrly08b.plugger` and its
associated physical setup (a USBRLY08b and the cables properly
connected) is what allows the physical act of switching. Another
example of a plugger would be one that talks to QEMU to route to the
VM guest a USB device plugged to the server.

As the things are also target, in a script you need to request both so
they are owned by the user and then you can plug them with::

.. code-block:: python

   def eval(self, target, thing):
     ...
     target.thing_plug(thing)
     ...

As well, in order to make it easy for testcases to locate them and get
them assign, it make sense to declare an interconnect that takes both
of them, so the target assigner will group them.

For example, if *TARGET0* is an MCU that implements a USB device that
we connect to *TARGET1* and we want to exercise plugging and
unplugging it, in the ``conf_10_target.py`` file, we would add:

.. code-block:: python

   ttbl.config.interconnect_add(
       ttbl.test_target('usb__TARGET1__TARGET0"),
       ic_type = 'usb__host__device')

   SOMETARGET_add('TARGET0'...)
   ttbl.config.targets['TARGET0'].add_to_interconnect('usb__TARGET1__TARGET0')

   SOMETARGET_add('TARGET1'...)
   ttbl.config.targets['TARGET1'].add_to_interconnect('usb__TARGET1__TARGET0')
   ttbl.config.targets['TARGET1'].add_thing(
       'TARGET0', ttbl.usbrly08b.plugger("SERIALNUMBER", 0))


Best practices for server setup
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. _bp_naming_targets:

Naming targets
~~~~~~~~~~~~~~

Name targets after the type of the target, a monotonically unique
number and in some cases, letters that indicate to which networks the
target is connected::

  TYPE-NNx

- *TYPE*: a short name that describes the type of the target

  e.g.: *arduino2*, *minnowboard*, *arduino101*, *nuc*, *genericpc*...

- *NN* is a number that is increased monotonically for each target
  added to the infrastructure, even of different types:

  * this allows using the number to assign addresses in different
    spaces (eg: MAC addresses, IPv4 and IPv6, etc)

  * if there are multiple servers in an infrastructure, it is
    recommended they all share the same number space, so that when a
    target is moved from one server to another or networks are shared
    between servers, the addresses don't conflict

- *x*: if the target is connected to a network, append the network name
  (it is also recommended to name networks *nwx*, where x is a single
  character)--if the target is connected to multiple targets, multiple
  letters can be specified if so chosen.

examples:

  - *arduino101-03*
  - *minnowboard-04r*
  - *nuc-58a*

.. _bp_naming_networks:

Naming Networks
~~~~~~~~~~~~~~~

It helps to name networks with a single letter, e.g.: *nwa*,
*nwb*...*nwr*:

- it's a short name and it will fit into network interface names, etc.

- it allows to use the letter's ASCII value for naming the IP address
  ranges and MAC address generation. E.g. *a* in *nwa* is 97, 0x61
  which can be used to define networks::

    ipv6_addr: fc00::61:0/112
    ipv4_addr: 192.168.97.0/24

- as well, as described :ref:`in the previous section
  <bp_naming_targets>` it allows to add a single letter to a target
  name to indicate which network it is connected to.

Configuration Example 1
^^^^^^^^^^^^^^^^^^^^^^^

To add an FRDM k64f board and an Arduino101 board + Flyswatter 2 JTAG,
along with a couple of YKush hubs to control them and a DLWPS7 power switch,
we'd use the following in ``/etc/ttbd-production/conf_10_targets.py``:

.. code-block:: python

   dlwps7_add("sp1")

   ykush_targets_add("YK20954", "http://admin:1234@sp1/3")
   ykush_targets_add("YK20946", "http://admin:1234@sp1/2")

   frdm_add(name = "frdm-06",
            serial_number = "0240022636c40e6e000000000000000000000000cb1df3d6",
            ykush_serial = "YK20946",
            ykush_port_board = 3)

   arduino101_add(name = "arduino101-02",
                  fs2_serial = "FS20000",
                  serial_port = "/dev/tty-arduino101-02",
                  ykush_url = "http://admin:1234@sp1/2",
                  ykush_serial = "YK20954")

This would also require some *udev* configuration that is explained in
the setup instructions for the :ref:`MCU boards <ttbd_config_mcus>` (and
detailed :ref:`here <usb_tty>`) to generate the right
``/dev/tty-NAME`` device links; in short, add to
``/etc/udev/rules.d/90-ttbd.rules``::

  SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "0240022636c40e6e000000000000000000000000cb1df3d6", \
    SYMLINK += "tty-frdm-06"

  SUBSYSTEM == "tty", \
    ENV{ID_PATH} == "*2:1.0", \
    PROGRAM = "/usr/bin/usb-sibling-by-serial YK20954", \
    SYMLINK += "tty-arduino101-02"

(reread *udev* configuration with udevadm ``control --reload-rules``).

.. note:: Note your serial numbers for the boards and YKush hubs will
          be different for your setup; see :ref:`here for boards
          <ttbd_config_mcus>` and :ref:`here for YKush hubs
          <ykush_serial_number>` of how to find them.

Likewise with the definition of the *sp1*. Add to ``/etc/hosts``::

  192.168.x.y	sp1

Where *192.168.x.y* is the IP address of the power switch.

As well, setup the proper hardware connections:

- *sp1* connected to the wall and it's network cable to the server,
  name *sp1* defined in ``/etc/hosts`` to the right IP address (see
  :py:func:`here <conf_00_lib_pdu.dlwps7_add>` for details)
- *YK20954*\'s power connected to the power switch *sp1*\'s socket #3
- *YK20956*\'s power connected to the power switch *sp1*\'s socket #2
- *frdm-06* USB cable connected to *YK20946*\'s port #3
- *arduino101-2* connected as described :py:func:`here
  <conf_00_lib_mcu.arduino101_add>`

Restart the server and a listing should show::

  $ tcf list
  local/sp1-1
  local/sp1-2
  local/sp1-3
  local/sp1-4
  local/sp1-5
  local/sp1-6
  local/sp1-7
  local/sp1-8
  local/YK20954
  local/YK20954-base
  local/YK20954-1
  local/YK20954-2
  local/YK20954-3
  local/YK20946
  local/YK20946-base
  local/YK20946-1
  local/YK20946-2
  local/YK20946-3
  local/arduino101-02
  local/frdm-06

Giving you targets to individually control each power switch's ports
plus the targets themselves.

Once a target is configured in, run a quick healthcheck::

  $ tcf healthcheck arduino101-02
  Acquiring
  Acquired
  Powering off
  Powered off
  Querying power status
  Power is reported correctly as 0
  Powering on
  Powered on
  Querying power status
  Power is reported correctly as 1
  power test passed
  Releasing
  Released
  arduino101-02: healthcheck completed

.. only:: mastermode

   Galileo Gen2
   ^^^^^^^^^^^^

   FIXME: incomplete

   **Bill of materials**

   * A Galileo2 board
   * power brick connected to *spX/Y*
   * USB FTDI cable connected to *usbhubN*

   Needs udev configuration to setup permissions. Follow
   :ref:`usb_tty_path`.


   Minnowboards
   ^^^^^^^^^^^^

   FIXME: incomplete

   **Bill of materials**

   * A MinnowboardMax
   * power connected to *spX/Y*
   * USB serial port connected to *usbhubN*; same udev configuration as
     Galileo Gen2
   * network cable connected to *nsX*

   Needs udev configuration to setup permissions. Follow
   :ref:`usb_tty_path`.


   .. admonition:: FIXME

      place links to configuration of network infrastructure (switches
      and interfaces)

.. _pos_setup:

Configuring Provisioning OS support
-----------------------------------

POS allows for a method to provision/flash/image certain devices using
a :mod:`Provisioning OS <tcfl.pos>` which is faster than imaging using
standard OS installation procedures. See the :ref:`architectural
refence <provisioning_os>`

POS needs, depending on the setup:

- targets able to UEFI boot via PXE to the network

  these targets will boot POS over PXE, with the root filesystem in an
  NFS drive

- a network interconnect to which the target(s) have to be connected,
  as well as the server

- a server acting as an rsync server to provide images to flash into
  targets; this is usually the same as the TTBD server (for
  simplicity) the interconnect between the rsync server and the
  targets needs to be at least 1Gbps to provide the needed performance
  that will allow to flash a 1G image in less than one minute on a
  normal harddrive.

  Optional: use glusterfs to coordinate the distribution of images to
  all the servers FIXME

- A server providing:

  - the POS linux kernel and initrd over HTTP for targets to boot from
    PXE
  - the POS image over NFS root for the targets to boot

  this can also be the TTBD server for simplicity and scalability.

Current known POS limitations:

- Only UEFI PXE boot supported, others device specific
- Single partitioning scheme supported

Refer to :ref:`the examples <examples_pos>` section for usage.

POS: Server setup
^^^^^^^^^^^^^^^^^

These instructions are for Fedora only; other distributions have not
been tested yet, shall be similar.

1. Install the auxiliary package ``ttbd-pos`` to bring in all the
   required dependencies::

     # dnf install -y --allowerasing ttbd-pos

2. Ensure your user is member of the ``ttbd`` group::

     # usermod -aG ttbd YOURUSER

   you will have to re-login for changes to take effect.

3. Configure an image repository (FIXME: add in glusterfs steps); we
   choose ``/home/ttbd/images`` but any other location will do::

     # install -o ttbd -g ttbd -m 2775 -d \
         /home/ttbd \
         /home/ttbd/images/tcf-live/ \
         /home/ttbd/images/tcf-live/x86_64 \
         /home/ttbd/public_html /home/ttbd/public_html/x86_64

4. Disable the firewall (FIXME: do not require this)::

     # systemctl stop firewalld
     # systemctl disable firewalld

5. Enable required services:

   - Apache: to serve the POS Linux kernel and initrd::

       # tee /etc/httpd/conf.d/ttbd.conf <<EOF
       Alias "/ttbd-pos" "/home/ttbd/public_html"

       <Directory "/home/ttbd/public_html">
       AllowOverride FileInfo AuthConfig Limit Indexes
       Options MultiViews Indexes SymLinksIfOwnerMatch IncludesNoExec
       Require method GET POST OPTIONS
       </Directory>
       EOF

     SELinux requires setting a few more things to enable serving from
     home directories::

       # setsebool -P httpd_enable_homedirs true
       # chcon -R -t httpd_sys_content_t /home/ttbd/public_html

     Test this is working::

       # systemctl restart httpd
       # echo "it works" > /home/ttbd/public_html/testfile

     from any other browser try to access
     http://YOURSERVERNAME/ttbd-pos/testfile and check it succeeds.

     FIXME: move ttbd.conf file as a config file in package
     ``ttbd-pos``.

   - NFS server: provides the POS root filesystem.

     Ensure UDP support is enabled (not for RHEL >= 7.6)::

       # sed -i 's|RPCNFSDARGS="|RPCNFSDARGS="--udp |' /etc/sysconfig/nfs
       # systemctl enable nfs-server
       # systemctl restart nfs-server

POS: deploy PXE boot image to HTTP and NFS server locations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Currently the Provisioning OS is implemented with a derivative of
Fedora Linux.

.. warning:: these steps are meant for an x86-64 platform and it has
             to be run in such. Steps for x86 (32-bits) or other
             platforms need to be documented.

.. _generate_tcf_live_iso:

a. Generate TCF-live on the fly::

     $ /usr/share/tcf/live/mk-liveimg.sh

   Note:

   - needs sudo access; will ask for your password to gain *sudo* when
     needed

   - downloads ~300 packages to create a Fedora-based image, so make
     sure you have a good connection and plenty of disk space free.

     It will be cached in directory *tcf-live* so next time you run
     less needs to be downloaded.

     To use a closer mirror to you or add extra RPM repositories::

       $ mdkir tcf-live
       $ cat > tcf-live/tcf-live-mirror.ks <<EOF
       # Repos needed to pick up TCF internal RPMs
       repo --name=EXTRAREPO --baseurl=https://LOCATION/SOMEWHERE
       # internal mirrors for getting RPMs
       repo --name=fedora-local --cost=-100 --baseurl=http://MIRROR/fedora/linux/releases/$releasever/Everything/$basearch/os/
       repo --name=updates-local --cost=-100 --baseurl=http://MIRROR/fedora/linux/releases/$releasever/Everything/$basearch/os/
       EOF

b. Extract the root file system from the ISO image to the
   ``/home/ttbd/images`` directory; this is where the NFS server
   will read-only root serve it from and also we'll be able to use
   it to flash targets::

     $ /usr/share/tcf/tcf-image-setup.sh /home/ttbd/images/tcf-live/x86_64/ tcf-live/tcf-live.iso
     I: loop device /dev/loop0
     NAME      MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
     loop0       7:0    0  419M  0 loop
     └─loop0p1 259:0    0  419M  0 loop
     mount: /home/LOGIN/tcf-image-setup.sh-XEqBHG/iso: WARNING: device write-protected, mounted read-only.
     I: mounted /dev/loop0p1 in tcf-image-setup.sh-XEqBHG/iso
     I: mounted tcf-image-setup.sh-XEqBHG/iso/LiveOS/squashfs.img in tcf-image-setup.sh-XEqBHG/squashfs
     I: mounted tcf-image-setup.sh-XEqBHG/squashfs/LiveOS/ext3fs.img in tcf-image-setup.sh-XEqBHG/root
     I: created tcf-live, transferring
     I: tcf-live: diffing verification
     File tcf-image-setup.sh-XEqBHG/root/./dev/full is a character special file while file tcf-live/.
     /dev/full is a character special file
     ...
     File tcf-image-setup.sh-XEqBHG/root/./dev/zero is a character special file while file tcf-live/.
     /dev/zero is a character special file
     I: unmounting tcf-image-setup.sh-XEqBHG/root
     I: unmounting tcf-image-setup.sh-XEqBHG/squashfs
     I: unmounting tcf-image-setup.sh-XEqBHG/iso
     I: unmounting tcf-image-setup.sh-XEqBHG/root
     umount: tcf-image-setup.sh-XEqBHG/root: not mounted.

   (most of those warning messages during verification can be ignored)

c. Make the kernel and initrd for POS available via Apache for
   PXE-over-HTTP and PXE-over-TFTP booting:

   i. Copy the kernel::

        # ln /home/ttbd/images/tcf-live/x86_64/boot/vmlinuz-* \
            /home/ttbd/public_html/x86_64/vmlinuz-tcf-live

   ii. Regenerate the *initrd* with nfs-root support, as the initrd
       generated does not have nfs-root enabled (FIXME: figure out
       the configuration to enable it straight up)::

         # dracut -v -H --kver $(ls /home/ttbd/images/tcf-live/x86_64/lib/modules) \
                -k /home/ttbd/images/tcf-live/x86_64/lib/modules/* \
               --kernel-image /home/ttbd/images/tcf-live/x86_64/boot/vmlinuz-* \
               --add-drivers "igb i40e e1000e r8169 virtio_net ftdi_sio" \
               -m "nfs base network kernel-modules kernel-network-modules" \
               /home/ttbd/public_html/x86_64/initramfs-tcf-live

       .. warning:: ``--kver`` is needed to not default to the kernel
                    version of the system running the co/mmand.
                    ``-H`` is needed to ensure a generic initrd that
                    works with multiple machines is created.

       needed drivers:
       
       - *ftdi_sio* drivers for FTDI USB serial ports
       - *igb*, *e1000e*, *i40e*: Intel adapters
       - *r8169* for some Realtek network cards
       - *virtio* for running under QEMU

       Note if you run as non-root (not using *sudo* or *su*) *dracut*
       will fail to generate the initrd properly due to some bugs.
         
   iii. Make everything readable to the public::

          # chmod a+rX -R /home/ttbd/public_html
          # chcon -R -t httpd_sys_content_t /home/ttbd/public_html

   iv. Copy the POS boot material to the TFTP directory::

         # install -m 2775 -o ttbd -g ttbd -d \
              /var/lib/tftpboot/ttbd-production/efi-x86_64
         # install -m 0644 -o ttbd -g ttbd /home/ttbd/public_html/x86_64/* \
              /var/lib/tftpboot/ttbd-production/efi-x86_64

       This allows targets to get the boot kernel/initrd over TFTP.

   Ensure those two files work by pointing a browser to
   http://YOURSERVERNAME/ttbd-pos/ and verifying they can be downloaded.

d. Make the POS root image available over NFS as read-only (note we
   only export those images only, not all)::

     # tee /etc/exports.d/ttbd-pos.exports <<EOF
     /home/ttbd/images/tcf-live/x86_64 *(ro,no_root_squash)
     EOF
     # systemctl reload nfs-server

   Verify the directory is exported::

     $ showmount -e SERVERNAME
     Export list for localhost:
     /home/ttbd/images/tcf-live/x86_64 *

.. _ttbd_pos_deploying_images:

POS: Deploying other images
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Image naming follows the format::

 DISTRO:SPIN:VERSION:SUBVERSION:ARCH

it is valid to leave any fields empty except for the DISTRO and ARCH
fields; valid examples::

  - clear:live:25930::x86_64
  - yocto:core-image-minimal:2.5.1::x86_64
  - fedora:live:29::x86_64
  - fedora:workstation:29::x86_64

The script ``/usr/share/tcf/tcf-image-setup.sh`` will take an image
from different OSes and extract it so it can be used to be flashed via
POS; for example:

- Clearlinux::

    $ wget https://download.clearlinux.org/releases/25930/clear/clear-25930-live.img.xz
    $ /usr/share/tcf/tcf-image-setup.sh /home/ttbd/images/clear:live:25930::x86_64 clear-25930-live.img.xz

- Yocto::

    $ wget http://downloads.yoctoproject.org/releases/yocto/yocto-2.5.1/machines/genericx86-64/core-image-minimal-genericx86-64.wic
    $ /usr/share/tcf/tcf-image-setup.sh yocto:core-image-minimal:2.5.1::x86_64 core-image-minimal-genericx86-64.wic

- (others coming)

Otherewise, an image can be extracted and or setup manually and it
consists of:

- the full root filesystem that shall be deployed

  Note it is important to respect not only the user/group and
  permisisons of each file, but also any extended attributes (ACLs,
  SELinux contexts, etc). Look at the insides of
  ``tcf-image-setup.sh`` for a methodology to do it.

- basic configuration so it starts a serial console on the serial
  device/s given in the kernel command line

- (recommended) remove the root password, so it needs no extra steps
  to login (after all, this is not protecting any infrastructure or
  access, since the target will be in a silo; as well, the cleartext
  password would have to be in a test script so it can be entered, so
  it would make no sense).

.. _ttbd_pos_network_config:

POS: Configuring networks
^^^^^^^^^^^^^^^^^^^^^^^^^

For a target to be able to be provisoned via POS, it needs to be
connected to an (IPv4) network to the server, which provides DHCP,
TFTP and HTTP (for PXE), NFS and rsync support.

TTBD will start the rsync and DHCP servers on demand, TFTP, HTTP and
NFS services have been enabled by installing the *ttbd-pos* package.

To enable the system to know what to use, the network the target is
connected to (which is another target) needs to have certain
configuration settings.

**The quick way**

The quick way to add a POS capable network is using the POS
configuration library function :func:`pos_target_add
<conf_00_lib_pos.nw_pos_add>`.

Add a network called *nwa*; the physical network interface with MAC
*c0:3f:d5:67:af:99* will be used to connect to the network:

.. code-block:: python

   nw_pos_add('a', mac_addr = 'c0:3f:d5:67:af:99')

if you want to add services, to the network, you can calculate the IP
addresses it is going to be assigned based on the network name (*a*)
using :func:`conf_00_lib_pos.nw_indexes`

.. code-block:: python

   x, y, _ = nw_indexes('a')

   interconnect.tags_update(dict(
       # implemented by tinyproxy running in the server
       ftp_proxy = "http://192.%d.%d.1:8888" % (x, y),
       http_proxy = "http://192.%d.%d.1:8888" % (x, y),
       https_proxy = "http://192.%d.%d.1:8888" % (x, y),
   ))
  
by default the server is in *192.x.y.1* in that network, so if we
configure *tinyproxy* to serve on port 8888, the targets can access it
for proxy services.

See :ref:`more details <pos_network_config_details>` on network configuration.

POS: Configuring targets
^^^^^^^^^^^^^^^^^^^^^^^^

This example connects an Intel NUC5i5425OU called nuc-58 to the
network *nwa* so it can be flashed with POS.

**Overview**


**Bill of Materials**

- A PC-class machine (the *target*):

  - able to UEFI boot over the network

  - serial port available (and it's cable) or USB port available (and
    USB-to-USB null modem cable or similar)

  - power cable

  - network cable

  - Monitor, keyboard and mouse for initial configuration, will be
    disconnected once setup.

- a free outlet on a PDU unit supported by TCF

**Setup the test target fixture**

1. connect the target to a normal power outlet, monitor, keyboard and
   mouse

2. start the target, go into the BIOS setup menu

   a. navigate to the *boot* section:

      - set UEFI to boot off network IPv4 as primary boot source

      - remove any other boot methods (TCF will tell it to boot to
        local disk via the network boot) [USB, Optical, etc]

      - disable unlimited amount of netwbot boots

   b. navigate to the *Power* section and enable *Power on after AC
      power loss / power failure*.

      This ensures that the target will power on when power is applied
      via the power controller instead of waiting for the user to
      press the power button.

   c. From the top level menu or advanced config menus, find the MAC
      address of the target.

      Alternative, this also can be found by booting any OS in the
      target (eg: a Linux installation image).

3. Power off the target, disconnect the power, keep the monitor,
   keyboard and mouse for now


**Connecting the target**

1. connect the target's power cable to the port selected in the PDU
   (for this example our PDU is a :class:`DLWPS7 <ttbl.pc.dlwps7>`
   named *sp6* and we'll use port #6)

   Label the cable with the target's name.

2. connect the serial cable to the target and the other end to the
   server.

   Find :ref:`the serial number <find_usb_info>` of the USB serial
   port connected to the server. We will need it later.


**Configuring the system for the target**

1. Pick up a :ref:`target name <bp_naming_targets>`.

   For this example, we picked ``nuc5-58a``, the number 58 is then
   used to decide the IP address that is assigned to this target
   (192.168.97.58) on network *a* (as :ref:`defined
   above<ttbd_pos_network_config_numbers>`).

2. Configure *udev* to add a name for the serial device for the
   target's serial console USB cable so it can be easily found at
   ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
   <usb_tty_serial>` using the cable's *serial number* we found in
   the previous section.

3. Add a configuration block to the configuration file
   ``/etc/ttbd-production/conf_10_targets.py``

   .. code-block:: python

      pos_target_add("nuc5-63b", "c0:3f:d5:69:1a:c7",
                     "sp7/6", "sda", "1:10:40:20", 'ttyUSB0',
                     target_type_long = "Intel NUC5i5425OU")

   :func:`pos_target_add <conf_00_lib_pos.pos_target_add>` does all
   the low level details of arranging for the target to be configured
   properly; some setups might need other arrangements, for which the
   individual steps might have to be unfolded--look at the source of
   the configuration library (in your server configuration directory)
   for details.
               
Restart the server and verify *nuc-58a* works as expected::

  # systemctl restart ttbd@production
  # tcf healthcheck nuc-58a

will try to power on and off the target; observe in the monitor if the
target is coming up or not. FIXME: diagose issues

**Smoke test**

From another machine (or within the server) with TCF installed, flash
the POS image itself in the system as an initial smoke test, using
``/usr/share/tcf/examples/test_pos_deploy.py``::

  $ IMAGE=tcf:live tcf run -vvvt 'nwa or nuc-58a' /usr/share/tcf/examples/test_pos_deploy.py

FIXME: this will fail now because we don't have the right regex to
catch tcf:live's root prompt (``[0-9]+ $``).

.. _pos_list_images:

List available images::

  $ tcf run /usr/share/tcf/examples/test_pos_list_images.py
  server10/nwa clear:live:25550::x86_64
  server10/nwa clear:live:25890::x86_64
  server10/nwa fedora:cloud-base:28::x86_64
  server10/nwa yocto:core-minimal:2.5.1::x86_64
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:06.635452) - passed

and flash other images by passing the right image name to the IMAGE
environment variable::

  $ IMAGE=clear:live:25890::x86_64 tcf run -vvvt 'nwa or nuc-58a' /usr/share/tcf/examples/test_pos_deploy.py


(of course, this assumes that image is available in your system; see
:ref:`how to add more <ttbd_pos_deploying_images>`).

.. _pos_network_config_details:
     
POS networks: harder details, adding extra services
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

a. A network is usually defined, in a ``conf_10_NAME.py``
   configuration file in ``/etc/ttbd-production`` (or any other
   instance) with a block such as:

   .. code-block:: python

      ttbl.config.interconnect_add(
          ttbl.tt.tt_power('nwa',
                           [
                               vlan_pci()
                           ]),
          tags = dict(
              ipv6_addr = 'fc00::61:1',
              ipv6_prefix_len = 112,
              ipv4_addr = '192.168.97.1',
              ipv4_prefix_len = 24,
          ),
          ic_type = "ethernet"
      )

   This defines a target representing an interconnect, called ``nwa``,
   of type *ethernet* (vs let's way WiFi). It is sometimes also called
   a NUT (Network Under Test). This network defines a single power
   control implementation, a :class:`conf_00_lib.vlan_pci` which will
   upon power on/off create/teardown the internal piping for virtual
   macines to be able to access said interconnect.

   Note how we have assigned IP addresses to the network, which will
   be the ones the server connection to it will have. By setting the
   prefix lengths, we also know the network mask.

   .. _ttbd_pos_network_config_numbers:

   Note also the nomenclature: *nwa*, letter *a* )(ASCII 97 / 0x61)
   which we use in the *network* part of the IP address (*192.168.97.x*
   and *fc00::61:x*).

b. Since we know we are using a physical network, in the form of one of
   the server's network interfaces connected to a network switch, we
   ask ttbd to use said network interface by adding a *mac_addr* tag
   describing the interface's MAC address:

   .. code-block:: python

           ....
           tags = dict(
               mac_addr =  'a0:ce:c8:00:18:73',
               ipv6_addr = 'fc00::61:1',
               ....

   Now, powering on or off the *nwa* target will bring up or
   down the interface.

c. If we want to control the power to the network switch, we would add a
   power control implementation to the target's power rail after
   ``vlan_pci()``:

   .. code-block:: python

          ...
          ttbl.tt.tt_power('nwa',
                           [
                               vlan_pci(),
                               ttbl.pc.dlwps7('http://admin:1234@sp5/8')
                           ]),
          ...

   .. warning:: Do not do this if you are using a shared switch split
                in multiple port groups, as you would power off the
                switch for other users while they need it.

   This is assuming we have the power to the network switch connected
   to socket #5 of a :class:`Digital Weblogger Switch
   7<ttbl.pc.dlwps7>` which the server can reach through the
   infrastructure network as hostname *sp5* (see :py:func:`configuring
   Digital Loggers Web Power Switch 7 <conf_00_lib_pdu.dlwps7_add>`) --
   note other power switches can be used too as long as a driver class
   is available for them.

d. Now we need to add DHCP support to the network; we do that by using
   a :class:`DHCP power control interface <ttbl.dhcp.pci>`, that will
   configure and start a DHCP daemon when the *nwa* interconnect is
   powered on, or stop it when is powered off:

   .. code-block:: python

          ...
          ttbl.tt.tt_power('nwa',
                           [
                               vlan_pci(),
                               ttbl.pc.dlwps7('http://admin:1234@sp5/8'),
                               ttbl.dhcp.pci("192.168.97.1", "192.168.97.0", 24,
                                             "192.168.97.10", "192.168.97.20"),
                               ttbl.dhcp.pci("fc00::61:1", "fc00::61:0", 112,
                                             "fc00::61:2", "fc00::61:fe", ip_mode = 6),
                           ]),
          ...

   note how we added one for IPv4 and one for IPv6; they both specify
   the server address as .1, net 'network" as .0, the prefix len and
   the range of IP addresses than can be served (note these addresses
   will be hardcoded--the same IP address will be given always to the
   same target based on the target's configuration -- more below).

e. POS can do very fast and efficient imaging by using rsync; the
   images installed in ``/home/ttbd/images`` will be exported by an rsync
   server daemon controlled by a :class:`rsync power control interface
   <ttbl.rsync.pci>`, that will configured to start/stop an rsync daemon when
   the *nwa* interconnect is powered on/off:

   .. code-block:: python

          ...
          ttbl.tt.tt_power('nwa',
                           [
                               vlan_pci(),
                               ttbl.pc.dlwps7('http://admin:1234@sp5/8'),
                               ttbl.dhcp.pci("192.168.97.1", "192.168.97.0", 24,
                                             "192.168.97.10", "192.168.97.20"),
                               ttbl.dhcp.pci("fc00::61:1", "fc00::61:0", 112,
                                             "fc00::61:2", "fc00::61:fe", ip_mode = 6),
                               ttbl.rsync.pci("192.168.97.1", 'images',
                                              '/home/ttbd/images'),
                           ]),
          ...

   this rsync server binds to IP address 192.168.97.1, exports a
   read-only rsync share called *images* which is anything in
   */home/ttbd/images*

f. Optionally, you can implement port redirection.

   The NUT *nwa* is completely isolated from any other networks in
   your server (unless you have munged with the forwarding rules in
   the server).

   However, with the :class:`socat power control implementation
   <ttbl.socat.pci>`, you can configure one or more port redirections
   -- like a proxy, so that oyur test systems have controlled access
   to the outside world:

   .. code-block:: python

          ...
          ttbl.tt.tt_power('nwa',
                           [
                               vlan_pci(),
                               ttbl.pc.dlwps7('http://admin:1234@sp5/8'),
                               ttbl.dhcp.pci("192.168.97.1", "192.168.97.0", 24,
                                             "192.168.97.2", "192.168.97.254"),
                               ttbl.dhcp.pci("fc00::61:1", "fc00::61:0", 112,
                                             "fc00::61:2", "fc00::61:fe", ip_mode = 6),
                               ttbl.rsync.pci("192.168.97.1", 'images',
                                              '/home/ttbd/images'),
                               ttbl.socat.pci('tcp', "192.168.97.1", 8080,
                                              'http_proxy.mydomain.com', 8080)
                               ttbl.socat.pci('tcp', "192.168.97.1", 1080,
                                              'socks_proxy.mydomain.com', 1080)
                           ]),
          ...


g. Finally, we need to specify a few more tags that the clients and
   server will use to drive operation:

   .. code-block:: python

          ...
          tags = dict(
              ipv6_addr = 'fc00::61:1',
              ipv6_prefix_len = 112,
              ipv4_addr = '192.168.97.1',
              ipv4_prefix_len = 24,

              ftp_proxy = "http://192.168.97.1:8080",
              http_proxy = "http://192.168.97.1:8080",
              https_proxy =  "http://192.168.97.1:8080",

              # Provisioning OS support to boot off PXE on nfs root
              pos_http_url_prefix = "http://192.168.97.1/ttbd-pos/%(bsp)s/",
              pos_nfs_server = "192.168.97.1",
              pos_nfs_path = "/home/ttbd/images/tcf-live/%(bsp)s",
              pos_rsync_server = "192.168.97.1::images",
          ),
          ic_type = "ethernet"
      )

All together, it shall look like:

.. code-block:: python

   import ttbl.config
   import ttbl.tt
   import ttbl.dhcp
   import ttbl.rsync
   import ttbl.socat

   # Delete existing definition of the 'nwa' target created by the
   # default initialization
   del ttbl.config.targets['nwa']

   ttbl.config.interconnect_add(
       ttbl.tt.tt_power(
           'nwa',
           [
               vlan_pci(),
               # optional, to power control the network switch
               #ttbl.pc.dlwps7('http://admin:1234@sp5/8'),
               ttbl.dhcp.pci("192.168.97.1", "192.168.97.0", 24,
                             "192.168.97.10", "192.168.97.20"),
               ttbl.dhcp.pci("fc00::61:1", "fc00::61:0", 112,
                             "fc00::61:2", "fc00::61:fe", ip_mode = 6),
               ttbl.rsync.pci("192.168.97.1", 'images',
                              '/home/ttbd/images'),
               ttbl.socat.pci('tcp', "192.168.97.1", 8080,
                              'http_proxy.mydomain.com', 8080),
               ttbl.socat.pci('tcp', "192.168.97.1", 1080,
                              'socks_proxy.mydomain.com', 1080),
           ]),
       tags = dict(
           ipv6_addr = 'fc00::61:1',
           ipv6_prefix_len = 112,
           ipv4_addr = '192.168.97.1',
           ipv4_prefix_len = 24,

           ftp_proxy = "http://192.168.97.1:8080",
           http_proxy = "http://192.168.97.1:8080",
           https_proxy =  "http://192.168.97.1:8080",

           # Provisioning OS support to boot off PXE on nfs root
           pos_http_url_prefix = "http://192.168.97.1/ttbd-pos/%(bsp)s/",
           pos_nfs_server = "192.168.97.1",
           pos_nfs_path = "/home/ttbd/images/tcf-live/%(bsp)s",
           pos_rsync_server = "192.168.97.1::images",
       ),
       ic_type = "ethernet"
   )

Restart the server and verify *nwa* works as expected::

  # systemctl restart ttbd@production

Diagnose issues reported by systemd in :ref:`troubleshooting
<systemd_tips_diagnosis>`

Now the configuration is loaded and you can run::

  $ tcf list -vv nwa
  https://localhost:5000/ttb-v1/targets/nwa
    disabled: False
    ftp_proxy: http://192.168.97.1:8080
    fullid: local/nwa
    http_proxy: http://192.168.97.1:8080
    https_proxy: http://192.168.97.1:8080
    id: nwa
    ipv4_addr: 192.168.97.1
    ipv4_prefix_len: 24
    ipv6_addr: fc00::61:1
    ipv6_prefix_len: 112
    pos_http_url_prefix: http://192.168.97.1/ttbd-pos/%(bsps)s/
    pos_nfs_path: /home/ttbd/images/tcf-live/%(bsp)s
    pos_nfs_server: 192.168.97.1
    pos_rsync_server: 192.168.97.1::images
    powered: False
    things: []
    type: ethernet

Note some values from the *tcf list* output were omitted for clarity.

Check it can power on and off::

  $ tcf acquire nwa
  $ tcf power-off nwa
  $ tcf power-on nwa
  $ tcf power-off nwa


.. include:: 03-server-setup-LL-post-steps.rst
