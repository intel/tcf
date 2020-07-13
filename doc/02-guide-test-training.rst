:orphan:

.. _tcf_guide_test_training:

Testcase training
=================

Before you get started, this training guide assumes:

 - You have :ref:`installed <install_tcf_client>` the client software
 - have access to a server (local or remote)
 - you know your way around: Linux, Git, building the Zephyr kernel
 - you know some basics of Python


A basic testcase
----------------

.. literalinclude:: training/test_01.py

Inherit the basic class and create an evaluation method (where we run
the test), just print something

::

  $ tcf run test_01.py
  PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

- Quite succint? append one more more ``-v`` to *tcf run*.
- Increase its verbosity, add ``dlevel = -1`` or ``-2`` to *self.report_info()*
- Why not use Python's *print()* instead of *self.report_info()*? it
  sidesteps TCF's login mechanism and if you you want stuff logged and
  reported with proper verbosity control, you need to use TCF's
  reporting system.

  As well, when running many testcases and targets at the same time,
  it helps to keep the information organized; more on that later.

What's in a testcase
--------------------

- A testcase has six phases (which can be individually inhibited)

  - configuration
  - build
  - assignment of targets
  - deployment
  - evaluation (subphases setup/start/teardown)
  - cleanup

- Can be written in any language, as long as there is a driver to plug
  it into the framework (Python scripting driver by default, also
  available driver for Zephyr Sanitycheck's testcase.ini)

- Can need zero or more targets

  - example of no targets: static checkers, checkpatch, things that
    can run locally
  - one target: Zephyr Sanity Checks, some network testcases
  - multiple targets: device driver I/O testcases, most network
    testcases

- *Testcase* is just a name, it can be used during development for
  fast flashing and whatever suits you


Breaking it up
--------------

.. literalinclude:: training/test_02.py
   :emphasize-lines: 8-9

- You can have multiple evaluation functions, as long as they are
  called *eval_*()*

- They are executed sequentially in **alphabetical** order


::

   $ tcf run -vv test_02.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/gixj	test_02.py#_test @local: will run on target group 'localic-localtg'
   INFO2/gixjE#1	test_02.py#_test @local: Hello 1
   INFO2/gixjE#1	test_02.py#_test @local: Hello 2
   PASS1/gixj	test_02.py#_test @local: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed


Give me a target
----------------

.. literalinclude:: training/test_03.py
   :emphasize-lines: 4, 9-10

- ``@tcfl.tc.target()`` allows the testcase to request a target..or
  two, or seven hundred. By default they are called *target*, *target1*...
  but you can use ``name = "NAME"`` to give your own name.

- The only arguments you can pass to the *eval_*()* methods are target
  names. Note how we pass that to *eval_01()* and use it to report;
  this will have an impact when using multiple targets.

- Targets can be selected to run a tescase on in any of three ways
  (which you can set with teh ``mode = "MODE"`` parameter):

  - *any*: pick one, any one will do
  - *all*: pick all
  - *one-per-type*: pick one of each type

::

   $ tcf run -vv test_03.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/taqq	test_03.py#_test @local/qz46a-riscv32:riscv32: will run on target group 'target=local/qz46a-riscv32:riscv32'
   INFO2/taqqE#1	test_03.py#_test @local/qz46a-riscv32:riscv32: Hello 1
   INFO2/taqqE#1	test_03.py#_test @local/qz46a-riscv32:riscv32: Hello 2
   PASS1/taqq	test_03.py#_test @local/qz46a-riscv32:riscv32: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Give me a target that can run Zephyr
------------------------------------

.. literalinclude:: training/test_04.py
   :emphasize-lines: 4

- ``@tcfl.tc.target()``’s first argument is a :ref:`logical expression
  <tcf_evaluation_expressions>` which can use the tags a target
  exports (which you can see with ``tcf list -vv TARGETNAME``)

- *zephyr_board* means any target that exports a tag called
  zephyr_board with a value. That maps to the *BOARD* arg to the
  Zephyr build.

::

   $ tcf run -vv test_04.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/vzqp	test_04.py#_test @local/qz39a-arm:arm: will run on target group 'target=local/qz39a-arm:arm'
   INFO2/vzqpE#1	test_04.py#_test @local/qz39a-arm:arm: Hello 1
   INFO2/vzqpE#1	test_04.py#_test @local/qz39a-arm:arm: Hello 2
   PASS1/vzqp	test_04.py#_test @local/qz39a-arm:arm: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Give me a target that can run Zephyr and is x86
-----------------------------------------------

.. literalinclude:: training/test_05.py
   :emphasize-lines: 3

- many combinations are possible with logical expressions.

  Can get tricky, though; ``-vvvv`` will give you lots of details of the selection
  process; also the same expression can be passed to *tcf list* to
  figure out how it works.

- Removing ``mode = "any"`` defaults to running on one target of each
  type..which might result on a lot of execution if you have many
  different types of targets.

::

   $ tcf run -v test_05.py
   INFO1/1qvi	test_05.py#_test @srrsotc03/ti-01:x86+arc+arm/x86: will run on target group 'target=srrsotc03/ti-01:x86+arc+arm'
   INFO1/lwq8	test_05.py#_test @srrsotc03/qc1000-01:x86+arc/x86: will run on target group 'target=srrsotc03/qc1000-01:x86+arc'
   INFO1/dvj6	test_05.py#_test @jfsotc03/a101-16:x86: will run on target group 'target=jfsotc03/a101-16:x86'
   INFO1/gjfa	test_05.py#_test @jfsotc02/qz34l-x86:x86: will run on target group 'target=jfsotc02/qz34l-x86:x86'
   INFO1/luzj	test_05.py#_test @jfsotc03/qc1000-24:x86: will run on target group 'target=jfsotc03/qc1000-24:x86'
   INFO1/nycw	test_05.py#_test @jfsotc03/a101-16:x86+arc/x86: will run on target group 'target=jfsotc03/a101-16:x86+arc'
   INFO1/ra1f	test_05.py#_test @jfsotc02/mv-09:x86: will run on target group 'target=jfsotc02/mv-09:x86'
   ...
   PASS0/	toplevel @local: 9 tests (9 passed, 0 failed, 0 blocked, 0 skipped) - passed


But put some Zephyr into it?
----------------------------

.. literalinclude:: training/test_06.py
   :emphasize-lines: 2, 5-6

- feed ``@target()`` a path to a Zephyr App.

- ``app_zephyr`` enables a plugin that will monkey patch methods in
  your test class that tells it how to build, flash and startup a
  target running Zephyr (functions called
  ``(configure|build|deploy|start)_50_for_target()``)

- The app is built, flashed and the target reset before *eval_*()* are
  called

::

   $ tcf run -vv test_06.py
   INFO1/bxot	test_06.py#_test @jfsotc02/a101-01:x86: will run on target group 'target=jfsotc02/a101-01:x86'
   PASS2/bxot	test_06.py#_test @jfsotc02/a101-01:x86: configure passed
   PASS1/bxot	test_06.py#_test @jfsotc02/a101-01:x86: build passed
   PASS2/bxot	test_06.py#_test @jfsotc02/a101-01:x86: deploy passed
   INFO2/bxotE#1	test_06.py#_test @jfsotc02/a101-01:x86: Reset
   INFO2/bxotE#1	test_06.py#_test @jfsotc02/a101-01:x86: Hello 1
   INFO2/bxotE#1	test_06.py#_test @jfsotc02/a101-01:x86: Hello 2
   PASS1/bxot	test_06.py#_test @jfsotc02/a101-01:x86: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Now we are building all the time, some time savers
--------------------------------------------------

- create a temporary directory to save the build products::

    $ mkdir tmp

- add ``--tmpddir tmp`` to ``tcf run``--this way the builder will be
  able to reuse those build products

  by default, a temporary directory is created and removed when
  done--this helps when you have a lot of code being run in many
  targets and you just care about the results.

- as a bonus, in ``tmp/run.log`` you’ll get a log file with all the
  step by step details, ``--log-file`` also gets you that.

- work just with one target--this means that we don’t have to
  recompile for new targets constantly (as they are assigned randomly)
  and reuse what is already built in the temporary directory:

  Let a target be assigned running normally::

    $ tcf run --tmpdir tmp test_06.py
    ...
    INFO1/bxot	test_06.py#_test @jfsotc02/a101-01:x86: will run on target group 'target=jfsotc02/a101-01:x86'

  Save that *jfsotc02/a101-01*, that’s your target ID that you feed to
  ``tcf run`` with ``-t``::

    $ tcf run --tmpdir tmp -t jfsotc02/a101-01 test_06.py
    INFO1/bxot	test_06.py#_test @jfsotc02/a101-01:x86: will run on target group 'target=jfsotc02/a101-01:x86'...

So, is Zephyr booting?
----------------------

.. literalinclude:: training/test_07.py
   :emphasize-lines: 9, 12

- *build\*()* are build methods, things that have to happen when we
  build (akin to *eval\*()*)

- Use the target’s :class:`zephyr <tcfl.app_zephyr.zephyr>` API
  extension to enable the boot banner with a config fragment
  introduced with :meth:`config_file_write
  <tcfl.app_zephyr.zephyr.config_file_write>`

- Use *expect()* to wait for something on the default console; in this
  case, Zephyr’s boot banner (it can be a :mod:`Python regex <re>`
  ``re.compile(REGEX)``) and if it timeouts, it raises a failure
  exception, no more *eval\*()* will execute.

::

   $ tcf run --tmpdir tmp -vv test_08.py



And is the code doing what I want? Hello World?
-----------------------------------------------

.. literalinclude:: training/test_08.py
   :emphasize-lines: 14

- Same as before, use *expect()* to require the console to print
  *Hello World!* to determine if the testcase is passing.

::

   $ tcf run --tmpdir tmp -vv test_08.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/lyse	test_08.py#_test @local/qz36b-arm:arm: will run on target group 'target=local/qz36b-arm:arm'
   PASS2/lyse	test_08.py#_test @local/qz36b-arm:arm: configure passed
   PASS1/lyse	test_08.py#_test @local/qz36b-arm:arm: build passed
   PASS2/lyse	test_08.py#_test @local/qz36b-arm:arm: deploy passed
   INFO2/lyseE#1	test_08.py#_test @local/qz36b-arm:arm: Reset
   PASS2/lyseE#1	test_08.py#_test @local/qz36b-arm:arm: found expected `***** BOOTING ZEPHYR OS` in console `local/qz36b-arm:default` at 0.05s
   PASS2/lyseE#1	test_08.py#_test @local/qz36b-arm:arm: eval pass: found expected `***** BOOTING ZEPHYR OS` in console `local/qz36b-arm:default` at 0.05s
   PASS2/lyseE#1	test_08.py#_test @local/qz36b-arm:arm: found expected `Hello World!` in console `local/qz36b-arm:default` at 0.04s
   PASS2/lyseE#1	test_08.py#_test @local/qz36b-arm:arm: eval pass: found expected `Hello World!` in console `local/qz36b-arm:default` at 0.04s
   PASS1/lyse	test_08.py#_test @local/qz36b-arm:arm: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed


What happens when it fails? Let's make it fail
----------------------------------------------

.. literalinclude:: training/test_09.py
   :emphasize-lines: 16

- Instead of *Hello World*, look for *Hello Kitty*

- After waiting for sixy seconds to receive *Hello Kitty*, it raises
  an exception and fails.

  - This will generate a file called ``report-HASHID.txt`` in the current
    directory with detailed information

  - ``HASHID`` is a UUID from the testcase name and the target(s) where it
    ran, *azus* in the example below.

::

   $ tcf run --tmpdir tmp -vv test_09.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/azus	test_09.py#_test @local/qz36a-arm:arm: will run on target group 'target=local/qz36a-arm:arm'
   PASS2/azus	test_09.py#_test @local/qz36a-arm:arm: configure passed
   PASS1/azus	test_09.py#_test @local/qz36a-arm:arm: build passed
   PASS2/azus	test_09.py#_test @local/qz36a-arm:arm: deploy passed
   INFO2/azusE#1	test_09.py#_test @local/qz36a-arm:arm: Reset
   PASS2/azusE#1	test_09.py#_test @local/qz36a-arm:arm: found expected `***** BOOTING ZEPHYR OS` in console `local/qz36a-arm:default` at 0.05s
   PASS2/azusE#1	test_09.py#_test @local/qz36a-arm:arm: eval pass: found expected `***** BOOTING ZEPHYR OS` in console `local/qz36a-arm:default` at 0.05s
   FAIL2/azusE#1	test_09.py#_test @local/qz36a-arm:arm: eval failed: expected console output 'Hello Kitty!' from console 'qz36a-arm:default' NOT FOUND after 60.1 s
   FAIL0/azus	test_09.py#_test @local/qz36a-arm:arm: evaluation failed
   FAIL0/	toplevel @local: 1 tests (0 passed, 1 failed, 0 blocked, 0 skipped) - failed
   /tmp/tcf-k9WBkM.mk:2: recipe for target 'tcf-jobserver-run' failed
   make: *** [tcf-jobserver-run] Error 1

.. note:: ignore the make messages at the bottom, it is a subproduct of
          using *make*’s jobserver.

Running a Zephyr sanity check testcase
--------------------------------------

- A :mod:`builtin driver<tcfl.tc_zephyr_sanity>` understand's Zephyr's
  Sanity Check *testcase.ini* files and by default runs them on all
  available targets (one of each type)

- You can use ``-u`` to override and force it to run on *all* targets
  (stress test) or ``-y`` to run on any.

::

   $ cd $ZEPHYR_BASE
   $ mkdir tmp
   $ tcf run --tmpdir tmp -v tests/kernel/common
   INFO1/ihuu	tests/kernel/common/testcase.ini#test @local/qz35a-arm:arm: will run on target group 'target=local/qz35a-arm:arm'
   INFO1/7jbr	tests/kernel/common/testcase.ini#test @local/qz42a-nios2:nios2: will run on target group 'target=local/qz42a-nios2:nios2'
   INFO1/hegm	tests/kernel/common/testcase.ini#test @local/qz32b-x86:x86: will run on target group 'target=local/qz32b-x86:x86'
   INFO1/c8y1	tests/kernel/common/testcase.ini#test @local/qz45b-riscv32:riscv32: will run on target group 'target=local/qz45b-riscv32:riscv32'
   PASS1/c8y1	tests/kernel/common/testcase.ini#test @local/qz45b-riscv32:riscv32: build passed
   PASS1/hegm	tests/kernel/common/testcase.ini#test @local/qz32b-x86:x86: build passed
   PASS1/7jbr	tests/kernel/common/testcase.ini#test @local/qz42a-nios2:nios2: build passed
   PASS1/ihuu	tests/kernel/common/testcase.ini#test @local/qz35a-arm:arm: build passed
   PASS1/c8y1	tests/kernel/common/testcase.ini#test @local/qz45b-riscv32:riscv32: evaluation passed
   PASS1/hegm	tests/kernel/common/testcase.ini#test @local/qz32b-x86:x86: evaluation passed
   PASS1/7jbr	tests/kernel/common/testcase.ini#test @local/qz42a-nios2:nios2: evaluation passed
   PASS1/ihuu	tests/kernel/common/testcase.ini#test @local/qz35a-arm:arm: evaluation passed
   PASS0/	toplevel @local: 4 tests (4 passed, 0 failed, 0 blocked, 0 skipped) - passed


Double down
-----------

.. literalinclude:: training/test_10.py
   :emphasize-lines: 6-8, 11-12


- Two targets, flashed with *Hello World*

- The second one is called, by default *target1*. You can also use
  *name = "TARGETNAME"*.

- Note how the messages update vs running a single target

- Wait first for *target* and then *target1* to both print *Hello
  World!*

::

   $ tcf run --tmpdir tmp -vv test_10.py
   INFO1/zdad	test_10.py#_test @zc7o: will run on target group 'target=local/qz40a-nios2:nios2 target1=local/qz48b-riscv32:riscv32'
   PASS2/zdad	test_10.py#_test @zc7o: configure passed
   PASS1/zdad	test_10.py#_test @zc7o: build passed
   PASS2/zdad	test_10.py#_test @zc7o: deploy passed
   INFO2/zdadE#1	test_10.py#_test @zc7o|local/qz40a-nios2: Reset
   INFO2/zdadE#1	test_10.py#_test @zc7o|local/qz48b-riscv32: Reset
   PASS2/zdadE#1	test_10.py#_test @zc7o|local/qz40a-nios2: found expected `Hello World!` in console `local/qz40a-nios2:default` at 0.11s
   PASS2/zdadE#1	test_10.py#_test @zc7o|local/qz40a-nios2: eval pass: found expected `Hello World!` in console `local/qz40a-nios2:default` at 0.11s
   PASS2/zdadE#1	test_10.py#_test @zc7o|local/qz48b-riscv32: found expected `Hello World!` in console `local/qz48b-riscv32:default` at 0.06s
   PASS2/zdadE#1	test_10.py#_test @zc7o|local/qz48b-riscv32: eval pass: found expected `Hello World!` in console `local/qz48b-riscv32:default` at 0.06s
   PASS1/zdad	test_10.py#_test @zc7o: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Note how now the test reports running on *@zc7o*, a unique identifier for a
set of targets. Log messages specific to an specific target get that
prefixed to the target name (as in *@zc7o|local/qz48b-riscv32*).

Double down more efficiently
----------------------------

We were waiting for one to complete, then the other, but they were
running at the same time. We can set expectations and then wait for
them to happen in parallel.

*Expectation*: poll and check

.. literalinclude:: training/test_11.py
   :emphasize-lines: 11-13

- Asks to expect receiving from each target the same string, but all
  at the same time and run the expectation loop until they are all
  received or it timesout (meaning failure).

- That said, you will only notice speed ups on things that take longer
  to execute and thus, parallelize well :)

