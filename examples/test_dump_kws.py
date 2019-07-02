#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Static testcases (no targets, run local)
----------------------------------------

Notice the test group values are slightly different between the
multiple targets, the single target or no targets (static) cases.

.. literalinclude:: /examples/test_dump_kws.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_dump_kws.py>` with::

  $ tcf run -vv /usr/share/tcf/examples/test_dump_kws.py
  INFO0/vxmvB	/usr/share/tcf/examples/test_dump_kws.py#_test @localic-localtg: Keywords for testcase:
  {'cwd': '/home/inaky/z/s/local',
   'runid': '',
   'srcdir': '../../../../../usr/share/tcf/examples',
   'srcdir_abs': '/usr/share/tcf/examples',
   'target_group_info': 'localic-localtg',
   'target_group_name': 'localic-localtg',
   'target_group_servers': '',
   'target_group_targets': '',
   'target_group_types': 'static',
   'tc_hash': 'vxmv',
   'tc_name': '/usr/share/tcf/examples/test_dump_kws.py#_test',
   'tc_name_short': '/usr/share/tcf/examples/test_dump_kws.py#_test',
   'tc_origin': '/usr/share/tcf/examples/test_dump_kws.py:46',
   'thisfile': '/usr/share/tcf/examples/test_dump_kws.py',
   'tmpdir': '/tmp/tcf.run-9tJyXx/vxmv',
   'type': 'static'}
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:00.302539) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""
import pprint
import tcfl.tc

@tcfl.tc.tags(build_only = True, ignore_example = True)
class _test(tcfl.tc.tc_c):
    def build(self):
        self.report_info("Keywords for testcase:\n%s"
                         % pprint.pformat(self.kws),
                         level = 0)
