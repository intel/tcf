#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
Module for testing invocatoins of the tcf command line tool in the shell
------------------------------------------------------------------------
"""

import os
import re

import commonl.testing
import tcfl
import tcfl.tc

srcdir = os.path.dirname(__file__)
topdir = os.path.abspath(os.path.join(srcdir, ".."))
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        re.compile(r"ERROR:.*\(AUDIT\|serving with\)"),
        re.compile(r"DEBUG:.*"),
    ]
)


@tcfl.tc.parameters(
    tcfl.tc.parameter_c(
        "prefix",
        "prefix of the installation (as given to pip install --prefix=PREFIX"
        " TCFDIR); defaults to nothing and will run from source",
        "<prefix:none>"),
    tcfl.tc.parameter_c(
        "venvdir",
        "directory where a Python virtual environment was created and TCF"
        " was installed; defaults to none",
        "<venvdir:none>"),
    tcfl.tc.parameter_c(
        "container",
        "container image under which to run; defaults to using the local OS",
        "<container:none>"),
)
@tcfl.tc.target(ttbd.url_spec)
class test_base_c(tcfl.tc.tc_c):
    """

    The orden of evaluation of which parameter to use is as follows

    - if *container* is defined, we will run under a container;
      otherwise under the current system image

    - if *venvdir* is defined, we will activate it and run a tcf
      installed in such environment (under container if defined)

    - if *prefix* is defined, we will run a tcf
      installed in *PREFIX/bin*; otherwise it will defalt to run from
      source in the directory of the testcase (calculated as the
      parent directory where this file is).

    Building container images for execution:

      - use ../client.Dockerfile which builds the dependencies
        needed to run and installs in prefix and venv


    To run in the different environments:

    - Local system, source tree::

        tcf run test_NAME.py

    - Local system, installed tree::

        pip install --prefix=XYZ .../tcf.git
        export PYTHONPATH=$(readlink -e XYZ/lib/python*/site-packages):$PYTHONPATH"
        export PATH=XYZ/bin:$PATH
        tcf -e PARAMETER_prefix=XYZ run test_NAME.py

    - Local system, python virtual environment::

        python -m venv SOMEDIR.venv
        source SOMEDIR.venv/bin/activate
        .../tcf.git/nreqs.py install  .../tcf.git/base.nreqs.yaml
        pip install  .../tcf.git
        tcf -e PARAMETER_venvdir=SOMEDIR.venv run test_NAME.py

    - To run in a container, build the container first with the
      desired based OS (see instructions in ../client.Dockerfile);
      this will create prefix based installs in /opt/tcf-client.venv
      and /opt/tcf-client.dir and then do the above instructions, but
      adding::

        -e PARAMETER_container=IMAGENAME

      eg::

        tcf -e PARAMETER_container=tcf-client-deps -e PARAMETER_venvdir=/opt/tcf-client.venv run test_NAME.py

    """
    def setup_10_clil(self, target):
        target.console.enable()
        target.shell.setup()

        prefix = self.parameter_get("prefix")
        venvdir = self.parameter_get("venvdir")
        container = self.parameter_get("container")

        if container != "<container:none>":
            # always map $HOME, so we have access to the source if we
            # need it
            target.send(
                f"podman run --network=none --entrypoint= -ti -v $HOME:$HOME {container} /bin/bash")
            target.shell.run(
                r'export PS1="TCF-%(tc_hash)s:\w %%%% \$ "' % target.kws)
            target.shell.setup()
            system_image = f"container {container}"
        else:
            system_image = "local OS"

        # remove all special stuff for pretty prompts that interferes
        # with automation
        target.shell.run("unset PROMPT_COMMAND PS0")

        if prefix and prefix != "<prefix:none>":
            target.report_info(
                f"TCF CLI will run off prefix {prefix} in {system_image}")
            target.shell.run(f"export PATH={prefix}/bin:$PATH")
            target.shell.run(
                # we don't know what Python is configured in PREFIX,
                # so we just do a wild guess that's only one
                f"export PYTHONPATH=$(readlink -e {prefix}/lib/python*/site-packages):$PYTHONPATH")
            # verify we have the right TCF
            output = target.shell.run(
                "readlink -e $(which tcf)", output = True, trim = True)
            if output != f"{prefix}/bin/tcf":
                raise tcfl.error_e(
                    f"'which tcf' reports version '{output}'; expected '{prefix}/bin/tcf'")

        elif venvdir and venvdir != "<venvdir:none>":
            target.report_info(
                f"TCF CLI will run off Python venv {venvdir} in {system_image}")
            venvdir_basename = os.path.basename(venvdir)
            target.shell.run(f'source {venvdir}/bin/activate; export PS1="({venvdir_basename}) $PS1"')
            # this changes the prompt to
            #
            ## (tcf-cli.env) bash-5.2$
            #
            # so we force the hand a wee bit
            output = target.shell.run(
                "readlink -e $(which tcf)", output = True, trim = True)
            if output != f"{venvdir}/bin/tcf":
                raise tcfl.error_e(
                    f"'which tcf' reports version '{output}'; expected '{venvdir}/bin/tcf'")

        else:
            target.report_info(
                f"TCF CLI will run off source tree {topdir} in {system_image}")
            target.shell.run(f"export PATH={topdir}:$PATH")
            output = target.shell.run(
                "readlink -e $(which tcf)", output = True, trim = True)
            if output != f"{topdir}/tcf":
                raise tcfl.error_e(
                    f"'which tcf' reports version '{output}'; expected f{venvdir}/bin/tcf")



    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