::

   $ tcf run --tmpdir tmp -vv test_11.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/0d6z	test_11.py#_test @6hj6: will run on target group 'target=local/qz44b-nios2:nios2 target1=local/qz41b-nios2:nios2'
   PASS2/0d6z	test_11.py#_test @6hj6: configure passed
   PASS1/0d6z	test_11.py#_test @6hj6: build passed
   PASS2/0d6z	test_11.py#_test @6hj6: deploy passed
   INFO2/0d6zE#1	test_11.py#_test @6hj6|local/qz44b-nios2: Reset
   INFO2/0d6zE#1	test_11.py#_test @6hj6|local/qz41b-nios2: Reset
   PASS2/0d6zE#1	test_11.py#_test @6hj6|local/qz44b-nios2: found expected `Hello World!` in console `local/qz44b-nios2:default` at 0.09s
   PASS2/0d6zE#1	test_11.py#_test @6hj6|local/qz44b-nios2: eval pass: found expected `Hello World!` in console `local/qz44b-nios2:default` at 0.09s
   PASS2/0d6zE#1	test_11.py#_test @6hj6|local/qz41b-nios2: found expected `Hello World!` in console `local/qz41b-nios2:default` at 0.13s
   PASS2/0d6zE#1	test_11.py#_test @6hj6|local/qz41b-nios2: eval pass: found expected `Hello World!` in console `local/qz41b-nios2:default` at 0.13s
   PASS2/0d6zE#1	test_11.py#_test @6hj6: eval pass: all expectations found
   PASS1/0d6z	test_11.py#_test @6hj6: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Double down catchas
