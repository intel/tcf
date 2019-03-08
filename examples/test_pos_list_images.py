#! /usr/bin/python2
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import subprocess

import tcfl.tc
import tcfl.tl
import tcfl.pos

image_env = os.environ.get("IMAGE", None)

@tcfl.tc.interconnect("pos_rsync_server", mode = "all")
class _(tcfl.tc.tc_c):
    """
    List images available in a POS rsync server
    """
    def eval(self, ic):
        ic.power.on()
        port = ic.tunnel.add(873, ic.kws['ipv4_addr'])	# rsync's
        rsync_host = ic.rtb.parsed_url.hostname
        rsync_port = port
        output = subprocess.check_output(
            [ 'rsync', '--port', str(rsync_port), rsync_host + '::images/' ],
            close_fds = True, stderr = subprocess.PIPE)
        # output looks like:
        #
        # drwxrwxr-x          4,096 2018/10/19 00:41:04 .
        # drwxr-xr-x          4,096 2018/10/11 06:24:44 clear:live:25550
        # dr-xr-xr-x          4,096 2018/04/24 23:10:02 fedora:cloud-base-x86-64:28
        # drwxr-xr-x          4,096 2018/10/11 20:52:34 rtk::114
        # ...
        #
        # so we parse for 5 fields, take last
        imagel = tcfl.pos.image_list_from_rsync_output(output)
        for image in imagel:
            print ic.fullid, ":".join(image)

        if image_env:
            image_match = tcfl.pos.image_select_best(image_env, imagel, ic)
            self.report_info("Image '%s' (from env IMAGE) matches: %s"
                             % (image_env, ":".join(image_match)), level = 1)
