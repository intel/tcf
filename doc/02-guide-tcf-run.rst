
Running test cases with *tcf run*
=================================

*tcf run* builds and runs one or more testcases in one or more targets
(or in none if the testcase does not require any)::

  $ tcf run

will recursively look for testcases from the current working directory
and try to run them in as many targets as possible. The scanner will
look for files that describe testcases:

 - *test\*.py* :ref:`testcases <tcf_guide_tests>` written in Python

 - *testcase.ini* Zephyr Sanity Check test cases

it can also be pointed to one or more files or directories::

  $ tcf run ../test1.py sub/dir/1 bat/file/testcase.ini

for each testcase, if it needs targets, it evaluates which ones are
available (from the :ref:`configured *ttbd* servers
<tcf_config_servers>`, filtered with *-t* command line options and
more filtering requirements the testcase might impose). Then it
decides in how many it has to run it based on:

- are we asking to run on any target, one of each type, or all
- multiple random permutations of targets doing different roles that
  satisfy the testcase's specifications

Each testcase and unique target (or group of targets) where it is
going to be run is assigned a unique 4 letter identifier (called
*HASH*) which is used to prefix all the messages regarding to it. This
is useful to grep in long logs of multiple testcases and targets.

.. _tcf_run_test_file_exists:

Consider a simple testcase that checks if there is a file called
*thisfile* in the current working directory (and thus requires no
targets):

.. literalinclude:: ../examples/test_file_exists.py

we run it::

  $ tcf run /usr/share/tcf/examples/test_file_exists.py
  FAIL0/2kdb	/usr/share/tcf/examples/test_file_exists.py#_test @local: evaluation failed
  FAIL0/	toplevel @local: 1 tests (0 passed, 1 failed, 0 blocked, 0 skipped) - failed
  /tmp/tcf-Dw7AGw.mk:2: recipe for target 'tcf-jobserver-run' failed
  make: *** [tcf-jobserver-run] Error 1

you can ignore the messages from *make*, they just say *tcf* returned
with an error code--because a testcase failed, as the file *thisfile*
doesn't exist; if you add more *-v*::

  $ tcf run -vv /usr/share/tcf/examples/test_file_exists.py
  INFO2/	toplevel @local: scanning for test cases
  INFO2/2kdb	/usr/share/tcf/examples/test_file_exists.py#_test @local: will run on target group 'local'
  FAIL2/2kdbE#1	/usr/share/tcf/examples/test_file_exists.py#_test @local: eval failed: file 'testfile': does not exist
  FAIL0/2kdb	/usr/share/tcf/examples/test_file_exists.py#_test @local: evaluation failed
  FAIL0/	toplevel @local: 1 tests (0 passed, 1 failed, 0 blocked, 0 skipped) - failed

*tcf* is shy by default, it will only print about something having
failed. See below for a more detailed :ref:`description
<tcf_run_output_groking>` of the output.

Note the :ref:`*HASH* <tc_id>`, in this case *2kdb*, which uniquely
identifies the testcase/local-target combination. If the testcase
fails, a *report-HASH.txt* file is created with failure information
and instructions for reproduction.

Let's create *testfile*, so the test passes::

  $ touch testfile
  $ tcf run /usr/share/tcf/examples/test_file_exists.py
  PASS0/  toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

If some error happens while running the testcase (network connection
failure, or bug in the testcase code), the testcase will be *blocked*;
to diagnose why, add *-v*'s or look at the logfile (if *--logfile* was
given) for all the details; let's copy the example and introduce a
Python error::

  $ cp /usr/share/examples/test_file_exists.py .
  $ echo error >> test_file_exists.py
  $ tcf run test_file_exists.py
  BLCK0/	test_file_exists.py @local: blocked: Cannot import: name 'error' is not defined (NameError)
  E tc.testcases_discover():4484: WARNING! No testcases found
  BLCK0/	toplevel @local: 0 tests (0 passed, 0 failed, 0 blocked, 0 skipped) - / nothing ran

Running Zephyr OS testcases and samples
---------------------------------------

Because we installed the *tcf-zephyr* package, it brings the
dependencies needed to run Zephyr OS testcases and samples; let's run
Zephyr OS's *Hello World* sample::

  $ git clone http://github.com/zephyrproject-rtos/zephyr
  $ cd zephyr
  $ export ZEPHYR_BASE=$PWD
  $ tcf run /usr/share/tcf/examples/test_zephyr_hello_world.py
  PASS0/  toplevel @local: 7 tests (7 passed, 0 failed, 0 blocked, 0 skipped) - passed

This will now build the Zephyr OS's *Hello World* sample app for as
many different Zephyr OS capable targets as it might find, try to run
it there and verify it got the "Hello World!" string back. Note this
might involve a lot of compilation based on how many targets you can
access and it will take more or less based on your machine's power.

