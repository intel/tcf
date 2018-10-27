====
APIs
====

*TCF run*: testcase API and target manipulation during testcases
================================================================

.. automodule:: tcfl.tc

Test library (utilities for testcases)
--------------------------------------

.. automodule:: tcfl.tl

Extensions to :class:`tcfl.tc.target_c` types
---------------------------------------------

.. automodule:: tcfl.target_ext_console
.. automodule:: tcfl.target_ext_broker_files
.. automodule:: tcfl.target_ext_debug
.. automodule:: tcfl.target_ext_images
.. automodule:: tcfl.target_ext_power
.. automodule:: tcfl.target_ext_shell
.. automodule:: tcfl.target_ext_ssh
.. automodule:: tcfl.target_ext_tags
.. automodule:: tcfl.target_ext_tcob
.. automodule:: tcfl.target_ext_tunnel
.. automodule:: tcfl.target_ext_buttons

*TCF run* Application builders
------------------------------

.. automodule:: tcfl.app
.. automodule:: tcfl.app_zephyr
.. automodule:: tcfl.app_sketch
.. automodule:: tcfl.app_manual


*TCF run* report drivers
-------------------------

.. automodule:: tcfl.report
.. automodule:: tcfl.report_mongodb
                
*TCF* client configuration
==========================

.. automodule:: tcfl.config

*TCF* client internals
======================

.. automodule:: tcfl
.. automodule:: tcfl.expecter
.. automodule:: tcfl.ttb_client
.. automodule:: tcfl.util

.. automodule:: tcfl.tc_zephyr_sanity

                
Target metadata
===============

Each target has associated a list of metadata, some of them common to
all targets, some of them driver or target type specific that you can
get on the command line with ``tcf list -vvv TARGETNAME``

Common metadata
---------------
        
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
  
  - *ipv4_addr* (str): IPv4 Address (32bits, DDD.DDD.DDD.DDD, where
    DDD are decimal integers 0-255) that will be assigned to this
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

                
*ttbd* Configuration API for targets
====================================

.. automodule:: conf_00_lib
   :members:
   :undoc-members:

*ttbd* Configuration API
========================

.. automodule:: ttbl.config
   :members:

*ttbd* internals
================

.. automodule:: ttbl
.. automodule:: ttbl.fsdb

Target types drivers
--------------------

.. automodule:: ttbl.tt
.. automodule:: ttbl.tt_qemu
.. automodule:: ttbl.flasher

User access control and authentication
--------------------------------------

.. automodule:: ttbl.user_control
.. automodule:: ttbl.auth_ldap
.. automodule:: ttbl.auth_localdb
.. automodule:: ttbl.auth_party

Console Management Interface
----------------------------

.. autoclass:: ttbl.test_target_console_mixin
.. automodule:: ttbl.cm_serial
.. automodule:: ttbl.cm_loopback
.. automodule:: ttbl.cm_logger

Debugging Interface
-------------------

.. autoclass:: ttbl.tt_debug_mixin

Power Control Interface
-----------------------

.. autoclass:: ttbl.tt_power_control_mixin
.. automodule:: ttbl.pc
.. automodule:: ttbl.pc_ykush
.. automodule:: ttbl.usbrly08b


Miscelaneous
~~~~~~~~~~~~

.. automodule:: ttbl.target

Common helper library
---------------------

.. automodule:: commonl.expr_parser

.. automodule:: commonl.tcob
