====
APIs
====

*TCF run*: testcase API and target manipulation during testcases
================================================================

.. automodule:: tcfl.tc

Test library (utilities for testcases)
--------------------------------------

.. automodule:: tcfl.tl
.. automodule:: tcfl.biosl

Provisioning/deploying/flashing PC-class devices with a Provisioning OS
-----------------------------------------------------------------------

.. automodule:: tcfl.pos
.. automodule:: tcfl.pos_uefi
.. automodule:: tcfl.pos_multiroot

Other target interfaces
-----------------------

.. automodule:: tcfl.target_ext_buttons
.. automodule:: tcfl.target_ext_capture
.. automodule:: tcfl.target_ext_console
.. automodule:: tcfl.target_ext_debug
.. automodule:: tcfl.target_ext_fastboot
.. automodule:: tcfl.target_ext_images
.. automodule:: tcfl.target_ext_input
.. automodule:: tcfl.target_ext_ioc_flash_server_app
.. automodule:: tcfl.target_ext_power
.. automodule:: tcfl.target_ext_shell
.. automodule:: tcfl.target_ext_ssh
.. automodule:: tcfl.target_ext_store
.. automodule:: tcfl.target_ext_things
.. automodule:: tcfl.target_ext_tunnel

*TCF run* Application builders
------------------------------

.. automodule:: tcfl.app
.. automodule:: tcfl.app_zephyr
.. automodule:: tcfl.app_sketch
.. automodule:: tcfl.app_manual


*TCF run* report drivers
-------------------------

See :ref:`report reference <tcf_guide_report_driver>`.

                
*TCF* client configuration
==========================

.. automodule:: tcfl.config

*TCF* client internals
======================

.. automodule:: tcfl
.. automodule:: tcfl.ttb_client

.. automodule:: tcfl.tc_zephyr_sanity
.. automodule:: tcfl.tc_clear_bbt
.. automodule:: tcfl.tc_jtreg

                
Target metadata
===============

Each target has associated a list of metadata, some of them common to
all targets, some of them driver or target type specific that you can
get on the command line with ``tcf list -vvv TARGETNAME`` or in a test
script in the dictionary :data:`tcfl.tc.target_c.rt` (for Remote
Target), or more generally in the keywor dictionary
:data:`tcfl.tc.target_c.kws`.

Metada is specified:

- in the server's read only configuration by setting tags to the
  target during creation of the :class:`ttbl.test_target` object, by
  passing a dictionary to :func:`ttbl.config.target_add`

  >>> ttbl.config.target_add(
  >>>     ttbl.tt.tt_serial(....),
  >>>     tags = {
  >>>         'linux': True,
  >>>         ...
  >>>         'pos_capable': True,
  >>>         'pos_boot_interconnect': "nwb",
  >>>         'pos_boot_dev': "sda",
  >>>         'pos_partsizes': "1:20:50:15",
  >>>         'linux_serial_console_default': 'ttyUSB0'
  >>>     },
  >>>     target_type = "Intel NUC5i5425OU")

  or by calling :func:`ttbl.test_target.tags_update` on an already
  created target

  >>> ttbl.test_target.get('nwb').tags_update({
  >>>     'mac_addr': '00:50:b6:27:4b:77'
  >>> })

- during runtime, from the client with *tcf
  property-set*::

    $ tcf property-set TARGETNAME PROPERTY VALUE

  or calling :func:`tcfl.tc.target_c.property_set`:

  >>> target.property_set("PROPERTY", "VALUE")

Common metadata
---------------

- *bios_boot_time* (int): approx time in seconds the system takes to
  boot before it can be half useful (like BIOS can interact, etc).

  Considered as zero if missing.

- *id* (str): name of the target

- *fullid* (str): Full name of the target that includes the server's
  short name (*AKA*); *SERVERAKA/ID*.

- *TARGETNAME* (bool) True

- *bsp_models* (list of str): ways in which the BSPs in a target
  (described in the *bsps* dictionary) can be used.

  If a target has more than one BSP, how can they be combined? e.g:

  - BSP1
  - BSP2
  - BSP1+2
  - BSP1+3

  would describe that in a target with three BSPs, 1 and 2 can be used
  individually or the target can operate using 1+2 or 1+3 together
  (but not 3+2 or 1+2+3).

