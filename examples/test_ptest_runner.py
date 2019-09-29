#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Proprietary
#
# pylint: disable = missing-docstring
""".. _example_ptest_runner:

Impromptu testcase driver to execute and report Yocto/OE ptest-runner testcases
===============================================================================

This is a simple driver for executing Yocto/OE testcases, which are
usually installed in the system already.

The testsuites available can be listed with::

  ptest-runner -l
  Available ptests:
  acl	/usr/lib/acl/ptest/run-ptest
  attr	/usr/lib/attr/ptest/run-ptest
  bash	/usr/lib/bash/ptest/run-ptest
  bluez5	/usr/lib/bluez5/ptest/
  ...

Each suite contains one or more subcases, so the layout is like:

  - TESTSUITE1
    - SUBCASE1
    - SUBCASE2
    - SUBCASE2
    - ...
  - TESTSUITE2
    - SUBCASE1
    - ...
  - TESTSUITE3
    - SUBCASE1
    - SUBCASE2
    - ...
  - ...

Subcases will be reported as described in :ref:<example_subcases>, but
because we have no way to discover the number of subcases (before or
after provisioning, powering on and contacting the system), the total
number of reported testcases will vary wildly if the system cannot be
provisioned or powered on or if the testcase execution timesout.

Note this also servers as an example of an :term:`impromptu test driver
<impromptu test case driver>`.

To execute, :download:`the testcase
<../examples/test_ptest_runner.py>`.

- Find and run all the testsuites installed in the target::

  $ IMAGE=yocto:core-image-sato-sdk-ptest \
    tcf run -v test_ptest_runner.py

- run testsuites *zlib* and *gzip* only::

  $ IMAGE=yocto:core-image-sato-sdk-ptest \
    tcf run -v test_ptest_runner.py#zlib#gzip

- run testsuites *zlib* and *gzip* on one side and *valgrind* and
  *bash* in another::

  $ IMAGE=yocto:core-image-sato-sdk-ptest \
    tcf run -v test_ptest_runner.py#zlib#gzip test_ptest_runner.py#valgrind#bash

(where *IMAGE* is the name of a Yocto Linux OS image
:ref:`installed in the server <pos_list_images>`).

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""

import codecs
import os
import subprocess
import re
import traceback

import commonl
import tcfl.tc


#:
#: Timeouts per suite name (in seconds)
#:
#: When the default is too short, or needs ajustment
timeouts = {
    "bash": 120,
    "lzo": 60,
    "mdadm": 240,
    "valgrind": 300,
}

#:
#: Default timeout (seconds) to execute a ptest
#:
timeout_default = 30

class _driver(tcfl.pos.tc_pos_base):

    def _output_parse(self, testsuite, suite_tc, lf):

        #
        # Parse the log file out of running a single test suite; the
        # file format is more or less
        #
        # START: ptest-runner
        # <timestamp>
        # BEGIN: <suite>
        # <output for subtc>
        # FAIL|SKIP|PASS: <subtc>
        # <output for subtc>
        # FAIL|SKIP|PASS: <subtc>
        # <output for subtc>
        # FAIL|SKIP|PASS: <subtc>
        # DURATION: <n>
        # END: <suite>
        # <timestamp>
        # STOP: ptest-runner
        #
        result = tcfl.tc.result_c()
        cnt = -1
        start_seen = False
        suite = None
        log = ""
        date_regex = re.compile("^[-:T0-9]+$")	# lazy YYYY-MM-DDTHH:MM
        for line in lf:
            line = line.rstrip()
            cnt += 1
            if line.startswith("START: "):
                _, name = line.split(None, 1)
                assert name == 'ptest-runner', \
                    "%d: Found START for %s, not ptest-runner" % (cnt, name)
                start_seen = True
            elif line.startswith("STOP:"):
                assert start_seen, "%d: Found STOP: without START" % cnt
                _, name = line.split(None, 1)
                assert name == 'ptest-runner', \
                    "%d: Found STOP for %s, not ptest-runner" % (cnt, name)
                start_seen = False
            elif date_regex.search(line):
                pass	# ignored
            elif line.startswith("BEGIN:"):
                assert start_seen, "%d: Found BEGIN: without START" % cnt
                _, suite = line.split(None, 1)
                if suite != testsuite \
                   and testsuite not in suite:	# /usr/lib/SUITE/ptest HACK
                    raise AssertionError(
                        "%d: Found BEGIN: for %s, expected %s" \
                        % (cnt, suite, testsuite))
                log = ""
            elif line.startswith("END:"):
                assert start_seen, "%d: Found END: without START" % cnt
                assert suite, "%d: Found END: without suite" % cnt
                _, _suite = line.split(None, 1)
                assert suite == _suite, \
                    "%d: Found END: for suite %s different to" \
                    " START:'s %s" % (cnt, _suite, suite)
                suite = None
            elif line.startswith("PASS:") \
                 or line.startswith("FAIL:") \
                 or line.startswith("SKIP:"):
                tag, subcase = line.split(None, 1)
                assert start_seen, "%d: Found %s without START" % cnt
                assert suite, "%d: Found %s without suite" % cnt
                # some tests print names that are ...hummm...useless
                subcase_safe = commonl.name_make_safe(subcase)
                if tag == "PASS:":
                    _result = tcfl.tc.result_c(passed = 1)
                elif tag == "FAIL:":
                    _result = tcfl.tc.result_c(failed = 1)
                elif tag == "SKIP:":
                    _result = tcfl.tc.result_c(skipped = 1)
                else:
                    raise AssertionError("unknown tag from command output '%s'"
                                         % tag)
                #
                # Create a subtestcase with the information we found
                # about the execution of this SUBCASE of this SUITE
                #
                name = self.name + "##%s/%s" % (testsuite, subcase_safe)
                subtc = tcfl.tc.subtc_c(name, self.kws['thisfile'],
                                        suite, self)
                subtc.update(_result, line, log)
                result += _result
                self.subtc[subcase] = subtc
                log = ""
            elif line.startswith("DURATION:"):
                pass	# ignored
            else:
                log += line + "\n"

        # well, we done -- check thinks are as they should be, test
        # closed and all
        if suite_tc.result:
            # no wait, we have already updated the suite testcase
            # data; this was probably a timeout, so we know bad stuff
            # happened 
            return
        if suite:
            # this should have been closed by a END: tag
            result.errors += 1
            suite_tc.update(result,
                            "testsuite probably didn't complete"
                            " execution, no END tag", log)
        elif start_seen:
            # this should have been closed by a STOP tag
            result.errors += 1
            suite_tc.update(result,
                            "testsuite probably didn't complete"
                            " execution, no STOP tag", log)
        else:
            result.passed += 1
            lf.seek(0, 0)
            suite_tc.update(result, "testsuite completed execution",
                            lf.read())


    def eval_00(self, ic, target):

        target.shell.shell_prompt_regex = re.compile("PTEST-PROMPT% ")
        target.shell.run(
            "export PS1='PTEST-PROMPT% '  # a simple prompt is "
            "harder to confuse with general output")

        if not self.subcases:
            # no testsuites given, discover and use those
            #
            ## ptest-runner -l
            ## Available ptests:
            ## acl	/usr/lib/acl/ptest/run-ptest
            ## attr	/usr/lib/attr/ptest/run-ptest
            ## bash	/usr/lib/bash/ptest/run-ptest
            ## bluez5	/usr/lib/bluez5/ptest/
            ## ...
            #
            # there is a tab (\t) separating, we use that
            output = target.shell.run("ptest-runner -l", output = True)
            for line in output.splitlines():
                line = line.rstrip()
                if '\t' not in line:
                    # lists
                    continue
                testsuite, _path = line.split("\t", 1)
                self.subcases.append(testsuite)

        # check if stdbuf is available to use it if so
        output = target.shell.run(
            "stdbuf --help > /dev/null || echo N''OPE # stdbuf available??",
            output = True, trim = True)
        if 'NOPE' in output:
            stdbuf_prefix = ""
        else:
            # run the command prefixing this to reduce the
            # buffering; otherwise suites that take too long will
            # see their ouput buffered in tee and
            # resulting in timeouts expecting progress
            # stdbuf is part of GNU coreutils, so most places have
            # it installed.
            stdbuf_prefix = "stdbuf -o 0 "	# mind the trailing space

        target.shell.run("rm -rf logs && mkdir logs")
        for testsuite in self.subcases:
            offset = target.console.size()
            timeout = timeouts.get(testsuite, timeout_default)
            # suite_tc -> overall result of the whole testsuite execution
            suite_tc_name = self.name + "##" + testsuite
            suite_tc = tcfl.tc.subtc_c(suite_tc_name, self.kws['thisfile'],
                                       testsuite, self)
            self.subtc[testsuite] = suite_tc
            try:
                target.report_info("running testsuite %s" % testsuite)
                # run the testsuite and capture the output to a log file
                # HACK: ignore errors, so we can cancel on timeout
                # without it becoming a mess -- still
                target.shell.run(
                    stdbuf_prefix
                    + 'ptest-runner %s 2>&1 | tee logs/%s.log || true'
                    % (testsuite, testsuite), timeout = timeout)
            except tcfl.tc.error_e as e:
                # FIXME: this is a hack, we need a proper timeout exception
                if "NOT FOUND after" not in str(e):
                    raise
                # if we timeout this one, just cancel it and go for the next
                message = "stopping testsuite %s after %ds timeout" \
                    % (testsuite, timeout)
                target.report_error(message)
                # suspend -- Ctrl-Z & kill like really harshly
                target.console_tx("\x1a\x1a\x1a")
                target.expect("SIGTSTP")
                target.shell.run("kill -9 %% || true")	# might be dez already
                suite_tc.update(tcfl.tc.result_c(errors = 1),
                                message, target.console.read(offset = offset))

        # bring the log files home; SSH is way faster than over the console
        target.shell.run('tar cjf logs.tar.bz2 logs/')
        target.tunnel.ip_addr = target.addr_get(ic, "ipv4")
        target.ssh.copy_from("logs.tar.bz2", self.tmpdir)
        subprocess.check_output(
            [ "tar", "xf", "logs.tar.bz2" ],
            stderr = subprocess.STDOUT, cwd = self.tmpdir)

        # cat each log file to tell what happened? we know the log
        # file names, so we can just iterate in python -- in other
        # cases, we might have to list files in the target to find the
        # log files, or scan through a big log file that has
        # indications of where the output for one subcase start and
        # ends.
        for testsuite in self.subcases:
            suite_tc = self.subtc[testsuite]
            try:
                with codecs.open(
                        os.path.join(self.tmpdir, "logs", "%s.log" % testsuite),
                        encoding = 'utf-8', errors = 'replace') as lf:
                    target.report_info("parsing logs for testsuite %s"
                                       % testsuite)
                    self._output_parse(testsuite, suite_tc, lf)
            except Exception as e:
                # something wrong in parsing the log file; note it
                suite_tc.update(tcfl.tc.result_c(blocked = 1),
                                str(e), traceback.format_exc())


        # now when this testcase is done executing, the subcases are
        # going to be executed following and they will just report
        # their result individually.
        result = tcfl.tc.result_c()
        for _, subtc in self.subtc.iteritems():
            result += subtc.result
        # if some sub testcase fails, we want the top level to fail
        return result
