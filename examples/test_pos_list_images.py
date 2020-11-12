#! /usr/bin/python3
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

def _target_ic_kws_get(target, ic, kw, default = None):
    return target.kws.get(kw, ic.kws.get(kw, default))

@tcfl.tc.interconnect(mode = "all")
@tcfl.tc.target("pos_capable")
class _(tcfl.tc.tc_c):
    """
    List images available in a POS rsync server
    """
    def eval(self, ic, target):
        ic.power.on()
        rsync_server = _target_ic_kws_get(
            target, ic, 'pos.rsync_server',
            _target_ic_kws_get(target, ic, 'pos_rsync_server', None))
        self.report_info("POS rsync server: %s" % rsync_server)

        rsync_host = rsync_server.split("::", 1)[0]
        if rsync_host == ic.rtb.parsed_url.hostname:
            rsync_port = ic.tunnel.add(873, ic.kws['ipv4_addr'])
        else:
            rsync_port = 873

        output = subprocess.check_output(
            [ 'rsync', '--port', str(rsync_port), rsync_server + '/' ],
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
            print(ic.fullid, ":".join(image))

        if image_env:
            image_match = tcfl.pos.image_select_best(image_env, imagel, ic)
            self.report_info("Image '%s' (from env IMAGE) matches: %s"
                             % (image_env, ":".join(image_match)), level = 1)