- *bsps* (dictionary of dictionaries keyed by BSP name): describes
  each BSP the target contains

  A target that is capable of computing (eg: an MCU board vs let's
  say, a toaster) would describe a BSP; each BSP dictionary contains
  the following keys:

  - *cmdline* (str): [QEMU driver] command line used to boot a QEMU
    target

  - *zephyr_board* (str): [Zephyr capable targets] identifier to use
    for building Zephyr OS applications for this board as the *BOARD*
    parameter to the Zephyr build process.

  - *zephyr_kernelname* (str): [Zephyr capable targets] name of the
    file to use as Zephyr image resulting from the Zephyr OS build
    process.

  - *sketch_fqbn* (str): [Sketch capable targets] identifier to use
    for building Arduino applications for this board.

  - *sketch_kernelname* (str): [Sketch capable targets] name of the
    file to use as image resulting from the Sketch build process.

- *disabled* (bool): True if the target is disabled, False otherwise.

- *fixture_XYZ* (bool): when present and True, the target exposes
  feature (or a test fixture) named XYZ

- *interconnects* (dictionary of dictionaries keyed by interconnect
  name):

  When a target belongs to an interconnect, there will be an entry
  here naming the interconnect. Note the interconnect might be in
  another server, not necessarily in the same server as the target is.

  Each interconnect might have the following (or other fields) with
  address assignments, etc:

  - *bt_addr* (str): Bluetooth Address (48bits HH:HH:HH:HH:HH:HH,
    where HH are two hex digits) that will be assigned to this target
    in this interconnect (when describing a Bluetooth interconnect)

  - *mac_addr* (str): Ethernet Address (48bits HH:HH:HH:HH:HH:HH,
    where HH are two hex digits) that will be assigned to this target
    in this interconnect (when describing ethernet or similar
    interconnects)

  - *ipv4_addr* (str): IPv4 Address (32bits, *DDD.DDD.DDD.DDD*, where
    *DDD* are decimal integers 0-255) that will be assigned to this
    target in this interconnect

  - *ipv4_prefix_len* (int): length in bits of the network portion of
    the IPv4 address

  - *ipv6_addr* (str): IPv6 Address (128bits, standard ipv6 colon
    format) that will be assigned to this target in this interconnect

  - *ipv4_prefix_len* (int): length in bits of the network portion of
    the IPv6 address

- *idle_poweroff* (int): seconds the target will be idle before the
  system will automatically power it off (if 0, it will never be
  powered off).

- *interfaces* (list of str): list of interface names

- *interfaces_names* (str): list of interface names as a single string
  separated by spaces

- *mutex* (str): who is the current owner of the target

- *owner* (str): who is the current owner of the target

- *path* (str): path where the target state is maintained

- *things* (list of str): list of names of targets that can be
  plugged/unplugged to/from this target.

- *type* (str): type of the target

Interface specific metadata
---------------------------

- *consoles* (list of str): [console interface] names of serial
  consoles supported by the target

- *debug-BSP-gdb-tcp-port* (int): [debug interface] TCF port on which
  to reach a GDB remote stub for the given BSP (depending on target
  capability).

- *images-TYPE-QUALIFIER* (str): [imaging interface] File name of
  image that was flashed of a given type and qualifier; eg
  *images-kernel-arc* with a value of
  */var/cache/ttbd-production/USERNAME/somefile.elf* was an image
  flashed as a kernel for architecture ARC).

- *openocd.path* (str): [imaging interface] path of the OpenOCD
  implementation being used

- *openocd.pid* (unsigned): [imaging interface] PID of the OpenOCD
  process driving this target

- *openocd.port* (unsigned): [imaging interface] Base TCP port where
  we can connect to the OpenOCD process driving this target

- *powered* (bool): [power control interface] True if the target is
  powered up, False otherwise.

- *power_state* (bool): [power control interface] 'on' if the target
  is powered up, 'off' otherwise. (FIXME: this has to be unified with
  *powered*)

Driver / targe type specific metadata
-------------------------------------

- *hard_recover_rest_time* (unsigned): [ttbl.tt.tt_flasher driver,
  OpenOCD targets] time the target has to be kept off when
  power-cycling to recover after a failed reset, reset halt or reset
  after power-cycle when flashing.

  When the flasher (usually OpenOCD) cannot make the target comply,
  the driver will power cycle it to try to get it to a well known
  state.

- *linux* (bool): True if this is a target that runs linux

- *quark_se_stub* (bool): FIXME: DEPRECATED

- *qemu_bios_image* (str): [QEMU driver] file name used for the
  target's BIOS (depending on configuration)

