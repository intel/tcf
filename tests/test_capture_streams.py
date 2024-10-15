#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import json
import os
import time

import commonl.testing
import tcfl.tc
import conf_00_capture_content

srcdir = os.path.dirname(__file__)
ttbd = commonl.testing.test_ttbd(
    config_files = [
        # strip to remove the compiled/optimized version -> get source
        os.path.join(srcdir, "conf_%s" % os.path.basename(__file__.rstrip('cd'))),
        os.path.join(srcdir, "conf_00_capture_content.py"),
    ],
    errors_ignore = [
        "Traceback"
    ])

@tcfl.tc.target(ttbd.url_spec + " and t0")
class _test(tcfl.tc.tc_c):

    @tcfl.tc.subcase()
    def eval_00_list(self, target):
        r = target.capture.list()
        self.report_pass("can list", dict(r = r), dlevel = -1)

    @tcfl.tc.subcase()
    def eval_10_c1_start(self, target):
        r = target.capture.start("c1")
        self.report_pass("c1 starts", dict(r = r), dlevel = -1)


    @tcfl.tc.subcase()
    def eval_15_get_no_args(self, target):
        try:
            target.capture.get()
        except TypeError as e:
            self.report_pass(f"no args caught {type(e)} {e}")

    @tcfl.tc.subcase()
    def eval_15_get_capturer_bad_args(self, target):
        for arg in [ True, False, 1, 1.0, None, {}, [], set() ]:
            with tcfl.msgid_c(subcase = type(arg).__name__):
                try:
                    target.capture.get(arg)
                    self.report_fail(f"bad arg {type(arg)} '{arg}' not caught", level = 0)
                except AssertionError as e:
                    self.report_pass(f"bad arg {type(arg)} '{arg}' caught {type(e)} {e}")
                except:
                    self.report_fail(f"bad arg {type(arg)} '{arg}' not caught", level = 0)

    @tcfl.tc.subcase()
    def eval_15_get_offset_bad_args(self, target):
        for arg in [ 1.0, {}, [], set() ]:	# bool gets converted to 0/1, it seems. Fun.
            with tcfl.msgid_c(subcase = type(arg).__name__):
                try:
                    target.capture.get("c1", offset = arg)
                    self.report_fail(f"bad arg {type(arg)} '{arg}' not caught", level = 0)
                except AssertionError as e:
                    self.report_pass(f"bad arg {type(arg)} '{arg}' caught {type(e)} {e}")
                except:
                    self.report_fail(f"bad arg {type(arg)} '{arg}' not caught", level = 0)

    @tcfl.tc.subcase()
    def eval_20_c1_get(self, target):
        # hmmm, need to clean before? leftovers?
        with tcfl.msgid_c(subcase = 'no-args'):
            r = target.capture.get("c1")
            assert 'default' in r.keys() and 'log' in r.keys(), \
                f"missing keys in {' '.join(r.keys())}"
            for stream_name, file_name in r.items():
                assert os.path.exists(file_name), \
                    f"stream {stream_name}, file {file_name} was not created?"
                self.report_pass(f"stream {stream_name} reports"
                                 f" file {file_name} which has been created")
        with tcfl.msgid_c(subcase = 'log'):
            r = target.capture.get("c1", 'log')
            assert 'log' in r.keys() and len(r.keys()) == 1
            with open(r['log']) as f:
                assert f.read() == conf_00_capture_content.example_log, \
                    "log file contents differ"
                self.report_pass("log file contents match")
        with tcfl.msgid_c(subcase = 'default'):
            r = target.capture.get("c1", 'default')
            assert 'default' in r.keys() and len(r.keys()) == 1

    @tcfl.tc.subcase()
    def eval_20_c1_get_bad_stream(self, target):
        try:
            target.capture.get("c1", 'nonexistantstream')
            self.report_fail("nonexistant stream not caught", level = 0)
        except tcfl.tc.blocked_e:
            self.report_pass("nonexistant stream caught")
        except:
            self.report_fail("nonexistant stream not caught", level = 0)


    @tcfl.tc.subcase()
    def eval_30_c1_start_stop_x2(self, target):
        """
        Stopping twice shouldn't matter, since c1 is an snapshot capturer
        """
        target.capture.start("c1")
        target.capture.stop("c1")
        target.capture.stop("c1")

    @tcfl.tc.subcase()
    def eval_51_c2_stop_x4(self, target):
        """
        Stopping twice shouldn't matter
        """
        target.capture.stop("c2")
        target.capture.stop("c2")
        target.capture.stop("c2")
        target.capture.stop("c2")

    @tcfl.tc.subcase()
    def eval_51_c2_start_start(self, target):
        """
        Stopping twice shouldn't matter
        """
        target.capture.start("c2")
        target.capture.start("c2")
        target.capture.start("c2")
        target.capture.start("c2")
        target.capture.start("c2")

    @tcfl.tc.subcase()
    def eval_51_c2_stop_start_x3(self, target):
        """
        Stopping twice shouldn't matter
        """
        target.capture.stop("c2")
        target.capture.start("c2")
        target.capture.stop("c2")
        target.capture.start("c2")
        target.capture.stop("c2")
        target.capture.start("c2")

    @tcfl.tc.subcase()
    def eval_51_c2_start_stop_x3(self, target):
        """
        Stopping twice shouldn't matter
        """
        target.capture.start("c2")
        target.capture.stop("c2")
        target.capture.start("c2")
        target.capture.stop("c2")
        target.capture.start("c2")
        target.capture.stop("c2")


    @tcfl.tc.subcase()
    def eval_51_c2_start_wait_stop(self, target):
        """
        Stopping twice shouldn't matter
        """
        with self.subcase("start"):
            r = target.capture.start("c2")
            capturing = r.pop('capturing')
            assert capturing == True, \
                ( "not capturing when I should?", dict(r = r) )
            # verify this returns the list of streams with the data file
            # they are capturing to and then matches what the server has
            # posted to the inventory
            data = target.properties_get("interfaces.capture.c2")
            data_streams = data['interfaces']['capture']['c2']['stream']
            data_filenames = {
                stream_name: data_streams[stream_name]['file']
                for stream_name in data_streams
            }
            assert r == data_filenames, \
                ( "returned data mismatches inventory",
                  dict(r = r, inventory = data, data_filenames = data_filenames) )

        # ok, we wait two seconds and download the captured media, we
        # should find in the log at least 3 samples and a broken JSON
        # (because it is not properly terminated)
        time.sleep(2)
        with self.subcase("partial-download"):
            r = target.capture.get("c2")
            with self.subcase("logs"):
                log_data = open(r['log']).read()
                count = log_data.count('DEBUG: capture-example sampling')
                if count < 3:
                    # we are calling it with a 0.5/second sampling
                    # period and waiting two seconds, so we need at
                    # least 4 samples, 3 pressing it -- buffering is
                    # off, so the output shall be captured
                    raise tcfl.tc.failed_e(
                        f'the current log reports only {count} samples, '
                        f' expected at least 3', dict(log_data = log_data))
                if 'INFO: terminating JSON!' in log_data:
                    raise tcfl.tc.failed_e(
                        'the log reports it got finished,'
                        ' when this is supposed to be a half way'
                        ' capture', dict(log_data = log_data))
                target.report_pass("partial download: logs ok")
            with self.subcase("json"):
                try:
                    with open(r['default']) as f:
                        json_data = f.read()
                    json.loads(json_data)
                    raise tcfl.tc.failed_e(
                        "JSON data is valid, but expected it not finished",
                        dict(json_data = json_data))
                except json.decoder.JSONDecodeError:
                    self.report_pass("JSON data is invalid as expected")



        time.sleep(2)

        with self.subcase("stop"):
            r = target.capture.stop("c2")
            capturing = r.pop('capturing', False)
            assert capturing == False, \
                ( "capturing when it should not?", dict(r = r) )
            # verify this returns the list of streams with the data file
            # they are capturing to and then matches what the server has
            # posted to the inventory
            data = target.properties_get("interfaces.capture.c2")
            data_streams = data['interfaces']['capture']['c2']['stream']
            data_filenames = {
                stream_name: data_streams[stream_name]['file']
                for stream_name in data_streams
            }
            assert r == data_filenames, \
                ( "returned data mismatches inventory",
                  dict(r = r, inventory = data, data_filenames = data_filenames) )

        with self.subcase("complete-download"):
            r = target.capture.get("c2")
            with self.subcase("log"):
                log_data = open(r['log']).read()
                assert 'INFO: terminating JSON!' in log_data, (
                    "Can't find 'INFO: terminating JSON' in log",
                    dict(log_data = log_data)
                )
            with self.subcase("json"):
                try:
                    with open(r['default']) as f:
                        json_data = f.read()
                    json.loads(json_data)
                    self.report_pass("JSON data is valid as expected")
                except json.decoder.JSONDecodeError as e:
                    raise tcfl.tc.failed_e(
                        "JSON data is invalid, but expected it valid",
                        dict(json_data = json_data))

    @tcfl.tc.subcase()
    def eval_52_c3_start_stop_change_streams(self, target):
        r_start = target.capture.start("c3")
        self.report_info("started", dict(r = r_start))
        r_stop = target.capture.stop("c3")
        self.report_info("stopped", dict(r = r_stop))
        assert 'log' in r_start
        assert r_start['log'] == 'NAME2'
        assert 'default' in r_start
        assert r_start['default'] == 'NAME1'

        assert 'log' in r_stop
        assert r_stop['log'] == 'NAME2.stop'

        assert 'stream3' in r_stop
        assert r_stop['stream3'] == 'NAME3'

        assert 'default' not in r_stop


    def teardown_90_scb(self):
        ttbd.check_log_for_issues(self)