-------------------

- If your testcase takes one target and it shall run on one of each
  type and you have 6 different target types, it will:

  - choose one target per type to run the testcase
  - build and flash 6 times, evaluate 6 times (one on each type of target)

- If your testcase needs two different targets and there are six
  available:

  - it will choose *6^2 = 36* permutations of targets
  - build and flash 36 times twice (once per target), eval 36 times

- If your testcase needs three different targets and there are six
  available

  - it will choose *6^3 = 216* permutations of targets:

  - build and flash 216 times thrice (once per target), eval 216 times

*tcf run* limits by default to 10 permutations, but you can tweak that
with ``-PNUMBER``

Two interconnected targets?
---------------------------

Use ``@tcfl.tc.interconnect()`` (a target--maybe conceptual--which
connects other targets together)

.. literalinclude:: training/test_12.py
   :emphasize-lines: 3

- Looking at the target's *interconnecs* tags, *tcf run* can determine
  which targets are connected to which interconnects.

- Interconnects also use tags to describe what they are or how they
  operate (maybe is an IP interconnect, or just a group that describes
  targets that are in the same room, etc).

- By requesting an interconnect and two targets that belong to it, we
  will get a lot of permutations of two interconnected targets.

::

   $ tcf run --tmpdir tmp -v test_12.py
   INFO1/0hgf	test_12.py#_test @qlan-tfdh: will run on target group 'ic=local/nwa target=local/qz34a-x86:x86 target1=local/qz45a-riscv32:riscv32'
   INFO1/20i5	test_12.py#_test @qlan-xk2u: will run on target group 'ic=local/nwa target=local/qz43a-nios2:nios2 target1=local/qz39a-arm:arm'
   INFO1/9rdg	test_12.py#_test @qlan-xo7w: will run on target group 'ic=local/nwa target=local/qz34a-x86:x86 target1=local/qz40a-nios2:nios2'
   ...
   PASS1/soip	test_12.py#_test @qlan-xeb3: evaluation passed
   PASS1/4t2r	test_12.py#_test @qlan-xqnu: evaluation passed
   PASS1/ku9e	test_12.py#_test @qlan-kdrw: evaluation passed
   PASS1/20i5	test_12.py#_test @qlan-xk2u: evaluation passed
   PASS1/9rdg	test_12.py#_test @qlan-xo7w: evaluation passed
   PASS0/	toplevel @local: 10 tests (10 passed, 0 failed, 0 blocked, 0 skipped) - passed

