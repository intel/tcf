#! /usr/bin/python3
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Proprietary
#
# pylint: disable = missing-docstring

""".. _example_subcases:

Reporting subcases
==================

A common execution pattern is that a testcase executes and produces
results for multiple subcases.

In this example, given a target that can be provisioned with
:ref:`Provisioning OS <pos_setup>`, we create a fake testcase that
generates ten subtestcase reports in individual logfiles called
*subN.log*.

When the testcase is created, in the *__init__()* method, we would
scan the test to discover the list of subcases that will unfold--in
this example, we are faking it--this is important because it allows us
to double check that all we expected to execute will.

In general, the name of the subcase is the name of the testcase plus a
*dot something* (in this case we append *.subN*); then it is added to
the :data:`subtestcase dictionary self.subtc <tcfl.tc.tc_c.subtc>` by
creating an instancel of :class:`tcfl.tc.subtc_c`, which implements
this pattern.

.. literalinclude:: /examples/test_subcases.py
   :language: python
   :pyobject: _test

Execute :download:`the testcase <../examples/test_subcases.py>`
with (where *IMAGE* is the name of a Linux OS image :ref:`installed in
the server <pos_list_images>`)::

  $ IMAGE=clear tcf run -v /usr/share/tcf/examples/test_subcases.py

(depending on your installation method, location might be
*~/.local/share/tcf/examples*)

where IMAGE is the name of a Linux OS image :ref:`installed in the
server <pos_list_images>`.

"""

import tcfl.tc

class _test(tcfl.pos.tc_pos_base):
    def __init__(self, name, tc_file_path, origin):
        tcfl.pos.tc_pos_base.__init__(self, name, tc_file_path, origin)

        # "scan" for subcases (in our case, we know they'll be sub0 to sub9)
        for i in range(3):
            subcase = "sub%d" % i
            self.subtc[subcase] = tcfl.tc.subtc_c(self.name + "##" + subcase,
                                                  tc_file_path, origin, self)

    def eval_00(self, target):

        # Run our imaginary testcase in the target
        #
        # this script (our 'testcase') creates N files subX.log on
        # which the fist line is 0, 1 or 2 (pass, fail, error), a fake
        # summary and therest are a random made up log file we want to
        # report. Eg:
        #
        #   2
        #   Summary for subtest 5
        #   zsh syslinux zoneinfo hwdata file pixmaps drirc.d icons mime-packages
        #   gir-1.0 nano gtk-2.0 graphite2 libinput GConf misc vpnc bash-completion
        #   scan-view openldap security screen wayland cups opt-viewer znc pam.d
        #   libtool aclocal keyutils
        #
        # for a list of words that works everywhere, we just list /usr/share
        # `shuf` picks 30 random lines from input and `fmt` makes a
        # paragraph out of that.
        target.shell.run('for((n = 0; n < %d; n++));'
                         ' do ('
                         '  echo $((RANDOM %% 3)); '
                         '  echo Summary for subtest $n; '
                         '  /bin/ls /usr/share | shuf -n 30 | fmt'
                         ' ) > sub$n.log;'
                         'done' % len(self.subtc))

        # cat each log file to tell what happened? we know the log
        # file names, so we can just iterate in python -- in other
        # cases, we might have to list files in the target to find the
        # log files, or scan through a big log file that has
        # indications of where the output for one subcase start and
        # ends.
        for n in range(len(self.subtc)):
            subcase_name = "sub%d" % n
            output = target.shell.run('cat %s.log' % subcase_name,
                                      output = True, trim = True)
            # first line is result, parse it
            result, summary, log = output.split('\n', 2)
            # translate the result to a TCF result
            result = result.strip()
            if result == "0":
                _result = tcfl.tc.result_c(passed = 1)
            elif result == "1":
                _result = tcfl.tc.result_c(failed = 1)
            elif result == "2":
                _result = tcfl.tc.result_c(errors = 1)
            else:
                raise AssertionError("unknown result from command output '%s'"
                                     % result)

            # For each subcase's output, update the subcase report
            self.subtc[subcase_name].update(_result, summary, log)

        # now when this testcase is done executing, the subcases are
        # going to be executed following and they will just report
        # their result individually.
