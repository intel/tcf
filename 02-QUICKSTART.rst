.. _quickstart:

============
 Quickstart
============

.. _install_tcf_client:

1. Install the client software from source::

     $ git clone http://github.com/intel/tcf tcf.git
     $ cd tcf.git
     $ pip2 install --user -r requirements.txt	# dependencies
     $ python2 setup.py install --user
     $ cd zephyr
     $ python2 setup.py install --user

   You can also run *tcf* from the :ref:`source directory
   <tcf_run_from_source_tree>`.
     
   .. include:: doc/02-client-setup-LL-01.rst

2. :ref:`Configure it <tcf_guide_configuration>`, adding to
   `~/.tcf/conf_servers.py` or `/etc/tcf/conf_servers.py`

   .. include:: doc/02-client-setup-LL-03.rst

   You can also :ref:`install a server <ttbd_guide_deployment>`, in
   your machine or another one.

3.

   .. include:: doc/02-client-setup-LL-04-login.rst

4. If you want to run Zephyr testcases you will also need to follow
   the `Zephyr Development Environment Setup on Linux
   <https://docs.zephyrproject.org/latest/getting_started/installation_linux.html>`_
   and run::

     $ git clone https://github.com/zephyrproject-rtos/zephyr.git zephyr.git
     $ source zephyr.git/zephyr-env.sh

   before getting running *tcf* commands that involve Zephyr.

:ref:`Contributions <tcf_contributing>` welcome!

*Playing around with a server*
==============================

Once a server is configured and logged in, list with *tcf* which
targets it gives you acces to (this list is for the targets a default
:ref:`server install provides <ttbd_guide_install_default_config>`,
*qz*\* for Zephyr OS QEMU targets, *qlf*\* for Fedora Linux targets)::

  $ tcf list
  local/nwa
  ...
  local/qz30a-x86
  local/qz30b-x86
  local/qz30c-x86
  ...
  local/qz39c-arm
  local/qz40a-nios2
  ..
  local/qz45a-riscv32
  ...
  local/qlf04c
  local/qlf05cH
  ...


There are three test networks defined (*nwa*, *nwb* and *nwc*) and
targets assigned to each network. Thus, *qz39c-arm* is an ARM virtual
target, on network *c* (*192.168.12/0/24*) with IP address
*192.168.12.39*

*qlf* are QEMU Linux Fedora numbers *04* or *05* connected to network
*c* and *H* connected to upstream internet via NAT.