Options to *tcf run*
--------------------

There are many options to *tcf run* which you can find with *tcf run
--help*; here is a summary of the most frequent ones:

* **-v** Increases the verbosity of the console output, can be
  repeated for more information

.. _tcf_run_runid:

* **-i** adds a :term:`RunID` (``-i RUNID``), which will be prefixed in
  most messages and reports; it'll also generate a logfile called
  ``RUNID.log`` with lots of low-level details about the
  process. Failure reports will be created in files called
  ``report-RUNID:HASH.txt``, where :term:`hash` is the code that uniquely
  identifies the test case name and the target where it ran.

  This is very useful when running *tcf* from a continuous integration
  engine, such as Jenkins, to identify the reports and runs.

* **--log-file LOGDILE** file to which to dump the log

* **--logdir LOGDIR** directory where to place the log and failure report
  files.

* **-y**: just run once on any target that is available and suitable;
  there is also **-U** to run only in one target of each type and
  **-u** to run on every target, plus a more detailed explanation
  :ref:`here <tcf_target_modes>`.

.. _tcf_target_specs:
.. _target_specification:

- **-t** allows *tcf run* to filter which targets are available to
  select when determining where to run; see :ref:`specifications
  <tcf_evaluation_expressions>`.

- **-s** allows *tcf run* to filter which testcases are to be run; see
  :ref:`specifications <tcf_evaluation_expressions>`::

    $ tcf run -s slow

  This selects all testcases that have a *slow* tag; to select
  testcases that don't sport the *slow* tag::

    $ tcf run -s "not slow"

  you can also select a tag by value::

    $ tcf run -s 'slow == "very"'

.. _tcf_evaluation_expressions:

Target and tag filter specifications
------------------------------------

TCF incorporates a simple expression language parser to allows to
express boolean filters to select targets and tags in a programatic
way, such as::

  tag == 'value' and bsp in [ 'x86', 'arm' ]

and is used by *tcf run*'s *-t* and *-s* options, to select targets
and testcases, respectively. As well, testcases can use in the
:func:`tcfl.tc.target` and :func:`tcfl.tc.interconnect` decorators to
select tags.

The grammar is formally defined in :mod:`commonl.expr_parser`, but in
general an valid expressions are:

- *symbol*
- *symbol operator CONSTANT*
- *symbol in [ CONTANT1, CONSTANT2 ... ]*
- *[not] ( [not] expresion1 and|or [not] expression2 )*
- operators are *and*, *or*, *not*, ==, !=, <, >, >= and <=
- Python regex matching can be done with *:*

For targets, the target's name and full IDs are made symbols that
evaluate as True; other symboles added are the active :term:`BSP
model` and (if any) active BSP are also made symbols, so for given a
target named *z3* with the following tags::

  $ tcf list -vvv z3
    https://SERVER:5000/ttb-v0/targets/z3
      ...
      fullid: SERVER/z3
      id: z3
      consoles: [u'arm']
      fullid: https://SERVER:5000/z3
      owner: None
      bsps: {
        u'arm': {
          u'console': u'arm',
          u'zephyr_board': u'qemu_cortex_m3',
          u'zephyr_kernelname': u'zephyr.elf',
        }
      }
      ....

The following expressions could be used to match it::

- ``bsp == 'arm'``
- ``z3 or z1``
- ``zephyr_board in [ 'qemu_cortex_m3', 'frdm_k64f' ]``

The same system applies for tag; the tag itself is a symbol that
evaluates to true if available. It's contents are available for
matching.

Examples of specifications
~~~~~~~~~~~~~~~~~~~~~~~~~~

these examples can be passed to *tcf run -t* or :func:`tcfl.tc.target`
and :func:`tcfl.tc.interconnect` in their *spec* parameter::

  'type == "arduino101"'

filters to any target that declare's its type is *Arduino 101*::

  'bsp == "x86"'

any target (and :term:`BSP model` of said target) that sports an x86
BSP--if the target supports multiple BSPs and BSP models, then it will
select all the BSP models that expose at least an 'x86' BSP)::

  'zephyr_board : "quark_.*"'

this selects any target that contains a BSP that exposes a
*zephyr_board* tag whose content matches the Python regex *quark_.\**;
this::

  'bsp == "x86" or bsp == "arm"'
  'bsp in [ "x86", "arm" ]'

would run on any target that contains a BSP that declares itself as
*x86* or *ARM*::

   'TARGETNAME'

would match a target called *TARGETNAME* (in any server)::

   'server/TARGETNAME'

would match *TARGETNAME* on server *server*::

   'nwa or qz31a or ql06a'

This will allow only to run in network *nwa* and in targets *qz31a*
and *ql06a*; this effectively limits the testcase to run only in
permutations of targets that fit those limitations.
