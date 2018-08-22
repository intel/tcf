#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import unittest

import expecter
import tc

def debug_log(msg, attachments = None):
    print msg
    if attachments:
        for attachment, content in attachments.iteritems():
            print "attachment %s: %s" % (attachment, content)


text = """ Lorem ipsum dolor sit amet, consectetuer adipiscing elit.  Mauris
ac felis vel velit tristique imperdiet.  Praesent augue.  Cras
placerat accumsan nulla.  Vivamus id enim.  Etiam vel tortor sodales
tellus ultricies commodo.  Aliquam erat volutpat.  Proin quam nisl,
tincidunt et, mattis eget, convallis nec, purus.  Fusce sagittis,
libero non molestie mollis, magna orci ultrices dolor, at vulputate
neque nulla lacinia eros.  Curabitur lacinia pulvinar nibh.  Cras
placerat accumsan nulla.  Donec pretium posuere tellus.  Nam
vestibulum accumsan nisl.  Nullam tristique diam non turpis.  Nullam
eu ante vel est convallis dignissim.  Sed bibendum.  Etiam laoreet
quam sed arcu.  Nunc eleifend leo vitae magna.  Sed bibendum.
Praesent augue.  Praesent fermentum tempor tellus.  Sed id ligula quis
est convallis tempor.  Phasellus at dui in ligula mollis ultricies.
Vestibulum convallis, lorem a tempus semper, dui dui euismod elit,
vitae placerat urna tortor vitae lacus.  Sed id ligula quis est
convallis tempor.  Donec vitae dolor.  Nullam tempus.  Phasellus
purus.  Pellentesque dapibus suscipit ligula.  Nam a sapien.  Nullam
libero mauris, consequat quis, varius et, dictum id, arcu.  Curabitur
vulputate vestibulum lorem.  Donec hendrerit tempor tellus.  Donec
posuere augue in quam.  Pellentesque condimentum, magna ut suscipit
hendrerit, ipsum augue ornare nulla, non luctus diam neque sit amet
urna.  Mauris mollis tincidunt felis.  Etiam laoreet quam sed arcu.
Vivamus id enim.  Nullam rutrum.  Praesent augue.  """

class fake_rtb(object):
    @staticmethod
    def rest_tb_target_console_read_to_fd(
            ofd, target, console, offset, max_size, ticket):
        # Every time we read we only read 30 chars, so we can see in
        # the text where are we going to be
        os.write(ofd, text[offset : offset + 30])

class fake_target(object):
    """
    """
    def __init__(self, name):
        self.id = name
        self.fullid = "local_" + name
        self.rtb = fake_rtb()
        self.kws = dict(tc_hash = "TESTHASH")
    def wait(self, text_regex, timeout, console = None):
        self.e.add(expecter.debug_rx_poller, (),)
        return False

def debug_rx_poller(e, target, console = None):
    global text
    _, id_str = expecter.console_mk_code(target, console)
    offset = e.buffers.get(id_str, 0)
    if offset == 0:
        e.buffers[id_str + "-data"] = text[:30]
        e.buffers[id_str] = 30
    else:
        new_text = text[offset:offset+30]
        e.buffers[id_str + "-data"] += new_text
        e.buffers[id_str] += 30

