#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import json
import subprocess

import ttbl.capture
# This gets imported automatically
#import conf_00_capture_content
# yields example_data, example_log

class _snapshot_c(ttbl.capture.impl_c):
    def __init__(self):
        ttbl.capture.impl_c.__init__(self, True, "application/json",
                                     log = "text/plain")

    def start(self, target, capturer, path):
        default_file = os.path.join(path, capturer + "-somefile.json")
        log_file = os.path.join(path, capturer + "-somefile.log")

        with open(log_file, "w") as of:
            of.write(example_log)
        with open(default_file, "w") as of:
            json.dump(example_data, of)
        return False, {
            "default": capturer + "-somefile.json",
            "log": capturer + "-somefile.log"
        }


class _stream_c(ttbl.capture.impl_c):

    def __init__(self):
        ttbl.capture.impl_c.__init__(self, False, "application/json",
                                     log = "text/plain")


    def start(self, target, capturer, path):
        # no need for a timestamp because we can only capture one at the time
        stream_filename = capturer + ".data.json"
        log_filename = capturer + ".capture.log"
        pidfile = "%s/capture-%s.pid" % (target.state_dir, capturer)

        logf = open(os.path.join(path, log_filename), "w+")
        p = subprocess.Popen(
            [
                "stdbuf", "-e0", "-o0",
                os.path.join(os.path.dirname(ttbl.capture.__file__),
                             "..", "capture-example.py"),
                os.path.join(path, stream_filename),
                "30",
                "0.5",
            ],
            bufsize = -1,
            close_fds = True,
            shell = False,
            stderr = subprocess.STDOUT,
            stdout = logf.buffer)

        with open(pidfile, "w+") as pidf:
            pidf.write("%s" % p.pid)
        ttbl.daemon_pid_add(p.pid)

        return True, {
            "default": stream_filename,
            "log": log_filename
        }


    def stop(self, target, capturer, path):
        pidfile = "%s/capture-%s.pid" % (target.state_dir, capturer)
        commonl.process_terminate(pidfile, tag = "capture:" + capturer,
                                  # give plenty of time to flush
                                  wait_to_kill = 2)


class _stream3_c(ttbl.capture.impl_c):
    # capturer that changes stream on stop
    def __init__(self):
        ttbl.capture.impl_c.__init__(self, False, "application/json",
                                     log = "text/plain")


    def start(self, target, capturer, path):
        return True, {
            "default": "NAME1",
            "log": "NAME2",
        }


    def stop(self, target, capturer, path):
        return {
            "log": "NAME2.stop",
            "stream3": "NAME3",
        }


target = ttbl.test_target("t0")
ttbl.config.target_add(target)
target.interface_add(
    "capture", ttbl.capture.interface(
        c1 = _snapshot_c(),
        c2 = _stream_c(),
        c3 = _stream3_c(),
    )
)
