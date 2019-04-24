#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import contextlib
import os

import tc
import ttb_client

def _rest_tb_target_capture_start(rtb, rt, capturer, ticket = ''):
    assert isinstance(capturer, basestring)
    rtb.send_request("POST", "targets/%s/capture/start" % rt['id'],
                     data = { 'capturer': capturer, 'ticket': ticket })

def _rest_tb_target_capture_stop_and_get(rtb, rt, capturer, local_filename,
                                         ticket = ''):
    assert isinstance(capturer, basestring)
    with open(local_filename, "w") as lf, \
        contextlib.closing(rtb.send_request(
            "POST", "targets/%s/capture/stop_and_get" % rt['id'],
            data = { 'capturer': capturer, 'ticket': ticket },
            stream = True, raw = True)) as r:
        # http://docs.python-requests.org/en/master/user/quickstart/#response-content
        chunk_size = 1024
        total = 0
        for chunk in r.iter_content(chunk_size):
            os.write(lf.fileno(), chunk)
            total += len(chunk)
    return total

def _rest_tb_target_capture_list(rtb, rt, ticket = ''):
    return rtb.send_request("GET", "targets/%s/capture/list" % rt['id'],
                            data = { 'ticket': ticket })

class extension(tc.target_extension_c):
    """
    """

    def __init__(self, target):
        tc.target_extension_c.__init__(self, target)
        if not 'capture' in target.rt.get('interfaces', []):
            raise self.unneeded

    def start(self, capturer):
        self.target.report_info("%s: starting capture" % capturer, dlevel = 1)
        _rest_tb_target_capture_start(self.target.rtb, self.target.rt,
                                      capturer, ticket = self.target.ticket)
        self.target.report_info("%s: started capture" % capturer)

    def get(self, capturer, local_filename):
        self.target.report_info("%s: stopping capture" % capturer, dlevel = 1)
        r = _rest_tb_target_capture_stop_and_get(
            self.target.rtb, self.target.rt,
            capturer, local_filename, ticket = self.target.ticket)
        self.target.report_info("%s: stopped capture, %d bytes"
                                % (capturer, r))
        return r

    def list(self):
        self.target.report_info("listing", dlevel = 1)
        data = _rest_tb_target_capture_list(self.target.rtb, self.target.rt,
                                            ticket = self.target.ticket)
        capturers = data['capturers']
        self.target.report_info("listed: %s" % capturers)
        return capturers


def cmdline_capture_start(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    _rest_tb_target_capture_start(rtb, rt,
                                  args.capturer, ticket = args.ticket)

def cmdline_capture_stop_and_get(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    r = _rest_tb_target_capture_stop_and_get(
        rtb, rt,
        args.capturer, args.filename, ticket = args.ticket)
    return r

def cmdline_capture_list(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    data = _rest_tb_target_capture_list(rtb, rt, ticket = args.ticket)
    capturers = data['capturers']
    for name, state in capturers.iteritems():
        if state:
            _state = 'capturing'
        else:
            _state = 'off'
        print "%s:%s" % (name, _state)


def cmdline_setup(argsp):
    ap = argsp.add_parser("capture-start", help = "start capturing")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should start")
    ap.set_defaults(func = cmdline_capture_start)

    ap = argsp.add_parser("capture-get", help = "stop capturing "
                          "and get the result to a file")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should stop")
    ap.add_argument("filename", action = "store", type = str,
                    help = "File to which to dump the captured content")
    ap.set_defaults(func = cmdline_capture_stop_and_get)

    ap = argsp.add_parser("capture-list", help = "List available capturers")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = cmdline_capture_list)
