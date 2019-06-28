#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
Testcase using two targets
--------------------------

Note n this case the target group names are listing two targets and
each target obejct has different values.

.. literalinclude:: /examples/test_dump_kws_two_targets.py
   :language: python
   :pyobject: _test

Execute with::

  $ tcf run -vv /usr/share/tcf/examples/test_dump_kws_twp_targets.py
  INFO0/ato4B	/usr/share/tcf/examples/test_dump_kws_two_targets.py#_test @2psg: Keywords for testcase:
  {'cwd': '/home/inaky/z/s/local',
   ...}
  INFO0/ato4B	/usr/share/tcf/examples/test_dump_kws_two_targets.py#_test @2psg|localhost/qz33b-arm: Keywords for target 0:
  {u'board': u'qemu_cortex_m3',
   'bsp': u'arm',
   u'bsp_models': {u'arm': [u'arm']},
   u'bsps': {u'arm': {u'board': u'qemu_cortex_m3',
                      u'console': u'arm',
                      u'kernelname': u'zephyr.elf',
   ...
   u'zephyr_board': u'qemu_cortex_m3',
   u'zephyr_kernelname': u'zephyr.elf'}
  INFO0/ato4B	/usr/share/tcf/examples/test_dump_kws_two_targets.py#_test @2psg|localhost/qz31a-x86: Keywords for target 1:
  {u'board': u'qemu_x86',
   'bsp': u'x86',
   u'bsp_models': {u'x86': [u'x86']},
   u'bsps': {u'x86': {u'board': u'qemu_x86',
                      u'console': u'x86',
                      u'kernelname': u'zephyr.elf',
                      u'quark_se_stub': False,
   ...
   u'zephyr_board': u'qemu_x86',
   u'zephyr_kernelname': u'zephyr.elf'}
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:00.417956) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)
"""

import pprint
import tcfl.tc

@tcfl.tc.target()
@tcfl.tc.target()
@tcfl.tc.tags(build_only = True, ignore_example = True)
class _test(tcfl.tc.tc_c):
    def build(self, target, target1):
        self.report_info("Keywords for testcase:\n%s"
                         % pprint.pformat(self.kws),
                         level = 0)
        target.report_info("Keywords for target 0:\n%s"
                           % pprint.pformat(target.kws),
                           level = 0)
        target1.report_info("Keywords for target 1:\n%s"
                            % pprint.pformat(target1.kws),
                            level = 0)
