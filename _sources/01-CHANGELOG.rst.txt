.. _changelog:

=================
TCF release v0.11
=================

This release of TCF brings several new important high level features,
such as:

- multiple targets: allows a testcase to request multiple test targets
  where to execute (versus previous limitation of none or one)

- interconnected targets: allows a testcase to request targets that
  are interconnected, related or grouped (eg: targets in an IP
  network, or in Bluetooth or Wifi radio proximity)

- things: allows the specification and control of things that can be
  plugged to a target (eg: a USB device,

- default to use Python as a testcase programming language, providing
  a well defined :class:`API <tcfl.tc.tc_c>` to interact with the
  system running the testcase and report information and to manipulate
  the :class:`targets <tcfl.tc.target_c>`.

- many improvements to the documentation, with the addition of
  step-by-step guides for :ref:`installation <quickstart>`,
  :ref:`testcase <tcf_guide_tests>` :ref:`development <tcf_guide_test_training>`, etc

- Support for more hardware components and boards

On the server side, the installation has become easier (specially when
using RPMs), as the daemon runs now under a dedicated user (*ttbd*)
which is given the right privileges so *udev* configuration is
minimized

- *ttbd*, the server

  - the daemon is now run under the ttbd user (versus the *nobody*
    user previously); thus, *udev* configuration is simplified (rules
    might have to be updated if upgrading an existing system). The
    daemon is also given the *dialout* and *root* groups and
    *CAP_NET_ADMIN* so almost no changes are needed in most systems.

  - the location for virtual images has been set to */var/lib/ttbd*,
    the *$HOME* for user *ttbd*

  - support for:
    - Zephyr Xtensa and RISCv32 targets
    - Zephyr DFU targets
    - USB controlled relays for power control
    - QEMU-based Linux VMs as targets

  - IP port tunneling from client to target

  - multiple robustness improvements to the console logger

- client:

  - Main language for testcases is now Pyton, old .tc format
    discontinued; ability to refer to targets with well defined API
    extensible via plugins to support new server-side interfaces

  - introduce concept of App Builders, plugins that know how to build
    applications for different environment and deploy them to targets
    for you (sketch, Zephyr)

  - builds in temporary directories

  - logical expression language to select targets and testcases

  - multiple examples on networking, zephyr, sketch, linux

  - report drivers for logfiles and MongoDB databases

  - test case drivers for Python-based test cases, Zephyr samples and
    Sanity check

  - much improved interactive console-write mode

- add multiple self-test unit test cases

- add multiple scripts: generating virtual images, fixing FRDM k64f
  boards

Known issues:

- random (<1%) failures to detect a string from the console

- interconnect selection limited to a single interconnect

- the standard output of the Zephyr kbuild commands is lost (the lines
  that print *CC some/file/name.o*); this is a weird interaction with
  the Make jobserver that hasn't been fully triaged (TCF/run re-runs
  itself under a make jobserver to improve paralellism). To
  workaround, invoke *tcf --no-make-jobserver run OTHERARGS*).
