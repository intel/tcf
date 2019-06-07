#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Capture screenshots or video/audio stream from the target
---------------------------------------------------------

"""
import contextlib
import os

from . import tc
from . import ttb_client

def _rest_tb_target_capture_start(rtb, rt, capturer, ticket = ''):
    assert isinstance(capturer, str)
    return rtb.send_request("POST", "targets/%s/capture/start" % rt['id'],
                            data = { 'capturer': capturer, 'ticket': ticket })

def _rest_tb_target_capture_stop_and_get(rtb, rt, capturer, local_filename,
                                         ticket = ''):
    assert isinstance(capturer, str)
    total = 0
    if local_filename != None:
        with open(local_filename, "w") as lf, \
            contextlib.closing(rtb.send_request(
                "POST", "targets/%s/capture/stop_and_get" % rt['id'],
                data = { 'capturer': capturer, 'ticket': ticket },
                stream = True, raw = True)) as r:
            # http://docs.python-requests.org/en/master/user/quickstart/#response-content
            chunk_size = 1024
            for chunk in r.iter_content(chunk_size):
                os.write(lf.fileno(), chunk)
                total += len(chunk)
    return total

def _rest_tb_target_capture_list(rtb, rt, ticket = ''):
    return rtb.send_request("GET", "targets/%s/capture/list" % rt['id'],
                            data = { 'ticket': ticket })

class extension(tc.target_extension_c):
    """
    When a target supports the *capture* interface, it's
    *tcfl.tc.target_c* object will expose *target.capture* where the
    following calls can be made to capture data from it.

    A streaming capturer will start capturing when :meth:`start` is
    called and stop when :meth:`stop_and_get` is called, bringing the
    capture file from the server to the machine executing *tcf run*.

    A non streaming capturer just takes a snapshot when :meth:`get`
    is called.

    You can find available capturers with :meth:`list` or::

      $ tcf capture-list TARGETNAME
      vnc0:ready
      screen:ready
      video1:not-capturing
      video0:ready

    a *ready* capturer is capable of taking screenshots only

    or::

      $ tcf list TARGETNAME | grep capture:
        capture: vnc0 screen video1 video0

    """

    def __init__(self, target):
        tc.target_extension_c.__init__(self, target)
        if not 'capture' in target.rt.get('interfaces', []):
            raise self.unneeded

    def start(self, capturer):
        """
        Start capturing the stream with capturer *capturer*

        (if this is not an streaming capturer, nothing happens)

        >>> target.capture.start("screen_stream")

        :param str capturer: capturer to use, as listed in the
          target's *capture*
        :returns: dictionary of values passed by the server
        """
        self.target.report_info("%s: starting capture" % capturer, dlevel = 1)
        r = _rest_tb_target_capture_start(self.target.rtb, self.target.rt,
                                          capturer,
                                          ticket = self.target.ticket)
        self.target.report_info("%s: started capture" % capturer)
        return r

    def stop_and_get(self, capturer, local_filename):
        """
        If this is a streaming capturer, stop streaming and return the
        captured data or if no streaming, take a snapshot and return it.

        >>> target.capture.stop_and_get("screen_stream", "file.avi")
        >>> target.capture.get("screen", "file.png")
        >>> network.capture.get("tcpdump", "file.pcap")

        :param str capturer: capturer to use, as listed in the
          target's *capture*
        :param str local_filename: file to which to write the capture.
        :returns: dictionary of values passed by the server
        """
        self.target.report_info("%s: stopping capture" % capturer, dlevel = 1)
        r = _rest_tb_target_capture_stop_and_get(
            self.target.rtb, self.target.rt,
            capturer, local_filename, ticket = self.target.ticket)
        self.target.report_info("%s: stopped capture, %d bytes"
                                % (capturer, r))
        return r

    def stop(self, capturer):
        """
        If this is a streaming capturer, stop streaming and discard
        the captured content.

        >>> target.capture.stop("screen_stream")

        :param str capturer: capturer to use, as listed in the
          target's *capture*
        """
        self.target.report_info("%s: stopping capture" % capturer, dlevel = 1)
        _rest_tb_target_capture_stop_and_get(
            self.target.rtb, self.target.rt,
            capturer, None, ticket = self.target.ticket)
        self.target.report_info("%s: stopped capture" % capturer)

    def get(self, capturer, local_filename):
        """
        This is the same :meth:`stop_and_get`.
        """
        return self.stop_and_get(capturer, local_filename)
    
    def list(self):
        """
        List capturers available for this target.

        >>> r = target.capture.list()
        >>> print r
        >>> {'screen': 'ready', 'audio': 'not-capturing', 'screen_stream': 'capturing'}

        :returns: dictionary of capturers and their state
        """
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

def cmdline_capture_stop(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    r = _rest_tb_target_capture_stop_and_get(
        rtb, rt,
        args.capturer, None, ticket = args.ticket)
    return r

def cmdline_capture_list(args):
    rtb, rt = ttb_client._rest_target_find_by_id(args.target)
    data = _rest_tb_target_capture_list(rtb, rt, ticket = args.ticket)
    capturers = data['capturers']
    capture_spec = {}
    for capture in rt['capture'].split():
        capturer, streaming, mimetype = capture.split(":", 2)
        capture_spec[capturer] = (streaming, mimetype)
    for name, state in capturers.items():
        print("%s:%s:%s:%s" % (
            name, capture_spec[name][0], capture_spec[name][1], state))


def cmdline_setup(argsp):
    ap = argsp.add_parser("capture-start", help = "start capturing")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should start")
    ap.set_defaults(func = cmdline_capture_start)

    ap = argsp.add_parser("capture-get",
                          help = "stop capturing and get the result to a file")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should stop")
    ap.add_argument("filename", action = "store", type = str,
                    help = "File to which to dump the captured content")
    ap.set_defaults(func = cmdline_capture_stop_and_get)

    ap = argsp.add_parser("capture-stop-and-get",
                          help = "stop capturing and get the result to a file")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should stop")
    ap.add_argument("filename", action = "store", type = str,
                    help = "File to which to dump the captured content")
    ap.set_defaults(func = cmdline_capture_stop_and_get)

    ap = argsp.add_parser("capture-stop", help = "stop capturing, discarding "
                          "the capture")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should stop")
    ap.set_defaults(func = cmdline_capture_stop)

    ap = argsp.add_parser("capture-list", help = "List available capturers")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = cmdline_capture_list)
