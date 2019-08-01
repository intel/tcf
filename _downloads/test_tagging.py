#! /usr/bin/python2
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""Tag a testcase
==============

A testcase can be given one or more tags with the :func:`tcfl.tc.tags`
decorator:

.. literalinclude:: /examples/test_tagging.py
   :language: python
   :pyobject: _test

Note the *component/ANYTHING* tags are *special*, they are interpreted
as a namespace and with them, another tag called *components* is going
to be generated listing all the components found.

Tags, for example, can be used later to filter from the command line
to select all testcases with that expose a tag *color* with value
*red*, in this case, only :download:`this one
<../examples/test_tagging.py>`::

  $ tcf run -vv -s 'color == "red"' /usr/share/tcf/examples/

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

"""
import os

import tcfl.tc
import tcfl.pos

@tcfl.tc.tags("boolean_tag", "component/storage", value = 3, color = "red",
              ignore_example = True)
class _test(tcfl.tc.tc_c):
    def eval(self):
        for tag, value in self._tags.iteritems():
            self.report_info("tag %s: %s [from %s]"
                             % (tag, value[0], value[1]), level = 0)
