#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import subprocess
import time

import commonl.testing
import tcfl.tc
import utl

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Traceback"
    ])

# Note this test allocates no target, since we have to do it as part
# of the steps in A
class _test(tcfl.tc.tc_c):
    """
    Test that when an allocation is removed, it respects that the
    original targets it had might be under another allocation now.

    See ttbl.allocation.py:allocation_c.delete()

    1. Target gets allocated under ALLOCA
    2. target gets released, but ALLOCA is still active
    3. Target gets allocated under ALLOCB
    4. ALLOCA is let expire (timeout), when it is to removed, it
       notices target is not part of ALLOCA, so it is not released

    """

    acquire_allocid_regex = re.compile("allocation ID (?P<allocid>\w+): .*allocated.*")

    def eval(self):
        tcf_tool_path = utl.tcf_tool_path(self)

        r = subprocess.run([ tcf_tool_path, "ls"],
                           check = True, capture_output = True, text = True)
        if ttbd.aka + "/t0" not in r.stdout:
            raise tcfl.error_e(f"{ttbd.aka}/0 not found in ls output",
                             dict(ls_output = r.stdout))
        self.report_pass(f"listed targets, found {ttbd.aka}/t0",
                         dict(ls_output = r.stdout))

        # acquire the target
        r = subprocess.run([ tcf_tool_path, "acquire", ttbd.aka + "/t0" ],
                           check = True, capture_output = True, text = True)
        # output shall be something like
        ## allocation ID mz59pvwg: [+0.6s] allocated: t0
        m = self.acquire_allocid_regex.search(r.stdout)
        if not m:
            raise tcfl.failed_e(
                "can't find expected 'allocation ID' message in output of"
                " 'tcf acquire'",
                dict(stdout = r.stdout, stderr = r.stderr ))
        allocid_a = m.groupdict()['allocid']
        self.report_info(f"t0 acquired to allocid A {allocid_a}")

        # now release it, but ALLOCA is still active
        subprocess.run([ tcf_tool_path, "release", ttbd.aka + "/t0" ],
                       check = True, capture_output = True, text = True)
        self.report_info(f"t0 released from allocid A {allocid_a}")

        # acquire t0 to ALLOCB
        r = subprocess.run([ tcf_tool_path, "acquire", ttbd.aka + "/t0" ],
                           check = True, capture_output = True, text = True)
        m = self.acquire_allocid_regex.search(r.stdout)
        allocid_b = m.groupdict()['allocid']
        if not m:
            raise tcfl.failed_e(
                "can't find expected 'allocation ID' message in output of"
                " 'tcf acquire'",
                dict(stdout = r.stdout, stderr = r.stderr ))
        self.report_info(f"t0 allocated to allocid B {allocid_b}")

        # now delete ALLOCA
        r = subprocess.run([ tcf_tool_path, "alloc-rm", allocid_a ],
                           check = True, capture_output = True, text = True)

        # t0 should still be allocated to ALLOCB
        r = subprocess.run([ tcf_tool_path, "ls", "-v", ttbd.aka + "/t0" ],
                           check = True, capture_output = True, text = True)
        # output shall look like
        #
        ## ttbd-HASH/t0 [local:ALLOCB] ON
        regex = re.compile(f"{ttbd.aka}/t0\s+\[[^:]+:(?P<allocid>[^]]+)\]")
        m = regex.search(r.stdout)
        if not m or 'allocid' not in m.groupdict():
            raise tcfl.fail_e(
                f"t0 seems not to be allocated, should to allocid B {allocid_b}",
                dict(ls_output = r.stdout))
        allocid_t0 = m.groupdict()['allocid']
        if allocid_t0 != allocid_b:
            raise tcfl.fail_e(
                f"t0 is not allocated to allocid B {allocid_b} but {allocid_t0}",
                dict(ls_output = r.stdout))
        self.report_pass(f"t0 is still allocated to allocid B {allocid_b}",
                         dict(ls_output = r.stdout))

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