Note that because 4 target types were available (QEMU Zephyr for x86,
NIOS2, ARM and Risc v32), it has generated 16 different permutations
and only taken the first 10 (because of the default ``-P10``
setting).

Networking and the Zephyr echo server
-------------------------------------

Let's get a Zephyr network application, the Echo Server, built and
deployed in a target along with a network. Being part of a network
assigns IP addresses to targets, which we can query for building:

.. literalinclude:: training/test_13.py
   :emphasize-lines: 3-5, 10, 12-23, 25-26

- Use ``@tcfl.tc.interconnect("ipv4_addr")`` to request an
  interconnect that declares having an IPv4 address.

- Request a Zephyr capable target; use ``name`` to name them and
  ``spec`` to :ref:`filter <tcf_evaluation_expressions>` the
  targets where the echo server can run (based on the configuration
  files available). Use ``app_zephyr`` to point to the right source.

- Use *build_\*()* to set configuration values, as these applications
  need to know their IP addresses at build time. These are available
  in the target's *kws* dictionary, which export the target's tags.

- Use *start_\*()* to power cycle the network before starting the
  test, otherwise it will not work. *ic* is the default name assigned by
  ``@tcfl.tc.interconnect()``.

  Before evaluating, the *setup\*()* and *start\*()* functions are
  executed serially in alphabetical order. That's why we call it
  *_00_* to make sure it gets run before the default Zephyr's start
  function (*start_50_\*()*).

