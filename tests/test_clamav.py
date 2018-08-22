#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring

import os
import re
import subprocess

import tcfl.tc

class _clamav(tcfl.tc.tc_c):
    """
    Run the ClamAV antivirus, report on files scanned and infected

    Raises a failure if infected files are found, passes if no
    infections found; reports statistics on scanned/infected
    files. Blocks if anything doesn't work as it should.

    Environment:

     - CLAMSCAN_ROOT: where to start scanning (defaults to the parent
       directory of where this file is located)

     - CLAMSCAN_EXTRA_DIRS: list of space separated paths we also
       should scan (defaults to none)
    """

    def eval(self):
        # Collect in which directories we are running
        # Normally this is run in the TCF source tree, to validate it,
        # so start one level up. Unless we have a dirname specified.
        dirname = os.environ.get("CLAMSCAN_ROOT", None)
        if dirname == None:
            dirname = os.path.dirname(__file__)
            dirname = os.path.normpath(os.path.join(dirname, ".."))
            if dirname == "":
                dirname = "."
        extradirs = os.environ.get("CLAMSCAN_EXTRA_DIRS", None)

        # Run the clam scanner
        try:
            cmd = [
                "clamscan",
                "--recursive",
                "--suppress-ok-results",
                # Weird format to be able to skip directories;
                # --exclude dir takes a regex and the format is quite
                # hard to find. I haven't
                "--exclude-dir=/.git/",
                "--exclude-dir=/build/",
                os.path.relpath(dirname)
            ]
            if extradirs:
                cmd += extradirs.split()
            self.report_info("running '%s'" % " ".join(cmd))
            output = subprocess.check_output(cmd, stderr = subprocess.PIPE)
            virus = 0
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                # viruses found
                output = e.output
                virus = 1
            else:
                raise tcfl.tc.blocked_e("clamscan error: %d" % e.returncode,
                                        dict(output = e.output,
                                             returncode = e.returncode))

        # Parse the output, report data and pass/fail/block as needed
        data_regex = re.compile(r"""\
----------- SCAN SUMMARY -----------
Known viruses: [0-9]+
Engine version: [\.0-9]+
Scanned directories: (?P<scanned_directories>[0-9]+)
Scanned files: (?P<scanned_files>[0-9]+)
Infected files: (?P<infected_files>[0-9]+)
""", re.MULTILINE)
        output = unicode(output.decode('UTF-8'))
        self.report_info("ClamAV output", dlevel = 1, alevel = 0,
                         attachments = dict(output = output))
        m = data_regex.search(output)
        if not m:
            raise tcfl.tc.blocked_e("can't parse clamscan statistics",
                                    dict(output = output))
        gd = m.groupdict()
        scanned_files = int(gd["scanned_files"])
        scanned_directories = int(gd["scanned_directories"])
        infected_files = int(gd["infected_files"])
        self.report_data("ClamAV scan",
                         "scanned files", scanned_files)
        self.report_data("ClamAV scan",
                         "scanned directories", scanned_directories)
        self.report_data("ClamAV scan",
                         "infected files", int(gd["infected_files"]))
        if scanned_files == 0:
            raise tcfl.tc.blocked_e("clamscan scanned zero files")
        elif scanned_directories == 0:
            raise tcfl.tc.blocked_e("clamscan scanned zero directories")
        elif virus:
            raise tcfl.tc.failed_e("clamscan found viruses, %d infected files"
                                   % infected_files)
        elif infected_files:
            raise tcfl.tc.blocked_e("clamscan found viruses, %d infected "
                                    "files but didn't report it on the exit "
                                    "code" % infected_files)
        else:
            raise tcfl.tc.pass_e("clamscan found no viruses")
