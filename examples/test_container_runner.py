#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
""".. _example_container_runner:

Impromptu testcase driver to execute testcases in containers
============================================================

This example provisions an OS in the SUT and then runs a container
from a given registry, procesing it's standard output as TAP format to
parse subcase.

To execute :download:`the testcase
<../examples/test_container_runner.py>` and:

- (if no container image already available) build a testcase container
  image and push it to the registry::

    $ buildah buildah  bud -t IMAGENAME -f FILE.Dockerfile
    $ podman login --username USERNAME REGISTRY
    $ buildah push IMAGENAME REGISTRY/PROJECT/IMAGENAME

  this requires a Dockerfile; a very simple example that using TAP's
  http://testanything.org reporting format could be::

    FROM fedora:33
    RUN dnf install -y python3
    ENTRYPOINT python3 -c "print('ok 1 - sample 1 test')"

  add that to *file.Dockerfile* and run the build and push commands

- Execute the testcase::

    $ IMAGE=<IMAGE> tcf run -vv /usr/share/tcf/examples/test_container_runner.py#REGISTRY/PROJECT:IMAGENAME

  Where *IMAGE* is the name of a Linux OS that supports container
  execution with podman :ref:`installed in the server
  <pos_list_images>`).

  Depending on your installation method, location might be
  *~/.local/share/tcf/examples*)

  Exection tweaks:

  - if the machine is already provisioned, add *-D* to skip the
    provisioning step

  - if the machine is already on and ready to execute, prefix
    *REBOOT_DISABLED=true* to avoid a power cycle::

      $ REBOOT_DISABLED=true IMAGE=<IMAGE> tcf run -vv /usr/share...

FIXME/PENDING:

- report parsing hardcoded to TAP

- __init__ checks for images from repo and pulls data (SUT deps,
  etc), populates it

- only public images now--SUT can't login to registry yet

- add support to run containers in parallel
"""

import os
import subprocess
import re

import commonl
import tcfl.tc


timeouts = {}
#:
#: Default timeout (seconds) to execute a test -- account fo rimage download time
#:
timeout_default = 180

class _driver(tcfl.pos.tc_pos_base):

    def _output_parse(self, testsuite, suite_tc, lf):
        pass

    def start_50(self, ic, target):
        if 'REBOOT_DISABLED' not in os.environ:
            tcfl.pos.tc_pos_base.start_50(self, ic, target)
            target.console.select_preferred()
        else:
            target.console.select_preferred()
            #target.shell.prompt_regex = re.compile("KTS-PROMPT[\$%#]")
            target.console.enable()
            target.shell.setup()

    def eval_00(self, ic, target):

        target.shell.prompt_regex = re.compile(r"KTS-PROMPT[\$%#]")
        target.shell.run(
            f"echo $PS1 | grep -q KTS-PROMPT"
            f" || export PS1='TCF-{self.ticket}:KTS-PROMPT$ '"
            f" # a simple prompt is harder to confuse with general output")

        if not self.subcases:
            raise RuntimeError("FIXME: no subcases")
        tcfl.tl.linux_time_set(target)

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
            stdbuf_prefix = "stdbuf -e0 -o0"

        target.shell.run("rm -rf logs && mkdir logs")
        target.shell.run("set -o pipefail")
        # FIXME: running serial -> add way to run parallel
        for testsuite in self.subcases:
            timeout = timeouts.get(testsuite,
                                   int(os.environ.get("TIMEOUT",
                                                      timeout_default)))
            # suite_tc -> overall result of the whole testsuite execution
            with self.subcase(testsuite):
                try:
                    target.report_info("running testsuite %s" % testsuite)
                    target.shell.run(f"mkdir -p 'logs/{os.path.dirname(testsuite)}'")
                    # run the testsuite and capture the output to a log file
                    # HACK: ignore errors, so we can cancel on timeout
                    # without it becoming a mess -- still
                    target.shell.run(f"podman kill --signal KILL {self.runid_hashid} || true")
                    target.shell.run(f"podman rm -f {self.runid_hashid} || true")
                    target.shell.run(
                        f"{stdbuf_prefix} podman run --name {self.runid_hashid} {testsuite} 2>&1"
                        f" | tee -a logs/{testsuite}.log",
                        timeout = timeout)
                except tcfl.tc.error_e as e:
                    # FIXME: this is a hack, we need a proper timeout exception
                    if "NOT FOUND after" not in str(e):
                        raise
                    # if we timeout this one, just cancel it and go for the next
                    target.report_error(
                        f"stopping after {timeout}s timeout")
                    # suspend -- Ctrl-Z & kill like really harshly
                    target.console_tx("\x1a\x1a\x1a")
                    target.expect("SIGTSTP")
                    target.shell.run(f"podman kill --signal KILL {self.runid_hashid} || true")	# might be dez already

        # bring the log files home; SSH is way faster than over the console
        target.shell.run('tar cjf logs.tar.bz2 logs/')
        target.tunnel.ip_addr = target.addr_get(ic, "ipv4")
        target.ssh.copy_from("logs.tar.bz2", self.tmpdir)
        subprocess.check_output(
            [ "tar", "xf", "logs.tar.bz2" ],
            stderr = subprocess.STDOUT, cwd = self.tmpdir)

        # cat each log file to tell what happened? we know the log
        # file names, so we can just iterate in python
        for testsuite in self.subcases:
            dirname = os.path.dirname(testsuite)
            name = os.path.basename(testsuite)
            result = tcfl.result_c()
            with self.subcase(testsuite), \
                 open(os.path.join(self.tmpdir, "logs", dirname, name + ".log")) as lf:
                target.report_info("parsing logs")
                try:
                    # FIXME: support multiple formats, for now hard coded to TAP
                    d = tcfl.tl.tap_parse_output(lf)
                except Exception as e:
                    d = dict()
                    result += tcfl.result_c.report_from_exception(self, e)
                for name, data in d.items():
                    _tc_name = commonl.name_make_safe(name)
                    with self.subcase(_tc_name):
                        self.subtc[tcfl.msgid_c.subcase()].update(
                            tcfl.tl.tap_mapping_result_c[data['result']],
                            data.get('subject', str(data['plan_count'])),
                            data['output'])