::

   $ tcf run --tmpdir tmp -vv test_13.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/pz15	test_13.py#_test @qlan-4coc: will run on target group 'ic=local/nwa zephyr_server=local/qz33a-x86:x86'
   PASS2/pz15	test_13.py#_test @qlan-4coc: configure passed
   PASS1/pz15	test_13.py#_test @qlan-4coc: build passed
   PASS2/pz15	test_13.py#_test @qlan-4coc: deploy passed
   INFO2/pz15E#1	test_13.py#_test @qlan-4coc|local/nwa: Power cycled
   INFO2/pz15E#1	test_13.py#_test @qlan-4coc|local/qz33a-x86: Reset
   PASS2/pz15E#1	test_13.py#_test @qlan-4coc|local/qz33a-x86: found expected `init_app: Run echo server` in console `local/qz33a-x86:default` at 0.06s
   PASS2/pz15E#1	test_13.py#_test @qlan-4coc|local/qz33a-x86: eval pass: found expected `init_app: Run echo server` in console `local/qz33a-x86:default` at 0.06s
   PASS2/pz15E#1	test_13.py#_test @qlan-4coc|local/qz33a-x86: found expected `receive: Starting to wait` in console `local/qz33a-x86:default` at 0.05s
   PASS2/pz15E#1	test_13.py#_test @qlan-4coc|local/qz33a-x86: eval pass: found expected `receive: Starting to wait` in console `local/qz33a-x86:default` at 0.05s
   PASS1/pz15	test_13.py#_test @qlan-4coc: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed


Add on the Zephyr echo client
-----------------------------

A full Zephyr network echo client/server needs the client code too, so
we add it:

.. literalinclude:: training/test_14.py
   :emphasize-lines: 8-12, 29-44, 53-55

- Note how *build_00_client_config* takes as argument both the
  *zephyr_client* and *zephyr_server* targets, because it needs to
  know the server's IP address to configure the client build.

  This is the reason for ``@tcfl.tc.serially``. *build\*()* functions
  that take target arguments will be executed in parallel and cause an
  error if the targets overlap. The decorator forces them to execute
  serially to avoid race conditions in the use of resources (eg:
  temporary directories) associated to each target.

- In the same fashion, *eval_10_client()* is named *_10_* to make sure
  it runs after the server's evaluation function.

::

   $ tcf run --tmpdir tmp -vv test_14.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/51yw	test_14.py#_test @v2xd-d4h6: will run on target group 'ic=local/nwb zephyr_client=local/qz32b-x86:x86 zephyr_server=local/qz31b-x86:x86'
   PASS2/51yw	test_14.py#_test @v2xd-d4h6: configure passed
   PASS1/51yw	test_14.py#_test @v2xd-d4h6: build passed
   PASS2/51yw	test_14.py#_test @v2xd-d4h6: deploy passed
   INFO2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/nwb: Power cycled
   INFO2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz32b-x86: Reset
   INFO2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz31b-x86: Reset
   PASS2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz31b-x86: found expected `init_app: Run echo server` in console `local/qz31b-x86:default` at 0.41s
   PASS2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz31b-x86: eval pass: found expected `init_app: Run echo server` in console `local/qz31b-x86:default` at 0.41s
   PASS2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz31b-x86: found expected `receive: Starting to wait` in console `local/qz31b-x86:default` at 0.07s
   PASS2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz31b-x86: eval pass: found expected `receive: Starting to wait` in console `local/qz31b-x86:default` at 0.07s
   PASS2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz32b-x86: found expected `init_app: Run echo client` in console `local/qz32b-x86:default` at 0.08s
   PASS2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz32b-x86: eval pass: found expected `init_app: Run echo client` in console `local/qz32b-x86:default` at 0.08s
   PASS2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz32b-x86: found expected `Compared [0-9]+ bytes, all ok` in console `local/qz32b-x86:default` at 1.33s
   PASS2/51ywE#1	test_14.py#_test @v2xd-d4h6|local/qz32b-x86: eval pass: found expected `Compared [0-9]+ bytes, all ok` in console `local/qz32b-x86:default` at 1.33s
   PASS1/51yw	test_14.py#_test @v2xd-d4h6: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Cover more bases on the Zephyr echo server/client
