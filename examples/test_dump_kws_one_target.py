#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Testcase using one target
-------------------------

Note the data offered for the target is a superse of the testcase's
augmented with all the target metadata exported by the server

.. literalinclude:: /examples/test_dump_kws_one_target.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase
<../examples/test_dump_kws_one_target.py>` with::

  $ tcf run -vv /usr/share/tcf/examples/test_dump_kws_one_target.py
  INFO0/gcoyBwifr	/usr/share/tcf/examples/test_dump_kws_one_target.py#_test @localhost/qz31b-x86: Keywords for testcase:
  {'cwd': '/home/inaky/z/s/local',
   'runid': '',
   'srcdir': '../../../../../usr/share/tcf/examples',
   'srcdir_abs': '/usr/share/tcf/examples',
   ...
   'target_group_targets': u'localhost/qz31b-x86:x86',
   'target_group_types': u'qemu-zephyr-x86',
   'tc_hash': 'gcoy',
   'tc_name': '/usr/share/tcf/examples/test_dump_kws_one_target.py#_test',
   'tc_name_short': '/usr/share/tcf/examples/test_dump_kws_one_target.py#_test',
   'tc_origin': '/usr/share/tcf/examples/test_dump_kws_one_target.py:50',
   'thisfile': '/usr/share/tcf/examples/test_dump_kws_one_target.py',
   'tmpdir': '/tmp/tcf.run-DmwH93/gcoy',
   'type': u'qemu-zephyr-x86'}
  INFO0/gcoyBwifr	/usr/share/tcf/examples/test_dump_kws_one_target.py#_test @localhost/qz31b-x86: Keywords for target 0:
  {u'board': u'qemu_x86',
   'bsp': u'x86',
   u'bsp_models': {u'x86': [u'x86']},
   u'bsps': {u'x86': {u'board': u'qemu_x86',
                      u'console': u'x86',
   ...
   u'interconnects': {u'nwb': {u'ic_index': 31,
                               u'ipv4_addr': u'192.168.98.31',
                               u'ipv4_prefix_len': 24,
                               u'ipv6_addr': u'fd:00:62::1f',
                               u'ipv6_prefix_len': 104,
                               u'mac_addr': u'02:62:00:00:00:1f'}},
   u'interfaces': [u'power',
                   u'images',
                   u'console',
                   u'debug'],
   ...
   'url': u'https://localhost:5000/ttb-v1/targets/qz31b-x86',
   u'zephyr_board': u'qemu_x86',
   u'zephyr_kernelname': u'zephyr.elf'}
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:00.302253) - passed

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""
import pprint
import tcfl.tc

@tcfl.tc.target()
@tcfl.tc.tags(build_only = True, ignore_example = True)
class _test(tcfl.tc.tc_c):
    def build(self, target):
        self.report_info("Keywords for testcase:\n%s"
                         % pprint.pformat(self.kws),
                         level = 0)
        target.report_info("Keywords for target 0:\n%s"
                           % pprint.pformat(target.kws),
                           level = 0)
