.. _tcf_guide_report_driver:

Report Drivers
==============

A report driver is what gets called to report information by the
different components of the TCF client test runner.

The APIs that are the entry points for reporting are:

- target :class:`object <tcfl.tc.target_c>`:
  :meth:`report_info <tcfl.tc.target_c.report_info>`,
  :meth:`report_pass <tcfl.tc.target_c.report_pass>`,
  :meth:`report_fail <tcfl.tc.target_c.report_fail>`,
  :meth:`report_blck <tcfl.tc.target_c.report_blck>`,
  :meth:`report_skip <tcfl.tc.target_c.report_skip>`
- testcase :class:`object <tcfl.tc.tc_c>`:
  :meth:`report_info <tcfl.tc.tc_c.report_info>`,
  :meth:`report_pass <tcfl.tc.tc_c.report_pass>`,
  :meth:`report_fail <tcfl.tc.tc_c.report_fail>`,
  :meth:`report_blck <tcfl.tc.tc_c.report_blck>`,
  :meth:`report_skip <tcfl.tc.tc_c.report_skip>`

The system provides default drivers that report to the console and a
log file, as well as create report files with results of failures.

To create a new driver, one can override
:class:`tcfl.report.report_c`:

.. code-block:: python

   #! /usr/bin/env python
   import tcfl.report

   class report_ex_c(tcfl.report.report_c):
       def _report(self, level, alevel, ulevel, _tc, tag, message, attachments):
           print "REPORTING ", level, alevel, _tc, tag, message, attachments

   tcfl.report.report_c.driver_add(report_ex_c("results.log"))

with the following being:

 - *level* is the verbosity level of the message; note report levels
   greater or equal to 1000 are using to pass control messages, so
   they shall not be subject to normal verbosity control.
 - *alevel* is the verbosity level at which the attachments are
   reported
 - *ulevel* is deprecated
 - *_tc* is the :class:`tcfl.tc.tc_c` or :class:`tcfl.tc.target_c`
   object that is reporting
 - *tag* is a string *PASS*, *FAIL*, *BLCK*, *SKIP* or *INFO*,
   indicating what condition is being reported.
 - *message* is the message the caller is reporting; if it starts with
   *"COMPLETION "*, this is the final message issued to recap the
   result of executing a single testcase.
 - *attachments* a dictionary keyed by strings of objects that the
   reporter decided to pass as extra information

.. warning:: This function will be called for *every* single report
   the internals of the test runner and the testcases do from multiple
   threads at the same time, so it makes sense to protect for
   concurrency if accessing shared resources or to ignore high log
   levels.

From these functions basically anything can be done--but they being
called frequently, it has to be efficient or will slow testcase
execution considerably. Actions done in this function can be:

- filtering (to only run for certain testcases, log levels, tags or
  messages)
- dump data to a database
- record to separate files based on whichever logistics
- etc

Example 1: reporting completion of testcase execution
-----------------------------------------------------

For example, to report all the testcases that finalize to a file
called *results.log*, consider :download:`this example
<../examples/conf_report_ex.py>`:

.. literalinclude:: ../examples/conf_report_ex.py

note how this example:

- creates the file with a timestamp when the driver is initialized in
  the *__init__* method

- skips any reporter that has a *skip_reports* attribute

- acts only on testcase completion by looking for the *COMPLETION*
  string at the beginning of the message

- correctly assumes the testcase might be assigned none, one or more
  targets, depending on the testcase -- it merely walks the list of
  targets assigned to the testcase to print information about them as
  needed.

- accesses a shared resource (the file) by taking a lock, making sure
  only one thread is accessing it at the same time, to avoid
  corruption.

- registers the driver instantiating the class


Example 2: reporting failures
-----------------------------

The builtin :download:`report failure driver <../tcfl/report.py>`
works similarly, but collecting information as we go to differerent
files for each testcase instantiation. When the testcase completes, it
writes a single report with all the information using the same method
as we described in the first example.

See :class:`tcfl.report.file_c`.
