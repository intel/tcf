#! /usr/bin/env python3
#
# (C) 2024 Intel Corporation
#
# SPDX-License-Header: Apache 2.0

import os.path
import subprocess

import commonl
import tcfl.tc

class _test(tcfl.tc.tc_c):
    """
    Test the *extra_volume_maps* of
    :func:`commonl.buildah_image_create` by creating a container image
    mapping a volume (the tempdir) and adding a file in there.
    """
    def eval(self):

        this_file = os.path.basename(__file__)
        this_dir = os.path.abspath(os.path.dirname(__file__))
        self.report_info(f"mapping {self.tmpdir} to /example/volume")
        dockerfile = f"""\
FROM registry.fedoraproject.org/fedora-minimal:latest as fedora
RUN rm -f /example/volume/somefile.txt && touch /example/volume/somefile.txt
"""
        _, p = commonl.buildah_image_create(
            f"test_ttbd_image.{self.runid_hashid}",
            # ideally we'd use a scratch image, but then we have no
            # way to copy files to the volume (COPY doesn't really do
            # it)
            dockerfile,
            maybe = False,
            timeout = 300,			# might take a while to dnload
            capture_output = True,
            extra_volume_maps = {
                # map testcase's tempdir, because we'll mod it
                self.tmpdir: "/example/volume:rw"
            })
        if os.path.exists(os.path.join(self.tmpdir, "somefile.txt")):
            self.report_pass("container image build process placed file"
                             f" 'somefile.txt' found in {self.tmpdir}")
        else:
            self.report_fail("container image build process did not place file"
                             f" 'somefile.txt' found in {self.tmpdir}",
                             {
                                 "stdout": p.stdout,
                                 "stderr": p.stderr,
                                 "cmdline": " ".join(p.args),
                                 "dockerfile": dockerfile,
                             })


    def teardown(self):	# cleanup
        self.report_info(f"cleaning created image test_ttbd_image.{self.runid_hashid}")
        subprocess.run(
            f"podman rmi test_ttbd_image.{self.runid_hashid}".split(),
            capture_output = True,
            check = True)