-------------------------------------------------

In this case, we want to make sure that the order at which the targets
are starting is more under our control, because we need to make sure
the *network* (interconnect) is powered on first, then the server and
then finally the client.

.. literalinclude:: training/test_15.py
   :emphasize-lines: 46-47, 49-50, 54-57

- First we override the default App Zephyr start methods
  (*start_50_zephyr_server()* and *start_50_zephyr_client()*) to do
  nothing. This will actually have them renamed as
  *overriden_start_50_zephyr_server()* and
  *overriden_start_50_zephyr_client()*.

- Then add to the existing *start_00()* a call to start the server
  target, wait for the banner indicating it has started to serve and
  then call to start the client.

- This renders *eval_00_server()* unnecesary, as we did that check on
  *start_00()* to ensure it had started properly.

::

   $ tcf run --tmpdir tmp -vv test_14.py
   ...
   INFO2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/nwb: Power cycled
   INFO2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz30b-x86: Reset
   INFO2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz31b-x86: Reset
   PASS2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz31b-x86: found expected `init_app: Run echo server` in console `local/qz31b-x86:default` at 0.10s
   PASS2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz31b-x86: eval pass: found expected `init_app: Run echo server` in console `local/qz31b-x86:default` at 0.10s
   PASS2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz31b-x86: found expected `receive: Starting to wait` in console `local/qz31b-x86:default` at 0.10s
   PASS2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz31b-x86: eval pass: found expected `receive: Starting to wait` in console `local/qz31b-x86:default` at 0.10s
   PASS2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz30b-x86: found expected `init_app: Run echo client` in console `local/qz30b-x86:default` at 0.08s
   PASS2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz30b-x86: eval pass: found expected `init_app: Run echo client` in console `local/qz30b-x86:default` at 0.08s
   PASS2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz30b-x86: found expected `Compared [0-9]+ bytes, all ok` in console `local/qz30b-x86:default` at 1.61s
   PASS2/jgszE#1	test_14.py#_test @v2xd-xwv4|local/qz30b-x86: eval pass: found expected `Compared [0-9]+ bytes, all ok` in console `local/qz30b-x86:default` at 1.61s
   PASS1/jgsz	test_14.py#_test @v2xd-xwv4: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

But let's test Zephyr's echo server/client better
-------------------------------------------------

We should be looking for more than just one occurrence of the *all ok*
message:

.. literalinclude:: training/test_16.py
   :emphasize-lines: 61-64, 66-67, 71-79

- note how after we detect the client has started running, we let the
  client run, watiting a couple of times for thirty seconds...

- ... so we can mark all the targets as active using
  :meth:`tcfl.tc.target_c.active` to avoid the server powering them
  off due to inactivity.

- once the target has had at least a minute to run, we read all the
  console output and count how many *allow ok* messages have been
  received

::

   $ tcf run --tmpdir tmp -vv test_16.py
   ...
   PASS2/4odfE#1	test_16.py#_test @qlan-pbuz|local/qz34a-x86: found expected `init_app: Run echo client` in console `local/qz34a-x86:default` at 0.08s
   PASS2/4odfE#1	test_16.py#_test @qlan-pbuz|local/qz34a-x86: eval pass: found expected `init_app: Run echo client` in console `local/qz34a-x86:default` at 0.08s
   INFO2/4odfE#1	test_16.py#_test @qlan-pbuz|local/qz34a-x86: Running for 30s (1/1)
   INFO2/4odfE#1	test_16.py#_test @qlan-pbuz|local/qz34a-x86: Running for 30s (1/2)
   PASS2/4odfE#1	test_16.py#_test @qlan-pbuz|local/qz34a-x86: found expected `Compared [0-9]+ bytes, all ok` in console `local/qz34a-x86:default` at 0.40s
   PASS2/4odfE#1	test_16.py#_test @qlan-pbuz|local/qz34a-x86: eval pass: found expected `Compared [0-9]+ bytes, all ok` in console `local/qz34a-x86:default` at 0.40s
   INFO2/4odfE#1	test_16.py#_test @qlan-pbuz|local/qz34a-x86: read console 'local/qz34a-x86:<default>' @0 2374B
   PASS2/4odfE#1	test_16.py#_test @qlan-pbuz|local/qz34a-x86: Got at least 10 'all ok' messages
   PASS1/4odf	test_16.py#_test @qlan-pbuz: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed


Developing Zephyr apps with the TCF's help
------------------------------------------

Let's write our own Zephyr App, ``test_18/src/main.c``

.. literalinclude:: training/test_18/src/main.c
   :emphasize-lines: 13

This is a random test case, sometimes *passes*, sometimes *fails*.

Our app some assistance:

- ``test_18``: a directory where to place all the information for it
- ``test_18/Makefile``: Makefile to integrate into Zephyr

  .. literalinclude:: training/test_18/Makefile

