#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import time

import commonl.testing
import tcfl.tc

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd')))
    ],
    errors_ignore = [
        "Traceback"
    ])

@tcfl.tc.target("t0")
class flashes(tcfl.tc.tc_c):
    """
    Test the estimated_duration field from the imaging flasing
    interface is acknolwedged by the flashing interface.
    """
    @staticmethod
    def eval(target):
        ts0 = time.time()
        target.images.flash({ "image0": __file__ })
        ts1 = time.time()
        # this shall take around 80% of 10s, so we configured it
        delta = abs(10 - (ts1 - ts0))
        if delta > 1:
            raise tcfl.tc.failed_e(
                "image0 flashing expected to take around 10s, took %s (%s)"
                % (ts1 - ts0, delta))

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)


@tcfl.tc.target("t0")
class flasher_timesout(tcfl.tc.tc_c):
    """
    Test the estimated_duration field from the imaging flasing
    interface is acknolwedged by the flashing interface.
    """
    @staticmethod
    def eval(target):
        # shall error because the flashing command will timeout
        try:
            target.images.flash(
                { "image_timesout": __file__ },
                # estimated_duration set to 5 so the flasher (that lasts
                # 10secs) timesout, so force the client timeout longer
                timeout = 15)
        except tcfl.tc.error_e as e:
            if 'flashing failed: timedout after' not in str(e):
                raise tcfl.tc.failed_e(
                    "Unexpected exception; expected error_e with timeout",
                    dict(unexpected_exception = e))

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)



@tcfl.tc.target("t0")
class flashes_two_in_parallel(tcfl.tc.tc_c):
    """
    Test the estimated_duration field from the imaging flasing
    interface is acknolwedged by the flashing interface.
    """
    @staticmethod
    def eval(target):
        ts0 = time.time()
        target.images.flash({
            "image_p0": __file__,
            "image_p1": __file__
        })
        ts1 = time.time()
        # this shall take around 80% of 13s (declared estimated
        # duration), to prove they were done in parallel
        delta = ts1 - ts0
        if delta > 13:
            raise tcfl.tc.failed_e(
                "image_p0/image_p1 flashing expected to take around "
                "13s, took %s, did it parallelize?" % delta)
        target.report_pass("image_p0/image_p1 flashing took %.1fs" % delta)

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)


@tcfl.tc.target("t0")
class flashes_two_in_parallel_one_serial(tcfl.tc.tc_c):
    """
    Test the estimated_duration field from the imaging flasing
    interface is acknolwedged by the flashing interface.
    """
    @staticmethod
    def eval(target):
        ts0 = time.time()
        target.images.flash({
            "image0": __file__,
            "image_p0": __file__,
            "image_p1": __file__
        })
        ts1 = time.time()
        # this shall take around 20 secs, since 10+10 for image_p* and
        # 10 for image0 serially
        delta = ts1 - ts0
        expected = 10 + 10
        if abs(delta - expected) < 3:
            raise tcfl.tc.failed_e(
                "flashing time took %.1fs, expected %.1fs" % (delta, expected))
        target.report_pass("image0+image_p0/image_p1 flashing took %.1fs" % delta)

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)

@tcfl.tc.target("t0")
class serial_timesout(tcfl.tc.tc_c):
    """
    Run two parallel and one serial

    The serial one timesout (image_timeout is set to take double the
    the estimated_duration
    """
    @staticmethod
    def eval(target):
        try:
            # set to last 10, but estimated_timeout to 5, sowe wait
            # for longer and want to see the server complaining it
            # timed out
            #
            # -> t0: images/flash: remote call failed: 400: t0: image_timesout: flashing failed: timedout after 5s'
            target.images.flash({
                "image_timesout": __file__,
            }, timeout = 15)
            raise tcfl.tc.failed_e(
                "flash() didn't raise error when flashing image_timesout"
                " that shall timeout in the server")
        except tcfl.tc.error_e as e:
            message = e.args[0]
            if 'image_timesout: flashing failed: timedout' not in message:
                raise tcfl.tc.error_e(
                    "server error, but not because of the impl timing"
                    " out", dict(exception = e))
            ttbd.errors_ignore.append(
                # might mask others, sigh -- but there is no way to
                # latch it to context with the per line searching we
                # do now
                "RuntimeError(msg)")
            ttbd.errors_ignore.append(
                "image_timesout: flashing failed: timedout")

    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
