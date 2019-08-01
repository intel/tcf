#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Returning results
=================

Testcases can return :data:`five results <tcfl.tc.valid_results>` to
the testcase runner:

- pass
- fail
- error
- blockage
- skip

Note that any function that:

- just returns or returns *True* is a **pass**

- returns *False* is a **failure**

- any other return value other than :class:`tcfl.tc.result_c` will yield
  blockage, as it cannot be interpreted.

By raising an exception at any time in your testcase, the execution is
terminated, cleanup methods called and the results / collaterals that
apply collected.

This example generates a random result, running only in the local
host (it is a :term:`static testcase`):

.. literalinclude:: /examples/test_yielding_results.py
   :language: python
   :pyobject: _test_pass

.. literalinclude:: /examples/test_yielding_results.py
   :language: python
   :pyobject: _test_errr

.. literalinclude:: /examples/test_yielding_results.py
   :language: python
   :pyobject: _test_fail

.. literalinclude:: /examples/test_yielding_results.py
   :language: python
   :pyobject: _test_blck

.. literalinclude:: /examples/test_yielding_results.py
   :language: python
   :pyobject: _test_skip

Execute :download:`the testcase <../examples/test_yielding_results.py>` with::

  $ tcf run -vv /usr/share/tcf/examples/test_yielding_results.py
  INFO2/	toplevel @local: scanning for test cases
  INFO1/zom6	.../test_yielding_results.py#_test_pass @localic-localtg: will run on target group 'localic-localtg'
  INFO1/kvkn	.../test_yielding_results.py#_test_blck @localic-localtg: will run on target group 'localic-localtg'
  INFO1/rnpd	.../test_yielding_results.py#_test_skip @localic-localtg: will run on target group 'localic-localtg'
  INFO1/enpe	.../test_yielding_results.py#_test_fail @localic-localtg: will run on target group 'localic-localtg'
  INFO1/ap2n	.../test_yielding_results.py#_test_errr @localic-localtg: will run on target group 'localic-localtg'
  PASS2/zom6E#1	.../test_yielding_results.py#_test_pass @localic-localtg: I am causing a pass by raising
  PASS2/zom6E#1	.../test_yielding_results.py#_test_pass @localic-localtg: eval passed: I passed
  PASS1/zom6	.../test_yielding_results.py#_test_pass @localic-localtg: evaluation passed 
  BLCK2/kvknE#1	.../test_yielding_results.py#_test_blck @localic-localtg: I am causing a blockage by raising
  BLCK2/kvknE#1	.../test_yielding_results.py#_test_blck @localic-localtg: eval blocked: I blocked
  BLCK0/kvkn	.../test_yielding_results.py#_test_blck @localic-localtg: evaluation blocked 
  SKIP2/rnpdE#1	.../test_yielding_results.py#_test_skip @localic-localtg: I am causing a skip by raising
  SKIP2/rnpdE#1	.../test_yielding_results.py#_test_skip @localic-localtg: eval skipped: I skipped
  SKIP1/rnpd	.../test_yielding_results.py#_test_skip @localic-localtg: evaluation skipped 
  FAIL2/enpeE#1	.../test_yielding_results.py#_test_fail @localic-localtg: I am causing a failure by raising
  FAIL2/enpeE#1	.../test_yielding_results.py#_test_fail @localic-localtg: eval failed: I failed
  FAIL0/enpe	.../test_yielding_results.py#_test_fail @localic-localtg: evaluation failed 
  ERRR2/ap2nE#1	.../test_yielding_results.py#_test_errr @localic-localtg: I am causing an error by raising
  ERRR2/ap2nE#1	.../test_yielding_results.py#_test_errr @localic-localtg: eval errored: I errored
  ERRR0/ap2n	.../test_yielding_results.py#_test_errr @localic-localtg: evaluation errored 
  FAIL0/	toplevel @local: 5 tests (1 passed, 1 error, 1 failed, 1 blocked, 1 skipped, in 0:00:00.505594) - failed 

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

Note how *tcf run* reports counts on how many testcase executed, how
many passed/errored/failed/blocked or skipped.
"""
import os
import random

import tcfl.tc

random.seed()

class _test_pass(tcfl.tc.tc_c):
    def eval(self):
        self.report_pass("I am causing a pass by raising")
        # or you can just return nothing, that means pass
        raise tcfl.tc.pass_e("I passed")

class _test_errr(tcfl.tc.tc_c):
    def eval(self):
        self.report_error("I am causing an error by raising")
        raise tcfl.tc.error_e("I errored")

class _test_fail(tcfl.tc.tc_c):
    def eval(self):
        self.report_fail("I am causing a failure by raising")
        raise tcfl.tc.failed_e("I failed")

class _test_blck(tcfl.tc.tc_c):
    def eval(self):
        self.report_blck("I am causing a blockage by raising")
        raise tcfl.tc.blocked_e("I blocked")

class _test_skip(tcfl.tc.tc_c):
    def eval(self):
        self.report_skip("I am causing a skip by raising")
        raise tcfl.tc.skip_e("I skipped")