- ``test_18/src``: directory where to place the source
- ``test_18/src/Makefile``: Makefile Zephyr will call to build the app

  .. literalinclude:: training/test_18/src/Makefile

  We use the ``$(SUBPHASE)`` append to the file name so we can control
  from the environment which file we compile, as we evolve the
  testcase.

- ``test_18/test.py``: TCF test script integration

  .. literalinclude:: training/test_18/test.py
     :emphasize-lines: 4-5

  The *setup\*()* functions are called before *starting* the targets
  and in this case we setup a hook on the console to fail the testcase
  if we receive a ``FAIL`` string.

When you run it and passes::

  $ tcf run --tmpdir tmp -vvy test_18/
  INFO2/	toplevel @local: scanning for test cases
  INFO1/vdac	test_18/test.py#_test @srrsotc03/qz37g-riscv32:riscv32: will run on target group 'target=srrsotc03/qz37g-riscv32:riscv32'
  PASS2/vdac	test_18/test.py#_test @srrsotc03/qz37g-riscv32:riscv32: configure passed
  PASS1/vdac	test_18/test.py#_test @srrsotc03/qz37g-riscv32:riscv32: build passed
  PASS2/vdac	test_18/test.py#_test @srrsotc03/qz37g-riscv32:riscv32: deploy passed
  INFO2/vdacE#1	test_18/test.py#_test @srrsotc03/qz37g-riscv32:riscv32: Reset
  PASS2/vdacE#1	test_18/test.py#_test @srrsotc03/qz37g-riscv32:riscv32: found expected `PASS` in console `srrsotc03/qz37g-riscv32:default` at 0.62s
  PASS2/vdacE#1	test_18/test.py#_test @srrsotc03/qz37g-riscv32:riscv32: eval pass: found expected `PASS` in console `srrsotc03/qz37g-riscv32:default` at 0.62s
  PASS1/vdac	test_18/test.py#_test @srrsotc03/qz37g-riscv32:riscv32: evaluation passed
  PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

and when it fails::

  $ tcf run --tmpdir tmp -vvy test_18/
  INFO2/	toplevel @local: scanning for test cases
  INFO1/f95t	test_18/test.py#_test @srrsotc03/qz35h-nios2:nios2: will run on target group 'target=srrsotc03/qz35h-nios2:nios2'
  PASS2/f95t	test_18/test.py#_test @srrsotc03/qz35h-nios2:nios2: configure passed
  PASS1/f95t	test_18/test.py#_test @srrsotc03/qz35h-nios2:nios2: build passed
  PASS2/f95t	test_18/test.py#_test @srrsotc03/qz35h-nios2:nios2: deploy passed
  INFO2/f95tE#1	test_18/test.py#_test @srrsotc03/qz35h-nios2:nios2: Reset
  FAIL2/f95tE#1	test_18/test.py#_test @srrsotc03/qz35h-nios2:nios2: eval failed: found expected (for failure) `FAIL` in console `srrsotc03/qz35h-nios2:default` at 0.10s
  FAIL0/f95t	test_18/test.py#_test @srrsotc03/qz35h-nios2:nios2: evaluation failed
  FAIL0/	toplevel @local: 1 tests (0 passed, 1 failed, 0 blocked, 0 skipped) - failed

We are going to evolve this app to see what is in a Zephyr testcase.

Evolving into a TC test case
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Anything can be used to comunicate via the console if it passes or
fails, however, to be consistent and make it easy, Zephyr has
standarized on the *TC* macros and the *ztest* framework; copy
``main.c`` to ``main-b.c`` and edit it adding:

.. literalinclude:: training/test_18/src/main-b.c
   :emphasize-lines: 9, 21, 26-27

Our testing functions are slightly modified (no arguments or return
values) and they just have to call *ztest* functions to indicate a
failure. A suite is declared to tie them all together and launch
it. Error messages will be printed.

.. literalinclude:: training/test_18/test-b.py
   :emphasize-lines: 5-6

Now run::

  $ (export SUBSAMPLE=-c; tcf run --tmpdir tmp -vvvy test_18/test$SUBSAMPLE.py)

(remember that for the sake of brevity in the training, we use the
*SUBSAMPLE* environment variable to select which Python test file
script and which C source files we want to use)

produces::

  ...
  PASS2/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: found expected `PASS` in console `srrsotc03/qc1000-01:default` at 1.17s
  PASS3/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: console output: ***** BOOTING ZEPHYR OS v1.7.99 - BUILD: Jun  4 2017 12:31:00 *****
  PASS3/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: console output: tc_start() - random test
  PASS3/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: console output: ===================================================================
  PASS3/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: console output: PASS - main.
  PASS3/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: console output: ===================================================================
  PASS3/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: console output: RunID: :wpgl
  PASS3/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: console output: PROJECT EXECUTION SUCCESSFUL
  PASS2/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: eval pass: found expected `PASS` in console `srrsotc03/qc1000-01:default` at 1.17s
  ...

The message ``RunID: :wpgl`` from this line::

  PASS3/rmk0E#1	test_18/test.py#_test @srrsotc03/qc1000-01:x86: console output: RunID: :wpgl

will be unique for each combination of testcase name, target group
where it runs and the app itself (in our case *test_18/src*) and it is
always good to verify it was printed to ensure the right image was
found. For that, we can use *target.kws*\'s *tghash* and *runid*
keys:

.. code-block:: python

   target.expect("RunID: %(runid)s:%(tghash)" % target.kws)

Evolving into a ztest test case
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*ztest* is a unit test library, whose API can be found in
*tests/ztest/include*.

