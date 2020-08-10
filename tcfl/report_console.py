#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""Report to console and logfile
-----------------------------

:class:`tcfl.report_console.driver` generates reports for human
consumption to the console and optionally a logfile testcase, showing
realtime progress and output.

The verbosity to console is controllable from the command line; the
number of *-v* in *tcf run -vvv* is fed to this driver; the messages
show in realtime as they are produced.

This driver can also produce detailed output to a log file (which can
optionably be compressed to save space, since they tend to grow).  See
:data:`driver.compress` to understando how to add compression methods
and examine the log file as it is being created.

.. _tcf_run_output_groking:
.. _report_console_format:

Each line printed in the console (and log file) follows the format::

  TAG<N>/CODE TESTCASENAME @LOCATION TIME MESSAGE

So, for example, when running the Zephyr *Hello World!* sample in a
target called *qz39c-arm* in the local server, the output could be::

  $ tcf run -vv -t local/qz39c-arm test_zephyr_hello_world.py
  INFO2/	  toplevel @local: scanning for test cases
  INFO2/n9gcf3	  test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: will run on target group 'xqkw (target=local/qz39c-arm:arm)'
  PASS1/n9gcf3	  test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: configure passed
  PASS1/n9gcf3	  test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: build passed
  PASS2/n9gcf3	  test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: deploy passed
  INFO2/n9gcf3E#1 test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: Reset
  PASS2/n9gcf3E#1 test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: found expected `Hello World! arm` in console `default` at 0.03s
  PASS2/n9gcf3E#1 test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: eval pass: found expected `Hello World! arm` in console `default` at 0.03s
  PASS1/n9gcf3	  test_zephyr_hello_world.py#_test @local/qz39c-arm:arm: evaluation passed
  PASS0/	  toplevel @local: 1 tests (1 passed, 0 failed, 0 blocked, 0 skipped) - passed

Note the columns and the messages:

- *TAG* is:

  - *INFO*, information
  - *PASS*, *FAIL*, *ERRR*, something passed, failed to pass or errored
  - *BLCK* infrastructure issue
    errored or an infrastructure
  - *SKIP* something was skipped
  - *DATA* data was collected and now is being reported

- *<N>*, a verbosity number (0 most general, 1 more detailed, 2 more
  verbose, etc)