- *qemu_ro_image* (str): [QEMU driver] file name used for the target's
  read-only image (depending on configuration)

- *qemu-image-kernel-ARCH* (str): [QEMU driver] file used as a kernel to
  boot a QEMU target (depending on configuration)

- *qemu-cmdline-ARCH* (str): [QEMU driver] command line used to launch
  the QEMU process implementing the target (depending on configuration)

- *ifname* (str): [QEMU driver / SLIP] interface created to hookup the
  SLIP networking tun/tap into the vlan to connect to external
  networks or other VMs [FIXME: make internal]

- *slow_flash_factor* (int): [[ttbl.tt.tt_flasher driver, OpenOCD
  targets] amount to scale up the timeout to flash into an OpenOCD
  capable target. Some targets have a slower flashing interface and
  need more time.

- *tunslip-ARCH-pid* (int): [QEMU driver] PID of the process
  implementing tunslip for a QEMU target.

- *ram_megs* (int): Megs of RAM supported by the target

- *ssh_client* (bool): True if the target supports SSH

Provisioning OS specific metadata
---------------------------------

- *linux_serial_console_default*: which device **the target** sees as
  the system's serial console connected to TCF's first console.

  If *DEVICE* (eg: ttyS0) is given, Linux will be booted with the
  argument *console=DEVICE,115200*.

- *linux_options_append*: string describing options to append to a
  Linux kernel boot command line.

.. _pos_capable:

- *pos_capable*: dictionary describing a target as able to boot into a
  Provisioning OS to perform target provisioning.

  Keys are the same as described in :data:`tcfl.pos.capability_fns`
  (e.g: *boot_to_pos*, *boot_config*, etc)

  Values are only one of each of each second level keys in the
  :data:`tcfl.pos.capability_fns` dictionary (e.g.: *pxe*, *uefi*...).

  This indicates the system which different methodologies have to be
  used for the target to get into Provisioning OS mode, configure
  bootloader, etc.

.. _pos_http_url_prefix:

- *pos_http_url_prefix*: string describing the prefix to send for
  loading a Provisoning OS kernel/initramfs. See :ref:`here
  <pos_boot_http_tftp>`.

  Python's ``%(NAME)s`` codes can be used to substitute values from
  the target's tags or the interconnect's.

  Example:

  .. code-block:: python

     pos_http_url_prefix = "http://192.168.97.1/ttbd-pos/%(bsp)s/"

  ``bsp`` is common to use as the images for an architecture won't
  work for another. ``bsp`` is taken from the target's tag ``bsp``. If
  not present, the first BSP (in alphabetical order) declared in the
  target tags ``bsps`` will be used.

.. _pos_image:

- *pos_image*: string describing the image used to boot the target in
  POS mode; defaults to *tcf-live*.

  For each image, in the server, :data:`ttbl.pxe.pos_cmdline_opts
  <ttbl.pxe.pos_cmdline_opts>` describes the kernel options to append
  to the kernel image, which is expected to be found in
  *http://:data:`POS_HTTP_URL_PREFIX
  <pos_http_url_prefix>`/vmlinuz-POS_IMAGE* for HTTP boot. For other
  boot methods (eg: TFTP) the driver shall copy the files around as
  needed.

.. _pos_partscan_timeout:

- *pos_partscan_timeout*: maximum number of seconds we wait for a
  partition table scan to show information about the partition table
  before we consider it is really empty (some HW takes a long time).

  This is used in :func:`tcfl.pos.fsinfo_read
  <tcfl.pos.extension.fsinfo_read>`.
  
.. _pos_reinitialize:

- *pos_reinitialize*: when set to any value, the client provisioning
  code understands the boot drive for the target has to be
  repartitioned and reformated before provisioning::

    $ tcf property-set TARGET pos_reinitialize True
    $ tcf run -t TARGETs <something that deploys>

.. _roles_required:

- *_roles_required*: list of strings describing roles.

  In order to be able to see or use this targer, a user must have
  been granted one of the roles in the list by the authentication
  module. See :ref:`access control <target_access_control>`.

.. _roles_excluded:

- *_roles_excluded*: list of strings describing roles.

  In order to be able to see or use this targer, a user must have
  *not* been granted one of the roles in the list. See :ref:`access
  control <target_access_control>`.
  
.. _uefi_boot_manager_ipv4_regex:

- *uefi_boot_manager_ipv4_regex*: allows specifying a Python regular
  expression that describes the format/name of the UEFI boot entry
  that will PXE boot off the network. For example:

  >>> ttbl.test_target.get('PC-43j').tags_update({
  >>>     'uefi_boot_manager_ipv4_regex': 'UEFI Network'
  >>> })

  Function (tcfl.pos_uefi._efibootmgr_setup()* can use this if the
  defaults do not work :func:`target.pos.deploy_image()
  <tcfl.pos.extension.deploy_image>` reports::

    Cannot find IPv4 boot entry, enable manually

  even after the PXE boot entry has been enabled manually.

  Note this will be compiled into a Python regex.

*ttbd* HTTP API
===============

.. include:: 09-api-http.rst

.. _ttbd_conf_api:
             
*ttbd* Configuration API for targets
====================================

.. automodule:: conf_00_lib
   :members:
   :undoc-members:
.. automodule:: conf_00_lib_capture
   :members:
   :undoc-members:
.. automodule:: conf_00_lib_mcu
   :members:
   :undoc-members:
.. automodule:: conf_00_lib_mcu_stm32
   :members:
   :undoc-members:
.. automodule:: conf_00_lib_pos
   :members:
   :undoc-members:
.. automodule:: conf_00_lib_pdu
   :members:
   :undoc-members:
.. automodule:: conf_06_default

*ttbd* Configuration API
========================

.. automodule:: ttbl.config
   :members:

*ttbd* internals
================

.. automodule:: ttbl

.. _target_access_control:

User access control and authentication
--------------------------------------

TTBD provides for means for users to authenticate themselves to the
system and to decide which users can see and use what targets.

TTBD, however, does not implement the authentication; that is
delegated to :class:`authentication drivers <ttbl.authenticator_c>`
which can authenticate a user agains :class:`LDAP
<ttbl.auth_ldap.authenticator_ldap_c>`, a :class:`local database
<ttbl.auth_userdb.driver>`, any remote service, etc.

When a user succesfully *logs in*, the authentication drivers, based
on their configuration, provide a list of roles the user has, each
represented by a string, which minimally are defined as:

- *user*: standard label for all users; if an authentication system
   doesn't grant access to the *user* role, the user has no access to
   the system.

- *admin*: super users with access to everything; note *amdins* can
  always see/use all target, disregarding any exclude rules.

any other roles are deployment specific and can be used to control
access to targets, since the targets can define tags
:ref:`roles_required <roles_required>` and :ref:`roles_excluded
<roles_excluded>` to require users have a role or to exclude users
with a certain role. For example, a target defined such as:

>>> ttbl.config.target_add(
>>>     ttbl.test_target(TARGETNAME),
>>>     tags = dict(
>>>         ...
>>>         _roles_required = [ 'lab7', 'wizard' ],
>>>         _roles_excluded = [ 'guest' ],
>>>  ))

would allow any user with is given the *lab7* or *wizard* role by the
authentication system and would exclude anyone with the role *guest*.

.. automodule:: ttbl.user_control
.. automodule:: ttbl.auth_ldap
.. automodule:: ttbl.auth_localdb
.. automodule:: ttbl.auth_party
.. automodule:: ttbl.auth_userdb

Console Management Interface
----------------------------

.. automodule:: ttbl.console
.. automodule:: ttbl.lantronix

Debugging Interface
-------------------

.. autoclass:: ttbl.debug

Power Control Interface
-----------------------

.. automodule:: ttbl.power
.. automodule:: ttbl.pc
.. automodule:: ttbl.ipmi
.. automodule:: ttbl.raritan_emx
.. automodule:: ttbl.apc
.. automodule:: ttbl.pc_ykush
.. automodule:: ttbl.usbrly08b

Daemons that can be started in the server as part of a power rail:

.. automodule:: ttbl.dhcp
.. automodule:: ttbl.dnsmasq
.. automodule:: ttbl.qemu
.. automodule:: ttbl.openocd
.. automodule:: ttbl.rsync
.. automodule:: ttbl.socat

Other interfaces
----------------

.. automodule:: ttbl.buttons
.. automodule:: ttbl.capture
.. automodule:: ttbl.debug
.. automodule:: ttbl.fastboot
.. automodule:: ttbl.images
.. automodule:: ttbl.ioc_flash_server_app
.. automodule:: ttbl.things


Common helper library
---------------------

.. automodule:: commonl

.. automodule:: commonl.expr_parser

.. include:: 09-api-LL-extras.rst
