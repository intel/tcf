.. _tcf_guide_report_driver:

Report Drivers
==============

A report driver is what gets called to report information by the
different components of the TCF client test runner.

A new driver is created by subclassing
:class:`tcfl.tc.report_driver_c` and adding an instance of it to the
reporting system:

>>> class myclass_c(tcfl.tc.report_driver_c):
>>>     def report(self, level, alevel, ulevel, _tc, tag, message, attachments):
>>>         print "REPORTING ", level, alevel, _tc, tag, message, attachments
>>>
>>> driver_instance = myclass_c()
>>> tcfl.tc.report_driver_c.add(driver_instance)

The reporting API (:class:`tcfl.tc.reporter_c`) calls for each driver
the low level reporting entry point, function
:meth:`tcfl.tc.report_driver_c.report`, which needs to be created by
each driver.

Read on about reporting drivers provided by default

.. automodule:: tcfl.report_console
.. automodule:: tcfl.report_elastic
.. automodule:: tcfl.report_jinja2
.. automodule:: tcfl.report_mariadb
.. automodule:: tcfl.report_mongodb
.. automodule:: tcfl.report_taps


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

The builtin :download:`report Jinja2 <../tcfl/report_jinja2.py>`
works similarly, but collecting information as we go to differerent
files for each testcase instantiation. When the testcase completes, it
writes a single report with all the information using the same method
as we described in the first example.