- *CODE* such as ``/XXXXXX[CBDEL].NN``, where XXXXXX is the
  :term:`hashid`. The letters ``CBDEL`` describe which phase it us
  running (Configure, Build, Deploy, Evaluation, cLean), followed by
  the step number when they are being executed.

  What is this useful for? Well, you can ask the system to generate a
  log file (using `--log-file FILE.log`) and just let it print the
  most high level information to the console. The log has *way* more
  information than you would ever care for, but when something fails,
  grep for the message ID in the logfile (for example, if the build
  had failed, ``grep n9gcf3B FILE.log`` would give you the full build
  output for you to determine what is wrong--note the trailing *B*
  after ther hashid. It is also passed to the server, so we can
  identify what the target was doing when.

  .. note:: TCF also generates reports when something fails (look for
            ``report-HASHID.txt``) with all that detailed information.

- *@LOCATION*: testcase name, target name and :term:`BSP model`.

- A message indicating what happened

"""
import io
import os
import subprocess
import sys
import threading

import commonl
from . import msgid_c
from . import tc

class driver(tc.report_driver_c):
    """
    Driver to write progress messages to console and a log file

    :param int verbosity verbosity: maximum verbosity of messages to
      *stdout*

    :param str log_file: (optional) write messages also to the given
      log file name (defaults to *None*).

      If the name ends up in any of the suffixes in :data:`compress`,
      then the log file will be compressed with the program described
      by said entry.

    :param int verbosity_logf: (optional) maximum verbosity to report
      to the logfile; defaults to all of them (see
      :meth:`tcfl.tc.report_driver_c.report`), but on some cases you
      might want to limit to cut on disk consumption.
    """
    def __init__(self, verbosity, log_file = None,
                 verbosity_logf = 999):
        tc.report_driver_c.__init__(self)
        if log_file:
            assert isinstance(log_file, str)

        self.tls = threading.local()

        if log_file:

            _basename, ext = os.path.splitext(log_file)
            if ext in self.compress:	# compressed logfile support
                kws = dict(log_file = log_file)
                # use shell + exec to try to game possible buffering
                # issues w/ Python and blocks
                command = self.compress[ext]
                pipe = subprocess.Popen(
                    "exec " + command % kws + " > '%s'" % log_file,
                    shell = True, stdin = subprocess.PIPE)
                logf = pipe.stdin
                self.logf = commonl.io_tls_prefix_lines_c(
                    self.tls, io.open(pipe.stdin.fileno(), "w"))
            else:
                logf = io.open(log_file, "w+", encoding = 'utf-8',
                               errors = 'replace')
                self.logf = commonl.io_tls_prefix_lines_c(
                    self.tls, logf.detach())
        else:
            self.logf = None
        consolef = io.open(sys.stdout.fileno(), "wb")
        self.consolef = commonl.io_tls_prefix_lines_c(
            self.tls, consolef.detach())
        self.verbosity = verbosity
        self.verbosity_logf = verbosity_logf

    #: Map log file extension to compression program
    #:
    #: Log files in big runs can be huge but we don't want to loose
    #: them or we don't need the whole thing...until we need them.
    #:
    #: Compressing them after the fact is often a pain, so we can
    #: compress them on the run. Each program here takes stdin raw
    #: data and writes compressed data to stdout. It shall stop when
    #: receiving EOF and close it out gracefully, which will also work
    #: if TCF is killed mercilessly.
    #:
    #: New programs can be added with:
    #:
    #: >>> tcfl.report_console.driver.compress[".EXT"] = "program -options"
    #:
    #: Note that you can generate both a compressed and uncompressed
    #: log file by using tee; this is meant for debugging, since the
    #: compressed stream will be buffered by the compression program.
    #:
    #: >>> tcfl.report_console.driver.compress[".xz"] = \
    #: >>>     "tee %(log_file)s.raw | xz -T0 -6qzc",
    #:
    #: Another method is to strace the compression program::
    #:
    #:   $ strace -s 1024 -p PID
    compress = {
        ".bz2": "bzip2 -9qzc",
        ".xz": "xz -T0 -6qzc",
    }


    def _shall_do(self, level):
        console = level <= self.verbosity
        logfile = level <= self.verbosity_logf and level >= 1000
        return console, logfile

    def report(self, reporter, tag, ts, delta,
               level, message,
               alevel, attachments):
        """
        Report messages to the console or logfile in a line-by-line
        format prefixing each line.
        """
        # FIXME: rework the streaming object so it can multiplex the
        # output to two file descriptors *and* decide based on
        # verbosity; this way we do not have to walk the attachmen
        # tree and format twice if the log file is enabled.

        # the prefix to each line is stored in thraed-local-storage
        # (with commonl.tls_prefix_c), where it is picked up by the
        # stream buffer object commonl.io_tls_prefix_lines_c. This,
        # before printing, adds the prefix to each line.
        _prefix = "%s%d/%s\t%s [+%.1fs]: " % (
            tag, level, msgid_c.ident(),
            reporter._report_prefix, delta
        )
        with commonl.tls_prefix_c(self.tls, _prefix):
            console_p, logfile_p = self._shall_do(level)
            message += "\n"
            if console_p:
                self.consolef.write(message)
            if self.logf and logfile_p:
                self.logf.write(message)

        if attachments != None:
            assert isinstance(attachments, dict)
            console_p, logfile_p = self._shall_do(alevel)
            if console_p or logfile_p:
                _aprefix = "%s%d/%s\t%s [+%.1fs]:    " % (
                    tag, alevel, msgid_c.ident(),
                    reporter._report_prefix, delta
                )
                with commonl.tls_prefix_c(self.tls, _aprefix):
                    if console_p:
                        commonl.data_dump_recursive_tls(attachments, self.tls,
                                                        of = self.consolef)
                    if self.logf and logfile_p:
                        commonl.data_dump_recursive_tls(attachments, self.tls,
                                                        of = self.logf)

        self.consolef.flush()
        if self.logf:
            self.logf.flush()
