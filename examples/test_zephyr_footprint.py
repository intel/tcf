#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import pprint
import re
import subprocess

import tcfl.tc
import tcfl.tl

@tcfl.tc.tags(**tcfl.tl.zephyr_tags())
# Ask for a target that defines an zephyr_board field, which indicates
# it can run the Zephyr OS
@tcfl.tc.target("zephyr_board",
                app_zephyr = os.path.join(tcfl.tl.ZEPHYR_BASE,
                                          "tests", "benchmarks", "footprint"))
@tcfl.tc.tags(ignore_example = True)
class _test(tcfl.tc.tc_c):
    _build_serially = True
    build_only = [ "here" ]

    @tcfl.tc.serially()
    def build_60_something(self, target):
        # FIXME: target.expect("Hello World! %s" % target.bsp_model)
        #self.report_info("target kws %s" % pprint.pformat(target.kws))

        cmdline = [
            os.path.join(tcfl.tl.ZEPHYR_BASE, "scripts", "sanitycheck"),
            "-z",
            os.path.join(target.kws['zephyr_objdir'], "zephyr", "zephyr.elf")
        ]

        self.report_info("running %s" % " ".join(cmdline), dlevel = 1)
        s = subprocess.check_output(cmdline, stderr = subprocess.STDOUT)
        r_sections = re.compile(
            r"(?P<section_name>[A-Za-z0-9]+)\s+"
            r"(?P<vma>0x[0-9a-fA-F]+)\s+"
            r"(?P<lma>0x[0-9a-fA-F]+)\s+"
            r"(?P<size>[0-9]+)\s+"
            r"(?P<hexsize>0x[0-9a-fA-F]+)\s+(?P<type>[a-z]+)")
        r_totals = re.compile(r"Totals: (?P<rom>[0-9]+) bytes \(ROM\), "
                              r"(?P<ram>[0-9]+) bytes \(RAM\)")
        sections = []
        totals = None
        for line in s.split('\n'):
            m = r_sections.match(line)
            if m:
                sections.append(m.groupdict())
                continue
            m = r_totals.match(line)
            if m:
                totals = m.groupdict()
                continue

        # now deal with the totals
        if totals == None:
            raise tcfl.tc.blocked_e("Could not find data?",
                                    { "output": s })
        for section in sections:
            name = section['section_name']
            for key, val in section.items():
                target.report_data("Footprint %(zephyr_board)s",
                                   name + "/" + key, val)
        for key, val in totals.items():
            target.report_data("Footprint %(zephyr_board)s", key, val)
