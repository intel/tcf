#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import glob
import os
import re
import site
import subprocess
import time

import distutils
import distutils.command.install_data
import distutils.command.build_py
import distutils.command.sdist
import distutils.core
import distutils.sysconfig

import setupl

# Hook in the source distribution to generate tcfl.version with
# whichever version we generate or have guessed.
class _sdist(distutils.command.sdist.sdist):
    def run(self):
        # Build the documentation to include in the distribution
        subprocess.check_call("rm -rf _doc && make BUILDDIR=_doc html",
                              shell = True)
        distutils.command.sdist.sdist.run(self)

    def make_release_tree(self, base_dir, files):
        self.mkpath(base_dir)
        distutils.dir_util.create_tree(base_dir, files, dry_run=self.dry_run)
        target_dir = os.path.join(base_dir, 'tcfl')
        setupl.mk_version_py(target_dir, self.distribution.get_version())
        distutils.command.sdist.sdist.make_release_tree(self, base_dir, files)


# Likewise when we build the pythons
class _build_py(distutils.command.build_py.build_py):
    def run(self):
        if not self.dry_run:
            target_dir = os.path.join(self.build_lib, 'tcfl')
            self.mkpath(target_dir)
            setupl.mk_version_py(target_dir, self.distribution.get_version())

        # distutils uses old-style classes, so no super()
        distutils.command.build_py.build_py.run(self)


distutils.core.setup(
    name = 'tcf',
    description = "TCF client",
    long_description = """\
This is the client and meta-testcase runner for the TCF test case framework.
""",
    version = setupl.version,
    url = None,
    author = "Inaky Perez-Gonzalez",
    author_email = "inaky.perez-gonzalez@intel.com",
    packages = [
        'commonl',
        'tcfl',
    ],
    scripts = [ "tcf" ],
    # This is needed so when data is to be installed, our
    # _install_data class is used.
    cmdclass = dict(
        build_py = _build_py,
        install_scripts = setupl._install_scripts,
        install_data = setupl._install_data,
        sdist = _sdist,
    ),
    data_files = [
        # No default configuration files; confusing
        ('@sysconfigdir@/tcf/', [
            'conf_global.py',
        ]),
        # ('etc/tcf', glob.glob("conf_*.py")),
        ('@prefix@/share/tcf', [
            'tcfl/img-metadata.schema.yaml',
        ]),
        ('@prefix@/share/tcf/examples',
         [ ] \
         + glob.glob("examples/*.py") \
         + glob.glob("examples/*.ino"),
        ),
        ('@prefix@/share/tcf/tests',
         setupl.glob_no_symlinks("tests/*.py")
         + glob.glob("tests/*.sh")
         + glob.glob("tests/*.sh")
         + glob.glob("tests/*.txt")
         # These map to symlinked files in tests/
         + [
             'ttbd/conf_00_lib.py',
         ]
        ),
        ('@prefix@/share/tcf/lint',
         setupl.glob_no_symlinks(".lint.*.py")
         + [ "lint-all.py" ]
        ),
        ('@prefix@/share/tcf/',
         [
             "report-base.j2.txt",
             "report.j2.txt",
             "junit-base.j2.xml",
             "junit.j2.xml",
         ]
        ),
        ( '@prefix@/share/tcf/content', [
            'tcfl/evemu.bin.tar.gz',
        ]),
    ],
)
