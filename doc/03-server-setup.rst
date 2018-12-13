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
- example link to another :py:func:`section <conf_00_lib.dlwps7_add>`

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
  OS <ttbd_config_qemu_zephyr>` and :ref:`Linux
  <ttbd_config_qemu_linux>`.

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

.. _ttbd_config_qemu_linux:

Configure QEMU Linux targets
----------------------------

The default installation provies a list of QEMU-based targets that are
suitable for running Fedora, Clear Linux and other Linux cloud OS;
they are defined in ``/etc/ttbd-production/conf_06_default.py`` (you
can add more or less in your configuration files).

However, TCF provides a kickstarter configuration setup that generates
a Fedora-based TCF Live ISO image to run Linux machines that:

 - are continuously recycled (upon boot, they are always a fresh
   reinstall)

 - have installed the RPMs you need (look into
   :class:`conf_00_lib.tt_qemu_linux` for details on how to add more).

 - systemd networking is configured to work with TCF networks

 - works on VMs and physical machines

 - provide a serial console which autologs to root, TCF
   *console-read* and *console-write* commands can access the root
   console.

To generate the Linux image from a Fedora machine, you will need sudo
access::

  $ /usr/share/tcf/live/mk-liveimg.sh [OPTIONALPATHs]
  $ mv tcf-intel/tcf-intel.iso /var/lib/ttbd/

.. note::

   *OPTIONALPATHS* are paths to directories where to find extra
   configuration; read the documentaion on
   */usr/share/tcf/live/mk-liveimg.sh* for more information.

or download it

.. include:: 03-server-setup-LL-image-download.rst

Now, ``tcf list`` should show, after you login::

  # tcf list | grep ^ql
  ...
  locals/nwa
  locals/nwb
  locals/qlf04a
  locals/qlf04b
  locals/qlf05aH
  locals/qlf05bH
  ...

(output may vary based on configuration)

There are two test networks defined (*nwa*, *nwb*), *qlc* are Clear
Linux targets, *qlf* are Fedora. The number indicates the last part of
their IPv4 and IPv6 addresses. The letter *a* and *b* helps to tell
which network are they at. *H* at the end says they also have a NAT
connection to the server's upstream network connection.


Configure physical test targets and power switches
--------------------------------------------------

Everything in *ttbd* is a test target; they need to be added by
creating Python objects that represent them in the configuration
files. Helper functions have been created to simplify the process.

Power switches are used to build power rails to power on or off the
different test targets and other infrastructure components

Create a configuration file
``/etc/ttbd-production/conf_10_targets.py`` and start adding
configuration statements as described in the links below:

- :py:func:`Digital Loggers Web Power Switch 7
  <conf_00_lib.dlwps7_add>` wall-power switch.
- :py:func:`YKUSH USB power switches <conf_00_lib.ykush_targets_add>`
  USB data/power switchable hub
- :py:func:`Devantech USB-RLY08B USB controlled relays
  <conf_00_lib.usbrly08b_targets_add>`
- to add targets for just controlling power to something, see
  :ref:`these instructions<tt_power>`
- :ref:`physical Linux servers <ttbd_config_phys_linux>` boards

.. _ttbd_config_mcus:

MCU boards supported by default require different fixtures which are
described below:

- :py:func:`Arduino 101 <conf_00_lib.arduino101_add>` boards
- :py:func:`Arduino Due <conf_00_lib.arduino2_add>` boards
- :py:func:`Atmel SAM e70 <conf_00_lib.sam_xplained_add>` boards
- :py:func:`FRDM k64f <conf_00_lib.frdm_add>` boards
- :py:func:`STM32 / Nucleo <conf_00_lib.stm32_add>` boards
- :py:func:`Quark C1000 <conf_00_lib.quark_c1000_add>` boards
- :py:func:`Quark D2000 <conf_00_lib.mv_add>` boards
- :py:func:`Synopsis EMSK <conf_00_lib.emsk_add>` boards
- :py:func:`TinyTILEs <conf_00_lib.tinytile_add>` boards

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

Configure physical Linux targets
--------------------------------

There are multiple ways a Linux target can be connected as a target to
a TCF server. However, dependending on the intended use, different
configuration steps can be followed:


- A Linux target can be setup to :ref:`just power on and off
  <tt_linux_simple>`.
       
- A Linux target can be setup to boot off a read-only live filesystem
  (to avoid modifications to the root filesystem) following
  :ref:`these steps <ttbd_config_phys_linux_live>`.

  Serial access to a console can be provided and through it networking
  can be configured.


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

- *TYPE*: name that describes the type of the target

  e.g.: *arduino2*, *minnowboard*, *genericpc*...

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

  - *arduino101-03*:
  - *minnowboard-04r*


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
  :py:func:`here <conf_00_lib.dlwps7_add>` for details)
- *YK20954*\'s power connected to the power switch *sp1*\'s socket #3
- *YK20956*\'s power connected to the power switch *sp1*\'s socket #2
- *frdm-06* USB cable connected to *YK20946*\'s port #3
- *arduino101-2* connected as described :py:func:`here
  <conf_00_lib.arduino101_add>`

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