Copy ``src/main-b.c`` to ``src/main-c.c`` and introduce the
highlighted modifications:

.. literalinclude:: training/test_18/src/main-c.c
   :emphasize-lines: 9, 11-15, 17-21, 23, 25-29

Thus when a testcase passes, it will print ``PROJECT EXECUTION
SUCCESSFUL`` or ``PROJECT EXECUTION FAILED`` and a few other
messages; copy ``test.py`` to ``test-b.py`` and add:

.. literalinclude:: training/test_18/test-c.py
   :emphasize-lines: 5-7, 9-11

A new configuration setting is needed ``CONFIG_ZTEST``, which we can
do using a *build* method or by modifying ``prj.conf``.

Runing a case that fails::

  $ (export SUBSAMPLE=-c; ~/z/v0.11-tcf.git/tcf run --tmpdir tmp -vyvvvv test_18/test$SUBSAMPLE.py)
  INFO1/tgdh	test_18/test-c.py#_test @local/qz30a-x86:x86: will run on target group 'target=local/qz30a-x86:x86'
  PASS2/tgdh	test_18/test-c.py#_test @local/qz30a-x86:x86: configure passed
  PASS1/tgdh	test_18/test-c.py#_test @local/qz30a-x86:x86: build passed
  PASS2/tgdh	test_18/test-c.py#_test @local/qz30a-x86:x86: deploy passed
  INFO2/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: Reset
  PASS2/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: found expected `RunID: :5ohy` in console `local/qz30a-x86:default` at 0.05s
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: ***** BOOTING ZEPHYR OS v1.7.99 - BUILD: Jun  4 2017 17:36:02 *****
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: Running test suite test_18
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: tc_start() - run_some_test1
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: ===================================================================
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: PASS - run_some_test1.
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: tc_start() - run_some_test2
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: ===================================================================
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: PASS - run_some_test2.
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: ===================================================================
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: RunID: :5ohy
  PASS3/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: console output: PROJECT EXECUTION SUCCESSFUL
  PASS2/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: eval pass: found expected `RunID: :5ohy` in console `local/qz30a-x86:default` at 0.05s
  ...
  PASS2/tgdhE#1	test_18/test-c.py#_test @local/qz30a-x86:x86: found expected `PROJECT EXECUTION SUCCESSFUL` in console `local/qz30a-x86:default` at 0.05s
  ...
  PASS1/tgdh	test_18/test-c.py#_test @local/qz30a-x86:x86: evaluation passed
  PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Change of pace, input to a Zephyr test case
-------------------------------------------

Let's play with a Zephyr shell example:

.. literalinclude:: training/test_17.py
   :emphasize-lines: 8, 15, 17

- you can use shell based apps to implement *multiple* test cases on a
  single Zephyr app using the *TC* framework.

- Use :meth:`target.send <tcfl.tc.target_c.send>` to send data to the
  target's console, as if you were typing it.

::

   $ tcf run --tmpdir tmp -yvv test_17.py
   INFO2/	toplevel @local: scanning for test cases
   INFO1/3daq	test_17.py#_test @local/qz36a-arm:arm: will run on target group 'target=local/qz36a-arm:arm'
   PASS2/3daq	test_17.py#_test @local/qz36a-arm:arm: configure passed
   PASS1/3daq	test_17.py#_test @local/qz36a-arm:arm: build passed
   PASS2/3daq	test_17.py#_test @local/qz36a-arm:arm: deploy passed
   INFO2/3daqE#1	test_17.py#_test @local/qz36a-arm:arm: Reset
   PASS2/3daqE#1	test_17.py#_test @local/qz36a-arm:arm: found expected `shell>` in console `local/qz36a-arm:default` at 0.05s
   PASS2/3daqE#1	test_17.py#_test @local/qz36a-arm:arm: eval pass: found expected `shell>` in console `local/qz36a-arm:default` at 0.05s
   INFO2/3daqE#1	test_17.py#_test @local/qz36a-arm:arm: wrote 'select sample_module' to console 'local/qz36a-arm:<default>'
   PASS2/3daqE#1	test_17.py#_test @local/qz36a-arm:arm: found expected `sample_module>` in console `local/qz36a-arm:default` at 0.05s
   PASS2/3daqE#1	test_17.py#_test @local/qz36a-arm:arm: eval pass: found expected `sample_module>` in console `local/qz36a-arm:default` at 0.05s
   PASS1/3daq	test_17.py#_test @local/qz36a-arm:arm: evaluation passed
   PASS0/	toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Note how now, you can acquire the target and interact with it::

  $ tcf acquire qz36a-arm
  $ tcf console-write -i qz36a-arm
  WARNING: This is a very limited interactive console
           Escape character twice ^[^[ to exit

  shell> shell> select sample_module	# This was typed by the testcase
  sample_module> help		        # I typed this 'help'
  help
  ping
  params
  sample_module> ping                   # Same with 'ping'
  pong
  sample_module>

.. warning::

   Make sure it is on and it is not taken away from you in the middle
   due to inactivity, a trick for that is to run::

     tcf acquire qz36a-arm --hold

   *cancel it* when you are done, otherwise others won't be able to use
   it.

.. note:: the interactive console is quite limited; plus some targets
          (QEMU) have a tendency to drop characters or not echo input,
          some stop working half way (SAMe70).


FIXME: Missing
--------------

- USB
  - console
  - mount
- Power
- Network
- Network + tunnel
- Network + linux