class _test_expecter(unittest.TestCase):
    longMessage = True
    serial = None

    def test_01(self):
        e = expecter.expecter_c(debug_log, 10, 1)
        e.add(expecter.console_rx_eval, ("console1", 43, "fail"),)
        self.assertEqual(len(e.functors), 1)
        e.remove(expecter.console_rx_eval, ("console1", 43, "fail"),)
        self.assertEqual(e.functors, [])

    def test_02(self):
        e = expecter.expecter_c(debug_log, 10, 1)
        e.add(expecter.console_rx_eval, ("console1", 43, "fail"),)
        e.add(expecter.console_rx_eval, ("console1", 43, "fail"),)
        self.assertEqual(len(e.functors), 1)

    def test_03(self):
        t = fake_target("target1")
        # T = 10, timeout = 1, we'll only run once before timing out
        e = expecter.expecter_c(debug_log, 10, 1)
        _, id_str = expecter.console_mk_code(t, "console-1")
        e.add(debug_rx_poller, (t, "console-1"),)
        with self.assertRaises(tc.failed_e):
            # We fail with timeout
            e.run()
        # Read only 30 chars
        self.assertEqual(e.buffers[id_str + "-data"], text[:30])
        self.assertEqual(e.buffers[id_str], 30)
        # When we repeat, the buffers are cleared, so we shall fail
        # the same and get the same in the buffers.
        with self.assertRaises(tc.failed_e):
            e.run()
        self.assertEqual(e.buffers[id_str + "-data"], text[:30])
        self.assertEqual(e.buffers[id_str], 30)

    def test_04(self):
        t = fake_target("target1")
        # T = 1, timeout = 2, we'll run twice before timing out
        e = expecter.expecter_c(debug_log, 1, 2)
        _, id_str = expecter.console_mk_code(t, "console-1")
        e.add(debug_rx_poller, (t, "console-1"),)
        with self.assertRaises(tc.failed_e):
            # We fail with timeout
            e.run()
        # Read twice, so 60 chars off our block of text
        self.assertEqual(e.buffers[id_str + "-data"], text[:60])
        self.assertEqual(e.buffers[id_str], 60)

    def test_05(self):
        t = fake_target("target1")
        # T = 1, timeout = 2, we'll run once
        e = expecter.expecter_c(debug_log, 1, 2)
        e.add(expecter.console_rx_poller, (t, "console-1"),)
        e.add(expecter.console_rx_eval,
              (t, "Lorem ipsum dolor", "console-1"),)
        with self.assertRaises(tc.pass_e):
            e.run()

    def test_06(self):
        t = fake_target("target1")
        # T = 1, timeout = 1, we'll run once
        e = expecter.expecter_c(debug_log, 1, 1)
        e.add(expecter.console_rx_poller, (t, "console-1"),)
        # Will fail because the text we are expecting is on for the
        # second run only
        e.add(expecter.console_rx_eval,
              (t, "nsectetuer adipiscing ", "console-1"),)
        with self.assertRaises(tc.failed_e):
            e.run()

    def test_07(self):
        t = fake_target("target1")
        # T = 1, timeout = 2, we'll run twice
        e = expecter.expecter_c(debug_log, 1, 2)
        e.add(expecter.console_rx_poller, (t, "console-1"),)
        # Will pass as we did the second run
        e.add(expecter.console_rx_eval,
              (t, "nsectetuer adipiscing ", "console-1"),)
        with self.assertRaises(tc.pass_e):
            e.run()

    def test_08(self):
        t = fake_target("target1")
        # T = 1, timeout = 2, we'll run twice
        e = expecter.expecter_c(debug_log, 1, 2)
        e.add(expecter.console_rx_poller, (t, "console-1"),)
        # Will get a skip, as we said so
        e.add(expecter.console_rx_eval,
              (t, "nsectetuer adipiscing ", "console-1", None, "skip"),)
        with self.assertRaises(tc.skip_e):
            e.run()

    def test_09(self):

        e = expecter.expecter_c(debug_log, 10, 1)
        e.add(expecter.console_rx_eval, ("console1", 43, "fail"),)
        e.add(expecter.console_rx_eval, ("console1", 43, "fail"),)
        e.add(expecter.console_rx_eval, ("console1", 44, "fail"),)
        self.assertEqual(len(e.functors), 2)

    def test_10(self):
        t = fake_target("target1")
        # T = 1, timeout = 2, we'll run twice
        e = expecter.expecter_c(debug_log, 1, 2)
        e.add(expecter.console_rx_poller, (t, "console-1"),)
        # Will get a skip, as we said so
        e.add(expecter.console_rx_eval,
              (t, "nsectetuer adipiscing ", "console-1", None, "fail"),)
        with self.assertRaises(tc.failed_e):
            e.run()

    def test_11(self):
        t = fake_target("target1")
        # T = 1, timeout = 2, we'll run twice
        e = expecter.expecter_c(debug_log, 1, 2)
        e.add(expecter.console_rx_poller, (t, "console-1"),)
        # Will get a skip, as we said so
        e.add(expecter.console_rx_eval,
              (t, "nsectetuer adipiscing ", "console-1", None, "blck"),)
        with self.assertRaises(tc.blocked_e):
            e.run()

    @staticmethod
    def bad_code():
        this_will_raise_an_exception

    def test_12(self):
        fake_target("target1")
        # T = 1, timeout = 2, we'll run twice
        e = expecter.expecter_c(debug_log, 1, 2)
        # add some bad code, raises an exception
        e.add(self.bad_code, None)
        with self.assertRaises(Exception):
            e.run()

    # Now the same thing, but with a regular expression
    def test_13(self):
        r = re.compile("^ Lorem ipsum dolor sit amet, c$")
        t = fake_target("target1")
        # T = 1, timeout = 2, we'll run once
        e = expecter.expecter_c(debug_log, 1, 2)
        e.add(expecter.console_rx_poller, (t, "console-1"),)
        e.add(expecter.console_rx_eval,
              (t, r, "console-1"),)
        with self.assertRaises(tc.pass_e):
            e.run()


unittest.main(failfast = True)
