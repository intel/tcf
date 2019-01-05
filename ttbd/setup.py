#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# Invoke with
#
# VERSION=$(git describe) python ./setup.py bdist_rpm
#
#
import fileinput
import os

import distutils
import distutils.command.bdist_rpm
import distutils.command.install_data
import distutils.command.sdist
import distutils.command.build_py
import distutils.core
import distutils.sysconfig

import setupl

# Hook in the source distribution to generate ttbl.version with
# whichever version we generate or have guessed.
class _sdist(distutils.command.sdist.sdist):

    def make_release_tree(self, base_dir, files):
        self.mkpath(base_dir)
        distutils.dir_util.create_tree(base_dir, files, dry_run=self.dry_run)
        target_dir = os.path.join(base_dir, 'ttbl')
        setupl.mk_version_py(target_dir, self.distribution.get_version())
        distutils.command.sdist.sdist.make_release_tree(self, base_dir, files)


# Likewise when we build the pythons
class _build_py(distutils.command.build_py.build_py):
    def run(self):
        if not self.dry_run:
            target_dir = os.path.join(self.build_lib, 'ttbl')
            self.mkpath(target_dir)
            setupl.mk_version_py(target_dir, self.distribution.get_version())

        # distutils uses old-style classes, so no super()
        distutils.command.build_py.build_py.run(self)

# Run a post-install on installed data file replacing paths as we need
class _install_data(setupl._install_data):
    def run(self):
        install = self.distribution.command_options.get('install', {})
        if 'user' in install:
            raise RuntimeError("ttbd cannot be installed with --user, see "
                               "contributing guide in documentation")
        setupl._install_data.run(self)
        for filename in self.outfiles:
            if filename.endswith("var/lib/ttbd"):
                os.chmod(filename, 02775)
        # add ttbd to supplementalgroups in ttbd@.service
        for filename in self.outfiles:
            if filename.endswith(".ttbd@.service"):
                with fileinput.FileInput(filename, inplace = True,
                                         backup = None) as f:
                    for line in f:
                        print line.replace("SupplementalGroups = ",
                                           "SupplementalGroups = ttbd ",
                                           end = '')

class _bdist_rpm(distutils.command.bdist_rpm.bdist_rpm):
    def _make_spec_file(self):
        spec = distutils.command.bdist_rpm.bdist_rpm._make_spec_file(self)
        spec.extend(['%attr(2775,ttbd,ttbd) %dir /var/lib/ttbd'])
        spec.extend(['%attr(2775,ttbd,ttbd) %dir /etc/ttbd-production'])
        return spec


distutils.core.setup(
    name = 'ttbd',
    description = "TCF TTBD server",
    long_description = """\
This is the server for the TCF test case framework that exports test
targets over HTTP to be controlled by the TCF client.
""",
    version = setupl.version,
    url = None,
    author = "Inaky Perez-Gonzalez",
    author_email = "inaky.perez-gonzalez@intel.com",
    packages = [
        'ttbl',
    ],
    scripts = [
        "ttbd",
        'hw-healthmonitor/ttbd-hw-healthmonitor.py',
        "usb-sibling-by-serial"
    ],
    # This is needed so when data is to be installed, our
    # _install_data class is used.
    cmdclass = dict(
        sdist = _sdist,
        install_data = _install_data,
        bdist_rpm = _bdist_rpm
    ),
    data_files = [
        ('etc/systemd/system', [
            'ttbd@.service',
            'hw-healthmonitor/ttbd-hw-healthmonitor.service'
        ]),
        ('etc/sudoers.d', [
            'ttbd_sudo',
            'hw-healthmonitor/ttbd_hw_healthmonitor_sudo'
        ]),
        ('etc/ttbd-production', [
            'conf_00_lib.py',
            'conf_06_default.py',
            'conf_05_auth_local.py',
            'example_conf_05_auth_localdb.py',
            'example_conf_05_auth_ldap.py',
        ]),
        ('etc/ttbd-hw-healthmonitor', [
            'hw-healthmonitor/example_conf_50_xhci.py',
        ]),
        # We install a local server, also a TCF config for it
        ('etc/tcf', [ 'conf_local.py' ]),
        ('@prefix@/share/tcf', [
            'hw-healthmonitor/ttbd-hw-healthmonitor-driver-rebind.py',
            'setup-efi-grub2-elf.sh'
        ]),
        ('@prefix@/share/tcf/live', [
            'live/mk-liveimg.sh',
            'live/tcf-live-02-core.pkgs',
            'live/tcf-live-extra-network.ks',
            'live/tcf-live.ks',
            'tcf-live-pos.pkgs'
        ]),
        ('@prefix@/lib/udev/rules.d', [ '80-ttbd.rules' ]),
        ('var/lib/ttbd', [ 'frdm_k64f_recovery.bin' ]),
    ],
    ext_modules = [
        distutils.core.Extension(
            'ttblc',
            [ 'ttbl/ttblc.c' ],
            # It is not clear where this is coming from in my setup,
            # so just in case, force it's definition.
            extra_compile_args = [ "-D_FORTIFY_SOURCE=2" ],
        )
    ]
)
