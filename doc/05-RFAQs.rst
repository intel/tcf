=========================================
Rationales and Frequently Asked Questions
=========================================

TCF is OS and test target agnostic
==================================

Whatever your test target is (an MCU, a PC, a toaster), TCF doesn't
care.

All the functionality is implemented by interfaces and drivers. The
only thing TCF does is (on the server side) manage access to the
targets and proxy requests via HTTP. On the client side, it just
launches tests however you tell him to do via the markup language of
choice to describe test cases.

.. _separated_networks:

Separated networks for infrastructure and test target hardware
==============================================================

If you have test targets connected to the same network switch as (for
example) your power controllers, security issues are introduced.

An attacker could deploy a rogue image to a test node, sniff the
traffic in the network and gather access to the power switches (which
don't have, in general, good security), thus disrupting the operation
and creating potential hazards.

Thus, the best deployment practice is to keep them in two separate and
isolate networks. This can also be accomplished with smart switches,
but it is out of the scope of this document.


.. _arduino101_rationale:

MCU test fixture for highest reliabiltiy
========================================

The fixture described in :func:`conf_00_lib_mcu.arduino101_add` can be
considered complicated, but it is designed for maximum reliability
when running thousands of test cases. These same points apply to other
(most) MCUs under test.

* Current leaks

  The board is so sensitive to current leakage that it will be
  residually powered on even when just connecting the serial
  console. This will charge some capacitors. Then it will work for a few
  millisecs, enough to print some trash to the serial console and die.

  All the components have to be connected to the same ground to avoid
  derivations, which means to the same YKUSH switchable USB hub and
  then powered up and down in an specific order via a power rail.

* Why power off everthing? Why not just power off the board?

  It has been found via experimentation that sometimes the only way to
  fully reset an Arduino 101 (and any MCU for that matter) is to
  completely disconnect every cable and let it sit for a few seconds.

  This is related to the previous point, current leakage can disallow
  the board ressetting properly.

  Humans can do this by disconnecting all the cables; the automation
  system does it by having all this power cutters completely isolating
  the board.

* Question: (on Zephyr) I’m a little confused why I actually need to
  power cycle the Arduino, when I compile zephyr and flash using ``make
  BOARD=Arduino_101_factory flash`` I don’t need [any hardware] to
  power it down...  Zephyr ``make flash`` seems to be using OpenOCD just
  like TCF.

  It does, and it is misleadingly simple.

  When doing ``make flash``, there is an OpenOCD-driven reset that is
  done there; if it doesn’t work, a human retries, if it doesn’t work
  again, the mailing list wisdom has been `disconnect every single
  cable to the board, let it rest a few seconds, reconnect again,
  retry`.

  TCF does the same, but faster and without your intervention, but for
  that it needs hardware.

  TCF is designed to run tests cases with no human intervention, one
  after another as fast as possible. If it fails, it recovers. In
  order to do that, reliably, the board has to be fully reset. And for
  that it uses that hardware.

* Why power off the USB bus versus the barrel?

  The choice to use USB is that in most setups, power comes from USB
  anyway and there is no real reason to use the barrel.

  It simplifies the cabling too. Using the barrel you have to make
  sure that the power is connected to the same power switch as the hub
  where the MCU is connected to avoid ground power derivation.

  As well, if you choose to use the barrel and USB, then note either
  will power it, so when the power rail powers up the target,
  whichever USB power controller or the barrel power controller is
  turned on first will power the whole board up.

High cost of fixtures
=====================

All the extra hardware needed to run the fixtures can get expensive:

 - ~$40 for an YKUSH hub and cables

 - ~$130 for a DLWPs7 if deciding to implement full power control

however, it needs to be put inperspective:

- the cost of the infrastructure is spread across the test targets

- humans take a long time to do things: reconnecting all cables for a
  solid power cycle a few times a day will add up to a lot of time

- removal of the human error factor: which can lead to false positives
  and negatives which will cause extra resource consumption on
  diagnosis

- reduce wear and tear: plugging and unplugging wears the boards down,
  loosens connectors and deceases the life expectancy of the hardware

The cost of investing full automation is rapidly offset by the
savings in human time (and their burn rate) and increased efficiency.

.. note:: time spent looking around for cables is wasted money; order
  in bulk and have spares.

Zephyr
======

``tcf run -s`` will not filter a Zephyr subcase
-----------------------------------------------

When trying to filter with ``-s`` a :class:`Zephyr SanityCheck
<tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c>` style
:class:`subcase <tcfl.tc_zephyr_sanity.tc_zephyr_subsanity_c>`
nothing gets executed; trying to filter
``zephyr.git/tests/libc/c_lib/testcase.yaml#libraries.libc.strcmp``::

  $ tcf run -vvv -t 'jfsotc05/esp32-42' -s 'name:".*zephyr.git/tests/lib/c_lib/testcase.yaml#libraries.libc.strcmp$"' zephyr.git/tests/lib/c_lib/testcase.yaml
  INFO3/	toplevel @local: version 0.11-75-g5ebea2f
  INFO2/	toplevel @local: scanning for test cases
  E tc.testcases_discover():5890: All testcases skipped or filtered out by command line -s options
  SKIP0/	toplevel @local: 1 tests (0 passed, 0 error, 0 failed, 0 blocked, 1 skipped, in 0:00:00.104572) - skipped

yields nothing, while if we remove the trailing ``.strcmp`` and filter
for it ``zephyr.git/tests/libc/c_lib/testcase.yaml#libraries.libc``::

  $ tcf run -vvv -t 'jfsotc05/esp32-42' -s 'name:".*zephyr.git/tests/lib/c_lib/testcase.yaml#libraries.libc$"' zephyr.git/tests/lib/c_lib/testcase.yaml
  ...

it runs all the testcases under ``zephyr.git/tests/libc/c_lib/testcase.yaml#libraries.libc``

So it is effectively not possible to filter for a Zephyr subcase. This
is because it is part of a bundle of testcases that can only be run as
a bundle.

**Technical details**

1. Zephyr sanity checks are a container of multiple subcases.

2. When they run, they always run all the subcases
   tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.eval_50() and capture the
   output.

3. They then parse the subcases on the teardown path
   func:`tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.teardown_subtestcases`.

   This is done by looking out the captured output and *fake* subcases
   are created and executed when the container is done in sequence by
   the function ``tcfl.tc.tc_c._run()`` which just say the testcase
   passed/failed (no actual physical running is done)

4. Then we extract KPIs
   :func:`tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.teardown`.

So, ``...testcase.yaml#libraries.libc.strcmp`` is a subcase of
``...testcase.yaml#libraries.libc``, which means it is *fake*, it is not
really running, so it can't really be filtered out as it is a
subproduct of the output. Hence why ``-s`` is not filtering it, as it
only filters against the testcases when loading them.

Now the ``libraries.libc`` part works because it becomes part of the
testcase name when loading
(``zephyr.git/tests/lib/c_lib/testcase.yaml#libraries.libc``); this is
done by :func:`tcfl.tc_zephyr_sanity.tc_zephyr_sanity_c.is_testcase`
(with ``_testcasesample_yaml_mktcs()`` function) when discovering the
``testcase.yaml`` file.