Feel free to add `-v`\s after *tcf* (to increase *tcf*`s verbosity)
or after the *list* command (to increase the amount of information for
each target).

As installing `tcf-zephyr` has brought the dependencies needed to
build the Zephyr OS you can run one of its test cases on it::

  $ git clone http://github.com/zephyrproject-rtos/zephyr
  $ export ZEPHYR_BASE=$HOME/zephyr
  $ export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
  $ export ZEPHYR_SDK_INSTALL_DIR=/opt/zephyr-sdk-0.9.3

  $ cd $ZEPHYR_BASE/samples/hello_world
  $ make BOARD=qemu_x86

  $ tcf acquire qz30a-x86
  # Note that depending on which target you use you might need
  # zephyr.bin instead of zephyr.elf
  $ tcf images-upload-set qz30a-x86 kernel-x86:outdir/qemu_x86/zephyr/zephyr.elf
  $ tcf power-cycle qz30a-x86
  $ tcf console-read qz30a-x86
  ***** BOOTING ZEPHYR OS v1.6.99 - BUILD: Jan 14 2017 06:04:22 *****
  Hello World! x86
  $ tcf power-off qz30a-x86

*tcf* provides primitives to (see *tcf --help*):

 - power control: on, off, cycle, reset

 - debugging: reset/halt/resume CPUs, attach GDB, run openocd commands

 - read/write (serial) consoles

 - deploy/flash images, roms, etc

these are available if the targets supports the interfaces for it,
which you can find by listing it
with ``-vv``::

  $ tcf list -vv arduino101-15 | grep interfaces:
  interfaces: test_target_console_mixin test_target_images_mixin tt_debug_mixin tt_power_control_mixin

use *tcf --help* to discover what is available.

Targets can also support one or more BSPs. A BSP in a target is
something we can use to run code on. When targets support multiple
BSPs, then we can decide to run the target in different *BSP models*,
each model determining which BSPs are used of all the ones available.

For example, the *Arduino 101* supports has two different BSPs (ARC
and x86) and can be used in three BSP models: as *x86* only, as *arc*
only and as *x86+arc*.

Running Zephyr OS testcases
===========================

Zephyr OS testcases can be run directly thanks to a :class:`driver
<tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c>` (loaded by the TCF
configuration file :download:`/etc/tcf/conf_zephyr.py
<zephyr/conf_zephyr.py>`), with *tcf run* doing the building,
flashing, power cycling, reading and checking for you (including
choosing one or more suitable targets)::

  $ cd $ZEPHYR_BASE
  $ tcf run -vvy tests/kernel/common
  INFO2/	toplevel @local: scanning for test cases
  INFO1/oqep	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: will run on target group 'target=locals/qz30b-x86:x86'
  PASS2/oqep	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: configure passed
  PASS1/oqep	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: build passed
  PASS2/oqep	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: deploy passed
  INFO2/oqepE#1	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: Reset
  PASS2/oqepE#1	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: found expected `RunID: :gn0v` in console `locals/qz30b-x86:default` at 1.86s
  PASS2/oqepE#1	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: eval pass: found expected `RunID: :gn0v` in console `locals/qz30b-x86:default` at 1.86s
  PASS2/oqepE#1	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: found expected `PROJECT EXECUTION SUCCESSFUL` in console `locals/qz30b-x86:default` at 0.02s
  PASS2/oqepE#1	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: eval pass: found expected `PROJECT EXECUTION SUCCESSFUL` in console `locals/qz30b-x86:default` at 0.02s
  PASS1/oqep	tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: evaluation passed
  PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped, in 0:00:24.056627) - passed

In here:

- *-y* means pick just one target to run on; by default
  *tcf run* will try to run each testcase in as many different target
  types as possible, but just one per type. With *-u* (unlimited)
  you'd ask *tcf run* to run in every single target, even if it means
  more than one of a different type.

- *tests/kernel/common* is the path to a directory in the Zephyr OS
  source tree--*tcf run* will look for stuff in directories, and in
  there it will find *testcase.yaml*, which the Zephyr driver will
  recognize.

- after building and deploying, *tcf run* has reset the target and
  read from the console until it found a few things the Zephyr driver
  told it to look for:

  * ``RunID: :gn0v``: during the compilation, this was passed as
    ``-DTC_RUNID=:gn0v``, serves to ensure the right image got flashed
    and ran.

    Note this ID is unique to the testcase path, the target is run
    into and a bunch of other things, so it can be guaranteed that if
    the image that boots does not have that, it is likely the wrong
    image and shall be a failure.

  * ``PROJECT EXECUTION SUCCESFUL``: every Zephyr OS testcase prints
    this on success. If we got ``...FAILED``, then the testcase
    execution would be marked as failed.

  * The driver also keeps an eye for telltales of issues, like ``USAGE
    FAULT``, ``fatal fault`` and will report failure if those are seen.

Running in multiple targets
---------------------------

Now if you ran (note there is no *-y* and only one *-v* to reduce
verbosity)::

  $ cd $ZEPHYR_BASE
  $ tcf run -v tests/kernel/common
  INFO1/ep8q	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz39a-xtensa:xtensa: will run on target group 'target=locals/qz39a-xtensa:xtensa'
  INFO1/foav	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz36b-riscv32:riscv32: will run on target group 'target=locals/qz36b-riscv32:riscv32'
  INFO1/kmat	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz33b-arm:arm: will run on target group 'target=locals/qz33b-arm:arm'
  INFO1/oqep	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: will run on target group 'target=locals/qz30b-x86:x86'
  INFO1/ilrv	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz35a-nios2:nios2: will run on target group 'target=locals/qz35a-nios2:nios2'
  PASS1/foav	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz36b-riscv32:riscv32: build passed
  PASS1/ilrv	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz35a-nios2:nios2: build passed
  PASS1/ep8q	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz39a-xtensa:xtensa: build passed
  PASS1/kmat	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz33b-arm:arm: build passed
  PASS1/oqep	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: build passed
  PASS1/kmat	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz33b-arm:arm: evaluation passed
  PASS1/ilrv	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz35a-nios2:nios2: evaluation passed
  PASS1/oqep	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz30b-x86:x86: evaluation passed
  BLCK0/foav	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz36b-riscv32:riscv32: evaluation blocked
  PASS1/ep8q	zephyr.git/tests/kernel/common/testcase.yaml#kernel.common @locals/qz39a-xtensa:xtensa: evaluation passed
  BLCK0/	toplevel @local: 5 tests (4 passed, 0 failed, 1 blocked, 0 skipped, in 0:00:43.538684) - blocked
  make: *** [/tmp/tcf-OL1zv6.mk:2: tcf-jobserver-run] Error 127

in this case we are telling *tcf run* to find all the testcases in
Zephyr OS's *tests/kernel/common* (there is only one) but it will try
to run each one on each different types of targets available--in this
case, there is five different QEMUs of different architectures.

Note how they all pass, except for the one for *riscv32* which
*blocks*--meaning something happened that forbade us from telling if
the testcase passes or fails.

When something doesn't pass (it *fails*, *skips* or *blocks*), the
default reporting driver creates a *report* file with the ID of the
testcase, in this case *report-foav.txt* (in your case it might have a
different ID)--sometimes it is related to conditions or bugs in the
server.

Running many testcases
----------------------

Following the example before, we can run for example two paths at
the same time; note *tcf run* will spread around multiple targets in
parallel--because it'd get very verbose, we removed the *-v* and *tcf
run* will only report about things that don't pass::

  $ tcf run tests/kernel/common/ tests/kernel/mem_slab/
  BLCK0/kijl	tests/kernel/common/testcase.yaml#kernel.common @locals/qz37a-riscv32:riscv32: evaluation blocked
  BLCK0/8thb	tests/kernel/mem_slab/mslab_threadsafe/testcase.yaml#kernel.memory_slabs @locals/qz37b-riscv32:riscv32: evaluation blocked
  BLCK0/605h	tests/kernel/mem_slab/mslab/testcase.yaml#kernel.memory_slabs @locals/qz37a-riscv32:riscv32: evaluation blocked
  BLCK0/wveb	tests/kernel/mem_slab/mslab_concept/testcase.yaml#kernel.memory_slabs @locals/qz37b-riscv32:riscv32: evaluation blocked
  BLCK0/sdlb	tests/kernel/mem_slab/mslab_api/testcase.yaml#kernel.memory_slabs @locals/qz37b-riscv32:riscv32: evaluation blocked
  BLCK0/	toplevel @local: 25 tests (20 passed, 0 failed, 5 blocked, 0 skipped, in 0:02:51.895300) - blocked
  make: *** [/tmp/tcf-jbll1L.mk:2: tcf-jobserver-run] Error 127

at the end the summary tell us how it run 25 testcases, of which
twenty passed, five blocked and it took about three minutes.

.. _tcf_run_automating_intro:

Automating test case building and execution
===========================================

Automation can be done in any language, provided there is a driver for
it; however, the default automation script is Python.

Create a file called `test_hello_world.py` with the following:

.. literalinclude:: examples/test_zephyr_hello_world.py
   :language: python
   :linenos:

this tells *tcf*'s test runner:

 - With the :func:`tcfl.tc.target` class decorator, we declare this
   test needs a single target on which we are going to deploy a Zephyr
   application.

   - *"zephyr_board"* is a :ref:`target specification
     <tcf_target_specs>`, which in this case makes sure the target
     exposes said tag, which indicates it can run Zephyr OS Apps.

   - *app_zephyr* is an :ref:`App Builder <tcf_guide_app_builder>` and
     provides the information for a Zephyr Application to build and
     load into the target.

     It will provide/impose additional conditions on the target
     selection process so Zephyr can be deployed on it. It also
     provides the instructions needed to build the app, deploy it to
     the target, setup the testcase for operation (like installing
     hooks to catch error messages) and starting the target. That is
     provided in the form of Python functions added to the test object
     `_test`) (:ref:`more information <tcf_guide_tests>`).

 - we create a `_test` class, deriving from :class:`tcfl.tc.tc_c`, so
   the testcase can be located and integrated

 - there is an evaluation function, `_test.eval(target)` which is used
   to tell if the test case succeeded or failed.

   The testcase runner will call it with a target object, which
   represents a remote target with which you can interact via the
   :class:`API <tcfl.tc.target_c>` it provides.

   If it returns, it is a *pass*. A failure can be indicated by
   raising :exc:`tcfl.tc.failed_e`; any other exception raised is
   captured and converted to a :exc:`blockage <tcfl.tc.blocked_e>`,
   which is a situation considered to impede the evaluation of the
   testcase.

   Multiple evaluation functions can be provided (named `eval*()`,
   each taking none or different targets, as many as declared by the
   testcase (see :class:`test class overview <tcfl.tc.tc_c>`). For the
   testcase to pass, all the evaluation functions have to pass.

   FIXME: ensure the tc_c and target_c class descriptions are adequate
   from this context

*tcf run* finds the `.py` file, queries which targets available and
selects the ones that match the conditions imposed with
:func:`tcfl.tc.target`; it then builds the *Hello World!* app for each
of them, pulling configuration from the target's description tags
(that you can see with `tcf list -vvv TARGETNAME`) and then evaluates
the output for success.

Let's ask it to run against an specific target, *local/qz39c-arm*::

  $ tcf run -vv -t local/qz39c-arm test_zephyr_hello_world.py
  INFO2/	toplevel @local: scanning for test cases
  INFO2/n9gc	test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: will run on target group 'xqkw (target=local/qz39c-arm:arm)'
  PASS1/n9gc	test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: configure passed
  PASS1/n9gc	test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: build passed
  PASS2/n9gc	test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: deploy passed
  INFO2/n9gcE#1	test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: Reset
  PASS2/n9gcE#1	test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: found expected `Hello World! arm` in console `default` at 0.03s
  PASS2/n9gcE#1	test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: eval pass: found expected `Hello World! arm` in console `default` at 0.03s
  PASS1/n9gc	test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: evaluation passed
  PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

You want less information about what happened? remove `-v`\s. Want a
full record? add a `--log-file=something.log` --that will show build
logs, read texts, etc.

Each line contains a high level tag (*INFO*, *PASS*, *FAIL*, *BLCK*),
followed by a verbosity level, a *unique ID* that identifies the
testcase and the target(s) on which it is being run (and will prefix
all the reports about it), the name of the test case and the target
where it runs and information on what happened (:ref:`more details
<tcf_run_output_groking>`).

At this point, you can ask it to run anywhere it can; *tcf run* will
try to run on all targets it can find, running by default only one
target of each type::

  $ tcf run test_zephyr_hello_world.py
  PASS0/  toplevel @local: 3 tests (3 passed, 0 failed, 0 blocked, 0 skipped) - passed

The testcase was run in three different targets, so we have three
testst that passed.

Note *tcf* is very shy, by default it only reports about things that
fail or error (and generates individual `report-*.txt` files about
it. For more information, throw in *-v*\s

*tcf* can be taught about other testcase formats using :term:`test
case driver`\s; (like :class:`Zephyr's Sanity Checks
<tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c>`)
