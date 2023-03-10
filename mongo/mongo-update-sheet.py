#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME:
#
# - hack runid to look like YY/MM/DD HH:MM:00.BBB so we can display it
#   as a date/time and gives us build density and better display
#
# - use with temp_matrix the same trick we use with key_values to
#   insert new columns (rows in this case) so we don't have to update
#   the whole thing (faster)

# - change cmd line handing of refresh / redo; --runid means refresh
#   that, --ws-runid means append that to the chart. Add instead
#   --refresh all, --ws-refresh?
# - breakup sheet_update in smaller chunks
#
# - document the flow
# - general sanitization of the code
# - add "DB"
# - timings must be properly calculated
# - add # targets / server (to make sure all servers are running)
# - if index is not present, make it automatically
"""
Generate summaries of TCF data saved to MongoDB

A TCF run can be configured to save result records to a MongoDB
database at URL, named DB, collection CID. This script then
issues requests to the database to generate summaries and charts that
are uploaded to a Google Sheet that give a visual and trends of:

- test case execution summary results (pass/errr/fail/block/skip)
- coverage, pass rate, blockage rate, totals
- server resources consumption
- frequency of errors, failures per test case across runs
- errors / failures per target type
- report of non-passing testcases (for triaging)
- frequency of blockage per target (for triaging broken targets)
- miscelaneous KPIs

If a --runid RUNID is specified, any runid stored in the database that
simple-string sorts equal or higher than RUNID will be processed and
added/updated to a summary database called
URL:DB:CID_summary_per_run. If none specifed, no summary DB updates
will be done.

If a Google Sheet id is specified with -i (along with other needed
auth data in -c and -s) then the sheet will be updated with data from
the summary DB.

"""
_internal_doc = """

Google Spreadsheet
------------------

 - sheets named _SOMETHING are internal tables, used as reference to
   plot charts

 - Charts: basic formatting done, but adjustments (that will be
   respected) will be needed.


Call flow
---------

main
  _mongo_mk_indexes()

  _summary_refresh()
     _runids_postprocess_summary_per_run()
     _runids_postprocess_blocked_per_target()
     _runids_postprocess_failures_per_target_type()

  sheet_update()
    URL:DB:COLLECTION_summary_by_run.find()
    sheet_update_spr()        # Summary per run
    sheet_update_fpbt()       # Failures per board type
    sheet_update_ff()         # Failure frequency
    sheet_update_nptcs()      # Non passing test cases
    sheet_update_bpt()        # Blockage per target
    sheet_update_fpt()        # Failure per target
    # KPI sheets

"""
# pylint: disable = bad-whitespace
import collections

import argparse
import bisect
import errno
import logging
import oauth2client
import oauth2client.tools
import pickle
import pprint
import pymongo
import re
import ssl
import sys
import time
import urllib.parse

import googlel
import googleapiclient.errors
import mongol

db = None
summary_collection = None

class timestamp_c(object):
    def __init__(self):
        self.ts = time.time()

    def tick(self, message = ""):
        now = time.time()
        print("TICK %.2fs %s" % (now - self.ts, message))
        self.ts = now

t = timestamp_c()


def _mongo_mk_indexes_collection(collection):
    # index for sorting all records so _iterate_non_passing() can
    # sort them descending and just pick the top
    print("%s: setting index" % collection.name)
    collection.create_index(
        [
            ('runid', pymongo.DESCENDING),
            ('hashid', pymongo.DESCENDING),
        ],
        background = True,
        name = "runid-hash",
        # Ensure the index only considers the documents that have all of
        # the listed fields.
        partialFilterExpression = {
            'runid': { "$exists": True },
            'hashid': { "$exists": True },
        }
    )
    collection.create_index(
        [
            ('runid', pymongo.DESCENDING),
        ],
        background = True,
        name = "runid",
        # Ensure the index only considers the documents that have all of
        # the listed fields.
        partialFilterExpression = {
            'runid': { "$exists": True },
            'hashid': { "$exists": True },
        }
    )
    collection.create_index(
        [
            ('tc_name', pymongo.DESCENDING),
        ],
        background = True,
        name = "tc_name",
        # Ensure the index only considers the documents that have all of
        # the listed fields.
        partialFilterExpression = {
            'tc_name': { "$exists": True },
        }
    )

def _mongo_mk_indexes():
    for collection_name in db.collection_names():
        if collection_name == "system.profile":
            continue
        if collection_name.endswith("summary_per_run"):
            continue
        try:
            _mongo_mk_indexes_collection(db[collection_name])
        except pymongo.errors.OperationFailure as e:
            if 'Index with name: runid-hash already exists with different options' not in str(e):
                raise
            # exists with a different options, that's ok, it exists--we let it be

#
# RunIDs can be raw or cooked (or the same)
#
# The raw runid (aka: runid_raw) is what is in the main database with
# the raw data.
#
# The cooked runid (aka: runid) is what is in the summary database,
# and is useful for display purposes.
#
# It has to be possible to convert from raw to cooked and back;
# command line always uses raw runid.
#
runid_raw_prefix = "ci-"
runid_raw_prefix_len = len(runid_raw_prefix)

def _runid_from_raw(runid_raw):
    if runid_raw.startswith(runid_raw_prefix):
        return runid_raw[runid_raw_prefix_len:]
    return runid_raw

def _runid_to_raw(runid_raw):
    assert not runid_raw.startswith(runid_raw_prefix)
    return runid_raw_prefix + runid_raw

def _runid_settle(runid):
    if runid.startswith(runid_raw_prefix):
        runid_raw = runid
        runid = runid[runid_raw_prefix_len:]
    else:
        runid_raw = runid_raw_prefix + runid
    return runid, runid_raw


def _runids_postprocess_summary_per_component(runid_raw):
    return db[args.collection_id]\
        .aggregate([
            {
                "$match": {
                    # match on both fields so the runid-hash index is used
                    "runid": runid_raw,
                    "hashid": { "$exists": True },
                }
            },
            {
                "$project" : {
                    # 1 means pass these through
                    "runid": 1,
                    "result": 1,
                    "components": 1,
                },
            },
            {
                # For each document with one than more component,
                # flatten it into N documents with one component each,
                # to make it easier on the accounting per-component below.
                '$unwind' : '$components'
            },
            {
                # All these $TOKEN are mongodb commands on how to run an
                # aggregation, when in the place of a key. When they are on a
                # value, they refer mostly to a field in the document
                "$group": {
                    "_id": { 'runid': '$runid', 'component': '$components' },
                    # Count all testcases we are running
                    "total": { "$sum" : 1 },
                    # Count passing, failing, blocked and skipped
                    "pass": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "PASS" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "fail": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "FAIL" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "errr": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "ERRR" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "blck": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "BLCK" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "skip": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "SKIP" ] },
                                1,
                                0
                            ]
                        },
                    },
                }
            }
        ], allowDiskUse = True)


def _runids_postprocess_summary_per_target_types(runid_raw):
    return db[args.collection_id]\
        .aggregate([
            {
                "$match": {
                    # match on both fields so the runid-hash index is used
                    "runid": runid_raw,
                    "hashid": { "$exists": True },
                }
            },
            {
                "$project" : {
                    # 1 means pass these through
                    "runid": 1,
                    "result": 1,
                    "target_types": 1,
                },
            },
            {
                # All these $TOKEN are mongodb commands on how to run an
                # aggregation, when in the place of a key. When they are on a
                # value, they refer mostly to a field in the document
                "$group": {
                    "_id": { 'runid': '$runid', 'target_types': '$target_types' },
                    # Count all testcases we are running
                    "total": { "$sum" : 1 },
                    # Count passing, failing, blocked and skipped
                    "pass": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "PASS" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "fail": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "FAIL" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "errr": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "ERRR" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "blck": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "BLCK" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "skip": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "SKIP" ] },
                                1,
                                0
                            ]
                        },
                    },
                }
            }
        ], allowDiskUse = True)


def _runids_postprocess_summary_per_run(runid_raw):
    # Agregate results to generate summaries
    # http://api.mongodb.com/python/current/examples/aggregation.html#aggregation
    #
    # This is what I call a horrible function from a horrible
    # language...but so is doing things with JSON.
    #
    # So first we filter the only records we want to deal with (>
    # args.runid) in the first two $match blocks; then we extract the
    # fields we care for and we $group by runid running a number of
    # tallys, which then we manipulate further in a couple of final
    # $project steps
    #
    # The different agreggation phases will collect the data and
    # further reduce it until we have what we need. Later when we read
    # the summary we might do some more reduction in Python depending
    # on the charts we are looking at.
    #
    # Probably we can fold blocked_per_target() and
    # failures_per_target_type() into this one, but I am really tired
    # of deailing with MongoDB, so it is left as an exercise to the
    # reader.
    return db[args.collection_id]\
        .aggregate([
            {
                "$match": {
                    # match on both fields so the runid-hash index is used
                    "runid": runid_raw,
                    "hashid": { "$exists": True },
                }
            },
            {
                # We don't reduce TARGETTYPE:BSPMODEL as we need it to verify coverage
                "$project" : {
                    "used_target_types": { "$split": [ "$target_types", "," ] },
                    "used_target_servers": { "$split": [ "$target_servers", "," ] },
                    # 1 means pass these through
                    "runid": 1,
                    "result": 1,
                    "tc_name": 1,
                    # These are KPIs
                    "data": 1,
                    "data-v2": 1,	# new version incl target name
                },
            },
            {
                # All these $TOKEN are mongodb commands on how to run an
                # aggregation, when in the place of a key. When they are on a
                # value, they refer mostly to a field in the document
                "$group": {
                    # Generate a table with total/pass/errr/fail/blck/skip counts
                    # for each runid/
                    # Each one is  done by counting how many have the given result.
                    "_id": "$runid",
                    # Count all testcases we are running
                    "total": { "$sum" : 1 },
                    # collect the data in a list; it is the
                    # responsibility of the reporter to arrange
                    # domains and execution models that allow proper
                    # grouping FIXME document
                    "data": { "$push": "$data" },
                    "data-v2": { "$push": "$data-v2" },
                    # Count passing, erroring, failing, blocked and skipped
                    "pass": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "PASS" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "fail": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "FAIL" ] },
                                1,
                                0
                            ]
                        },
                    },
                    # Accumulate specific ones which failed, for failure-frequency
                    "fail_tc_names": {
                        "$push": {
                            "$cond": [
                                { "$eq": [ "$result", "FAIL" ] },
                                "$tc_name",
                                "$nop",
                            ]
                        }
                    },
                    "errr": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "ERRR" ] },
                                1,
                                0
                            ]
                        },
                    },
                    # Accumulate specific ones which errored, for error-frequency
                    "errr_tc_names": {
                        "$push": {
                            "$cond": [
                                { "$eq": [ "$result", "ERRR" ] },
                                "$tc_name",
                                "$nop",
                            ]
                        }
                    },
                    "blck": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "BLCK" ] },
                                1,
                                0
                            ]
                        },
                    },
                    "skip": {
                        "$sum": {
                            "$cond": [
                                { "$eq": [ "$result", "SKIP" ] },
                                1,
                                0
                            ]
                        },
                    },
                    # Tally which target types, servers and testcases
                    # we are using
                    "used_target_types_set": {
                        "$push": "$used_target_types",
                    },
                    "used_target_servers_set": {
                        "$push": "$used_target_servers",
                    },
                    "tc_names": {
                        "$push": "$tc_name",
                    },
                },
            },
            {
                "$project" : {
                    # Now modify each record generated in the table; generate
                    # a pass % and a blocked % and a total fields.
                    "data": 1,
                    "data-v2": 1,
                    "pass": 1,
                    "errr": 1,
                    "fail": 1,
                    "blck": 1,
                    "skip": 1,
                    "total": 1,
                    "total_ran": { "$sum": [ "$pass", "$errr", "$fail", "$blck"] },
                    # reduce -> remove dups
                    "used_target_types": {
                        "$reduce": {
                            "input": "$used_target_types_set",
                            "initialValue": [],
                            "in": {
                                "$setUnion": [ "$$value", "$$this" ]
                            },
                        },
                    },
                    "used_target_servers": {
                        "$reduce": {
                            "input": "$used_target_servers_set",
                            "initialValue": [],
                            "in": {
                                "$setUnion": [ "$$value", "$$this" ]
                            },
                        },
                    },
                    "fail_tc_names": 1,
                    "errr_tc_names": 1,
                    "tcs": {
                        "$reduce": {
                            "input": "$tc_names",
                            "initialValue": [],
                            "in": {
                                "$setUnion": [ "$$value", [ "$$this" ] ]
                            },
                        },
                    },
                },
            },
            {
                "$project": {
                    "data": 1,
                    "data-v2": 1,
                    "pass": 1,
                    "errr": 1,
                    "fail": 1,
                    "blck": 1,
                    "skip": 1,
                    "tcs": 1,
                    # Number of different test cases
                    "total_tcs": { "$size": "$tcs" },
                    "total": 1,
                    "total_ran": 1,
                    "errr_tc_names": 1,
                    "fail_tc_names": 1,
                    "pass%": {
                        "$cond": [
                            {
                                "$eq": [
                                    { "$add": [ "$pass", "$errr", "$fail" ] },
                                    0
                                ]
                            },
                            0,
                            {
                                # We decided the pass rate is
                                # PASS/(PASS+ERRR+FAIL), to avoid blockage
                                # to alter results.
                                "$divide": [
                                    "$pass",
                                    { "$add": [ "$pass", "$errr", "$fail" ] }
                                ]
                            },
                        ]
                    },
                    "blck%": {
                        "$cond": [
                            { "$eq": [ "$total_ran", 0 ] },
                            0,
                            { "$divide": [ "$blck", "$total_ran" ] },
                        ]
                    },
                    "used_target_types": 1,
                    "number_used_target_types": {
                        "$size": "$used_target_types"
                    },
                    "used_target_servers": 1,
                    "number_used_target_servers": {
                        "$size": "$used_target_servers"
                    },
                }
            },
            # FIXME: remove intermediate fields
        ], allowDiskUse = True)


def _runids_postprocess_blocked_per_target(runid_raw):
    # See _runids_postprocess_summary_per_run
    return db[args.collection_id].aggregate([
        {
            "$match": {
                # match on both fields so the runid-hash index is used
                "runid": runid_raw,
                "hashid": { "$exists": True },
            }
        },
        {
            "$match": {
                # select only blocked testcases
                #
                # separate from previous one for clarity and to make
                # sure the index runid-hash is used.
                "result": "BLCK",
            }
        },
        {
            "$project" : {
                # Only use the two fields we care for
                "runid": "$runid",
                "targets": "$targets",
            }
        },
        {
            # bucketize by runid + targets
            "$group": {
                "_id": {
                    "runid": "$runid",
                    "targets": "$targets",
                },
                "blocked": { "$sum": 1 }
            }
        },
        {
            "$group": {
                "_id": "$_id.runid",
                "targets_blocked" : {
                    "$push": {
                        "targets": "$_id.targets",
                        "blocked": "$blocked",
                    },
                },
            }
        }
    ])

def _runids_postprocess_error_per_target(runid_raw):
    # See _runids_postprocess_summary_per_run
    return db[args.collection_id].aggregate([
        {
            "$match": {
                # match on both fields so the runid-hash index is used
                "runid": runid_raw,
                "hashid": { "$exists": True },
            }
        },
        {
            # select only failed testcases
            #
            # separate from previous one for clarity and to make
            # sure the index runid-hash is used.
            "$match": {
                "result": "ERRR",
            }
        },
        {
            "$project" : {
                # Now modify each record generated in the table; generate
                # a pass % and a blocked % and a total fields.
                "runid": "$runid",
                "targets": "$targets",
            }
        },
        {
            "$group": {
                "_id": {
                    "runid": "$runid",
                    "targets": "$targets",
                },
                "errors": { "$sum": 1 }
            }
        },
        {
            "$group": {
                "_id": "$_id.runid",
                "targets_errored" : {
                    "$push": {
                        "targets": "$_id.targets",
                        "errors": "$errors",
                    },
                },
            }
        }
    ])

def _runids_postprocess_failure_per_target(runid_raw):
    # See _runids_postprocess_summary_per_run
    return db[args.collection_id].aggregate([
        {
            "$match": {
                # match on both fields so the runid-hash index is used
                "runid": runid_raw,
                "hashid": { "$exists": True },
            }
        },
        {
            # select only failed testcases
            #
            # separate from previous one for clarity and to make
            # sure the index runid-hash is used.
            "$match": {
                "result": "FAIL",
            }
        },
        {
            "$project" : {
                # Now modify each record generated in the table; generate
                # a pass % and a blocked % and a total fields.
                "runid": "$runid",
                "targets": "$targets",
            }
        },
        {
            "$group": {
                "_id": {
                    "runid": "$runid",
                    "targets": "$targets",
                },
                "failed": { "$sum": 1 }
            }
        },
        {
            "$group": {
                "_id": "$_id.runid",
                "targets_failed" : {
                    "$push": {
                        "targets": "$_id.targets",
                        "failed": "$failed",
                    },
                },
            }
        }
    ])

def _runids_postprocess_failures_per_target_type(runid_raw):
    # See _runids_postprocess_summary_per_run
    return db[args.collection_id]\
        .aggregate([
            {
                "$match": {
                    # match on both fields so the runid-hash index is used
                    "runid": runid_raw,
                    "hashid": { "$exists": True },
                }
            },
            {
                # select only failed testcases
                #
                # separate from previous one for clarity and to make
                # sure the index runid-hash is used.
                "$match": {
                    "result": "FAIL",
                }
            },
            {
                "$project" : {
                    # Now modify each record generated in the table; generate
                    # a pass % and a blocked % and a total fields.
                    "target_type": "$target_types",
                    "runid": "$runid",
                    "tc_name": "$tc_name",
                }
            },
            {
                "$group": {
                    "_id": {
                        "runid": "$runid",
                        "target_type": {
                            # The target type might be TARGETTYPE:BSP if a
                            # target has multiple BSPs, in which case, we need
                            # to split away the BSP and aggregate by the
                            # TARGETTYPE only
                            "$arrayElemAt" : [
                                { "$split" : [ "$target_type", ":" ] },
                                0
                            ]
                        },
                    },
                    "failed_tc_names": { "$addToSet": "$tc_name" },
                    "failed": { "$sum": 1 },
                }
            },
            {
                "$group": {
                    "_id": "$_id.runid",
                    "target_types" : {
                        "$push": {
                            "failed_target_type": "$_id.target_type",
                            "failed": "$failed",
                            "failed_tc_names": "$failed_tc_names"
                        },
                    },
                }
            }
        ])

def _runids_postprocess_error_per_target_type(runid_raw):
    # See _runids_postprocess_summary_per_run
    return db[args.collection_id]\
        .aggregate([
            {
                "$match": {
                    # match on both fields so the runid-hash index is used
                    "runid": runid_raw,
                    "hashid": { "$exists": True },
                }
            },
            {
                # select only failed testcases
                #
                # separate from previous one for clarity and to make
                # sure the index runid-hash is used.
                "$match": {
                    "result": "ERRR",
                }
            },
            {
                "$project" : {
                    # Now modify each record generated in the table; generate
                    # a pass % and a blocked % and a total fields.
                    "target_type": "$target_types",
                    "runid": "$runid",
                    "tc_name": "$tc_name",
                }
            },
            {
                "$group": {
                    "_id": {
                        "runid": "$runid",
                        "target_type": {
                            # The target type might be TARGETTYPE:BSP if a
                            # target has multiple BSPs, in which case, we need
                            # to split away the BSP and aggregate by the
                            # TARGETTYPE only
                            "$arrayElemAt" : [
                                { "$split" : [ "$target_type", ":" ] },
                                0
                            ]
                        },
                    },
                    "error_tc_names": { "$addToSet": "$tc_name" },
                    "error": { "$sum": 1 },
                }
            },
            {
                "$group": {
                    "_id": "$_id.runid",
                    "error_per_target_type" : {
                        "$push": {
                            "error_target_type": "$_id.target_type",
                            "error": "$error",
                            "error_tc_names": "$failed_tc_names"
                        },
                    },
                }
            }
        ])

def _summary_runids_missing():
    t.tick("caching raw RunIDs in from raw database")
    raw_runids = set(db[args.collection_id].distinct('runid'))
    t.tick("cached RunIDs in from raw database, got %d" % len(raw_runids))
    t.tick("caching RunIDs in from raw database")
    summary_raw_runids = set([
        _runid_to_raw(runid)
        for runid in summary_collection.distinct('_id') ])
    t.tick("cached RunIDs in from raw database, got %d" % len(raw_runids))
    return raw_runids - summary_raw_runids

def _summary_runids_redo():
    t.tick("caching RUNIDs in from raw database")
    raw_runids = set(db[args.collection_id].distinct('runid'))
    t.tick("cached RUNIDs in from raw database, got %d" % len(raw_runids))
    return raw_runids

def _summary_refresh_per_component(runid_raw, runid_doc):

    t.tick("%s: summarizing per component" % runid_raw)
    # This part is really hard to do as an aggregation step in the
    # database, so we break it in two parts and do aggregation and
    # back computing here
    runid_doc['components'] = dict()
    for doc in _runids_postprocess_summary_per_component(runid_raw):
        runid = doc['_id']['runid']
        component = doc['_id']['component']
        passed = int(doc.get('pass', 0))
        blocked = int(doc.get('blck', 0))
        skipped = int(doc.get('skip', 0))
        errored = int(doc.get('errr', 0))
        failed = int(doc.get('fail', 0))
        total = int(doc['total'])
        if passed + errored + failed:
            passed_percent = float(passed) / (passed + errored + failed)
        else:
            passed_percent = 1
        if total:
            blocked_percent = float(blocked) / total
        else:
            blocked_percent = 1

        runid_doc['components'][component] = {
            'pass': passed,
            'pass%': passed_percent,
            'blck': blocked,
            'blck%': blocked_percent,
            'skip': skipped,
            'fail': failed,
            'errr': errored,
            'total': total
        }
    t.tick("%s: summarized per component" % runid_raw)


def _summary_refresh_per_target_types(runid_raw, runid_doc):

    t.tick("%s: summarizing per target types" % runid_raw)
    # This part is really hard to do as an aggregation step in the
    # database, so we break it in two parts and do aggregation and
    # back computing here
    runid_doc['target_types_stats'] = dict()
    for doc in _runids_postprocess_summary_per_target_types(runid_raw):
        runid = doc['_id']['runid']
        target_types = doc['_id']['target_types']
        passed = int(doc.get('pass', 0))
        blocked = int(doc.get('blck', 0))
        skipped = int(doc.get('skip', 0))
        errored = int(doc.get('errr', 0))
        failed = int(doc.get('fail', 0))
        total = int(doc['total'])
        if passed + errored + failed:
            passed_percent = float(passed) / (passed + errored + failed)
        else:
            passed_percent = 1
        if total:
            blocked_percent = float(blocked) / total
        else:
            blocked_percent = 1

        runid_doc['target_types_stats'][target_types] = {
            'pass': passed,
            'pass%': passed_percent,
            'blck': blocked,
            'blck%': blocked_percent,
            'skip': skipped,
            'fail': failed,
            'errr': errored,
            'total': total
        }
    t.tick("%s: summarized per target types" % runid_raw)


def _summary_refresh(runid_raw):
    runid = _runid_from_raw(runid_raw)
    t.tick("%s: summarizing" % runid_raw)
    doc = None
    for doc in _runids_postprocess_summary_per_run(runid_raw):
        assert runid_raw == doc["_id"]
        if args.url:
            doc['url'] = args.url
        if args.build_no:
            doc['build_no'] = args.build_no
        if args.runid_extra:
            doc['runid_extra'] = args.runid_extra
        _summary_refresh_per_target_types(runid_raw, doc)
        _summary_refresh_per_component(runid_raw, doc)
        # This will (should) actually only run once, for this RUNID
        # there shall be a single summary record...so break
        break

    if doc == None:
        t.tick("%s: runid not found" % runid_raw)
        return
    t.tick("%s: summarizing done" % runid_raw)

    doc_data = doc['data']
    doc_data_v2 = doc['data-v2']
    del doc['data']
    if 'data_v2' in doc:
        del doc['data_v2']
    del doc['_id']
    _doc = dict(doc)
    doc = None
    # cleanup the document a wee bit, removing empty stuff
    _doc['data'] = [ i for i in doc_data if i ]
    _doc['data-v2'] = [ i for i in doc_data_v2 if i ]

    for doc in _runids_postprocess_blocked_per_target(runid_raw):
        doc.pop("_id")
        _doc.update(doc)
    t.tick("%s: blocked per target" % runid_raw)

    for doc in _runids_postprocess_failure_per_target(runid_raw):
        doc.pop("_id")
        _doc.update(doc)
    t.tick("%s: failed per target" % runid_raw)

    for doc in _runids_postprocess_error_per_target(runid_raw):
        doc.pop("_id")
        _doc.update(doc)
    t.tick("%s: error per target" % runid_raw)

    for doc in _runids_postprocess_error_per_target_type(runid_raw):
        doc.pop("_id")
        _doc.update(doc)
    t.tick("%s: error per target type" % runid_raw)

    for doc in _runids_postprocess_failures_per_target_type(runid_raw):
        doc.pop("_id")
        _doc.update(doc)
    t.tick("%s: failures per target type" % runid_raw)

    summary_collection.update_one(
        { '_id': runid }, { "$set": _doc }, upsert = True)


def __sheet_update_temp_matrix(runid, records, name, label_name,
                              create = True, order = None):
    # Adds to an existing or new temperature matrix
    #
    # COLUMNAME   NOTE   RUNIDN   RUNIDN-1   RUNIDN-2 ... RUNID0
    # NAME0       NOTE0  VALUEN_0 VALUEN-1_0 ...
    # NAME1       NOTE1  VALUEN_1 VALUEN-2_0 ..
    #
    # Adds RUNID to the left of the existing matrix, maintaining the
    # notes and rearranging if new NAMEs come in or old go away
    #
    # If VALUE is none, plot nothing, VALUE are otherwise integers
    # that are colored from yellow to red as the value increases.

    assert isinstance(runid, str)
    assert isinstance(records, dict)
    assert all(i == None or isinstance(i, (int, str)) for i in records.values())
    assert isinstance(name, str)
    assert isinstance(label_name, str)
    assert order == None or order >= 0

    label_names = set(records.keys())
    ffsh = googlel.spreadsheet(args.s, args.spreadsheet_id, name,
                               create = create)
    ff_notes = collections.defaultdict(str)
    ff_values = collections.defaultdict(list)
    runids = [ runid ]
    t.tick("%s: sheet/%s updating" % (runid, name))
    if not ffsh.created:
        columns_ab = ffsh.number_to_letters(ffsh.sheet_get_column_count())
        # Get actual notes so we can preserve them
        @googlel.retry_google_operation
        def _get():
            result = ffsh.service.spreadsheets().values().get(
                spreadsheetId = ffsh.spid,
                # This ensures that we get the full value for
                # cells with hyperlinks, not just the *value*
                valueRenderOption = 'FORMULA',
                range = "%s!A1:%s" % (ffsh.sheet_name, columns_ab)).execute()
            return result
        r = _get()
        for row in ffsh.result_get_values(r, 'values', []):
            if not row:
                logging.warning(f"{runid}/{name}: skipping empty 'values' row")
                continue
            if row[0] == label_name:	# header
                runids += row[2:]
                continue
            if len(row) > 1:
                tc_name = row[0]
                # So a row has [0] tc name, [1] notes, [2:] data for
                # each runid; let's save them so they can be written back.
                if len(row) > 0:
                    ff_notes[tc_name] = row[1]
                if len(row) > 1:
                    values = row[2:]
                else:
                    values = []
                # if this testcase exists in our list of testcases with
                # data for this runid, insert said value, otherwise an
                # empty cell (None)
                if tc_name in records.keys():
                    new_value = records[tc_name]
                    # If repeated, too bad -- don't do that
                    if tc_name in label_names:
                        label_names.remove(tc_name)
                else:
                    new_value = None
                ff_values[tc_name] = [ new_value ] + values

    # Now go over the new ones, left over tc_names
    for _label_name in label_names:
        ff_values[_label_name] = [ records[_label_name] ]

    # Reformat in alphabetical order, remove those with no values
    if len(runids) > args.max_runids_horizontal:
        runids = runids[:args.max_runids_horizontal]
    header = [ label_name, "Notes"] + runids
    ff_rows = [ ]
    for tc_name in sorted(ff_values.keys()):
        notes = ff_notes.get(tc_name, None)
        values = ff_values[tc_name]
        if len(values) > args.max_runids_horizontal:
            values = values[:args.max_runids_horizontal]
        if any(value != None for value in values):
            ff_rows.append([ tc_name, notes ] + values)

    ffsh.sheet_format_clear()
    ffsh.flush()
    ffsh.feed_rows([ header ] + ff_rows)
    ffsh.flush()
    # Cap to maximum sizes we have enforced before
    ffsh.sheet_size_set(1 + len(ff_rows), 2 + len(runids))
    ffsh.flush()

    # Fix formatting for runids on row 0
    if runids:
        ffsh.cell_format('textRotation', { 'angle': 90 },
                         0, 2, 1, 2 + len(runids))
        ffsh.flush()
    if ff_rows:
        ffsh.cell_format('horizontalAlignment', 'CENTER',
                         0, 1, len(ff_rows), 1 + len(runids))
        ffsh.flush()

    # color code the value cells based on value
    row = 1	# Don't format the header
    for ff_row in ff_rows:
        column = 0
        for ff_cell in ff_row:
            if column <= 1:	# exclude the header and issue link
                column += 1
                continue
            if ff_cell:
                # If it fails, it's a bug -- let it fail
                try:
                    val = int(ff_cell)
                except ValueError:	# not an integer
                    val = ff_cell

                # let's do some coloring based on the content
                color = None
                if isinstance(val, int):
                    # Integer, heat map -- based on counts
                    if val <= 1:
                        color = dict(red = 1.0, blue = 0.0, green = 0.9)
                    elif val <= 4:
                        color = dict(red = 1.0, blue = 0.0, green = 0.6)
                    elif val <= 10:
                        color = dict(red = 1.0, blue = 0.0, green = 0.3)
                    else:
                        color = dict(red = 1.0, blue = 0.0, green = 0.0)
                elif isinstance(val, str):
                    # Text, hardcoded for results PASS, FAIL, ERR...
                    if val.startswith("=HYPERLINK"):
                        # if this is a hyperlink, might look like:
                        #
                        ## =HYPERLINK("https://plen-ci.ostc.intel.com/job/capi-healthcheck-ci-master//12/artifact/report-ci-201009-0008-12%3avf3qun.txt","P")
                        #
                        # Let's take out the value (second argument)
                        #
                        # we can't assume much about the URL and such,
                        # but we know it has no quotes or commas, so
                        # let's use those to pivot:
                        l = val.split(",", 1)

                        # now the second part is
                        #
                        ## "P")
                        val = l[1]

                        # let's remove from the first double quote to
                        # the last; might be an integer and have no
                        # quotes
                        if val.startswith('"'):
                            val = val[1:]
                        if val.endswith(')'):
                            val = val[:-1]
                        if val.endswith('"'):
                            val = val[:-1]
                    # assume is a string, color code
                    if val == "PASS" or val == "P":    # green
                        color = dict(red = 0.1, blue = 0.0, green = 0.9)
                    elif val == "FAIL" or val == "F":  # red
                        color = dict(red = 1.0, blue = 0.0, green = 0.0)
                    elif val == "ERRR" or val == "E":  # purplish
                        color = dict(red = 1.0, blue = 0.8, green = 0.0)
                    elif val == "BLCK" or val == "B":  # yellow
                        color = dict(red = 1.0, blue = 0.0, green = 0.9)
                    elif val == "SKIP" or val == "S":  # dark orange
                        color = dict(red = 0.8, blue = 0.0, green = 0.6)
                if color:
                    ffsh.cell_format('backgroundColor', color,
                                     row, column, row + 1, column + 1)
            column += 1
        row += 1
    ffsh.flush()

    if order:
        ffsh.sheet_order_update(order)
    t.tick("%s: sheet/%s updated" % (runid, name))


def _sheet_update_temp_matrix(runid, records, name, label_name,
                              create = True, order = None):
    try:
        __sheet_update_temp_matrix(runid, records, name, label_name,
                                   create = create, order = order)
    except googleapiclient.errors.Error as e:
        # we don't want to hard fail because of size limitations and
        # loose info
        logging.error(f"{runid}: can't update {name}: {e}")


def sheet_update_key_value(runid, records, name, create = True,
                           allow_duplicate_keys = False):
    """
    Given a runid and a set of records for that runid, create/update a
    worksheet where the rows are keyed by runid and the columns are
    updated to each of the keys in records (alphabetically).

    If there are existing records, columns will be inserted if new
    keys are added.

    :returns: True if the sheet is present, False if we didn't have to
      update it
    """
    # Now unfold the FPBT dictionary into a table runid/target-types
    sh = googlel.spreadsheet(args.s, args.spreadsheet_id, name, create = create)
    if not create and not sh._shid:
        logging.warning("%s: not creating worksheet '%s'; create manually "
                        "if update needed", runid, name)
        return False

    logging.warning("%s: sheet/%s: updating", runid, name)

    def _create():
        keys = sorted(records.keys())
        header = [ 'RunID' ] + keys
        sh.sheet_size_set(1, 1 + len(keys))
        sh.feed_rows([ header ])
        sh.spreadsheet_requests_flush()
        return keys

    if sh.created:
        keys = _create()
    else:
        # First read the existing sheet, because we'll need to get the
        # existing keys to format the ones we have likewise.
        # (if row 1 has keys K1 K4 K6 in COLUMNS B C D and we are
        # adding new records with K2 K3, we want to rearrang to K1 K2
        # K3 K4 K6)
        columns_ab = sh.number_to_letters(sh.sheet_get_column_count())
        @googlel.retry_google_operation
        def _get():
            return sh.service.spreadsheets().values().get(
                spreadsheetId = sh.spid,
                range = "%s!A1:%s1" % (sh.sheet_name, columns_ab)).execute()
        r = _get()
        header_row = sh.result_get_values(r, 'values', [])
        if not header_row:
            keys = _create()
        else:
            existing_keys = set(header_row[0][1:])
            new_keys = set(records.keys()) - existing_keys

            _existing_keys = sorted(existing_keys)

            for new_key in sorted(new_keys):
                position = bisect.bisect(_existing_keys, new_key)
                _existing_keys.insert(position, new_key)
                sh.columns_insert(position + 1, 1)
                sh.feed_rows([ [ new_key ] ], fromrow = 0, fromcol =
                             position + 1, torow = 1, tocol = position + 2)
                # FIXME: write the column name
            keys = _existing_keys
    row = [ runid ]
    for key in keys:	# the order is important
        row.append(records.get(key, None))
    sh.rows_insert(1, 1)
    sh.feed_rows([ row ], fromrow = 1, clear_values = False)
    # Now cap for size -- if at the time we read the sheet it was
    # already at capacity, we have added to it, so cap it
    if sh.sheet_get_row_count() >= args.max_runids:
        sh.sheet_size_set(args.max_runids, sh.sheet_get_column_count())
    t.tick("%s: sheet/%s updated" % (runid, name))
    return True

def sheet_update_per_component(runid, doc_runid):
    all_records = collections.defaultdict(None)
    ppc_records = collections.defaultdict(None)
    fpc_records = collections.defaultdict(None)
    epc_records = collections.defaultdict(None)
    bpc_records = collections.defaultdict(None)

    summary_per_component = doc_runid.get('components', {})
    runid_pass = doc_runid.get('pass', 0)
    runid_fail = doc_runid.get('fail', 0)
    runid_errr = doc_runid.get('errr', 0)
    runid_block = doc_runid.get('blck', 0)

    update = True
    for component, component_data in summary_per_component.items():
        _pass = component_data.get('pass', None)
        passp = component_data.get('pass%', None)
        block = component_data.get('blck', None)
        blockp = component_data.get('blck%', None)
        skip = component_data.get('skip', None)
        errr = component_data.get('errr', None)
        fail = component_data.get('fail', None)
        total = component_data.get('total', None)
        all_records = {
            'Blocked%': blockp,
            'Blocked': block,
            'Component': component,
            'Errored': errr,
            'Failed': fail,
            'Passed%': passp,
            'Passed': _pass,
            'Skipped': skip,
            'Total': total,
        }
        # This we have to call it per-component, as we are going to
        # introduce a row for each; if first time we call we are told
        # we don't have to update, don't do it again.
        if update:
            update = sheet_update_key_value(runid, all_records,
                                            "_All components", create = False,
                                            allow_duplicate_keys = True)
        # If the cell is going to be 0, we want a None, so we
        # don't draw anything there
        if not passp or not runid_pass or not _pass:
            ppc_records[component] = None
        else:
            ppc_records[component] = _pass

        if not fail or not runid_fail:
            fpc_records[component] = None
        else:
            fpc_records[component] = fail

        if not errr or not runid_errr:
            epc_records[component] = None
        else:
            epc_records[component] = errr

        if not block or not runid_block:
            bpc_records[component] = None
        else:
            bpc_records[component] = block

    sheet_update_key_value(runid, ppc_records, "_Pass per component",
                           create = False)
    sheet_update_key_value(runid, fpc_records, "_Fail per component",
                           create = True)
    sheet_update_key_value(runid, epc_records, "_Error per component",
                           create = True)
    sheet_update_key_value(runid, bpc_records, "_Block per component",
                           create = False)

# Adding the code to get the stats for each board type
def sheet_update_per_board_types(runid, doc_runid):
    all_records = collections.defaultdict(None)
    ppc_records = collections.defaultdict(None)
    fpc_records = collections.defaultdict(None)
    epc_records = collections.defaultdict(None)
    bpc_records = collections.defaultdict(None)

    summary_per_board_types = doc_runid.get('target_types_stats', {})
    runid_pass = doc_runid.get('pass', 0)
    runid_fail = doc_runid.get('fail', 0)
    runid_errr = doc_runid.get('errr', 0)
    runid_block = doc_runid.get('blck', 0)

    update = True
    for board_types, board_types_data in summary_per_board_types.items():
        _pass = board_types_data.get('pass', None)
        passp = board_types_data.get('pass%', None)
        block = board_types_data.get('blck', None)
        blockp = board_types_data.get('blck%', None)
        skip = board_types_data.get('skip', None)
        errr = board_types_data.get('errr', None)
        fail = board_types_data.get('fail', None)
        total = board_types_data.get('total', None)
        all_records = {
            'Blocked%': blockp,
            'Blocked': block,
            'board_types': board_types,
            'Errored': errr,
            'Failed': fail,
            'Passed%': passp,
            'Passed': _pass,
            'Skipped': skip,
            'Total': total,
        }
        # This we have to call it per-target_type, as we are going to
        # introduce a row for each; if first time we call we are told
        # we don't have to update, don't do it again.
        if update:
            update = sheet_update_key_value(runid, all_records,
            "Summary per boardtype", create = False, allow_duplicate_keys = True)
        # If the cell is going to be 0, we want a None, so we
        # don't draw anything there
        if not passp or not runid_pass or not _pass:
            ppc_records[board_types] = None
        else:
            ppc_records[board_types] = _pass

        if not fail or not runid_fail:
            fpc_records[board_types] = None
        else:
            fpc_records[board_types] = fail

        if not errr or not runid_errr:
            epc_records[board_types] = None
        else:
            epc_records[board_types] = errr

        if not block or not runid_block:
            bpc_records[board_types] = None
        else:
            bpc_records[board_types] = block

    sheet_update_key_value(runid, ppc_records, "_Pass per board_types",
                           create = False)
    sheet_update_key_value(runid, fpc_records, "_Fail per board_types",
                           create = True)
    sheet_update_key_value(runid, epc_records, "_Error per board_types",
                           create = True)
    sheet_update_key_value(runid, bpc_records, "_Block per board_types",
                           create = False)


def _sheet_update_tcs(runid_raw, runid, summary_doc, conditions, name,
                      create = False, order = None):
    # Create a worksheet that lists testcases based that resulted in
    # any of the @conditions
    #
    # These we take from the raw database and postprocess in place,
    # sorted by result and with a hyperlink to the result as per the
    # URL/buildno fed into the summary
    #
    # param str runid_raw: runid as consigned in the database
    # param str runid: runid as reported in the summary the database
    assert isinstance(runid, str)
    assert isinstance(conditions, list)
    assert isinstance(name, str)

    sh = googlel.spreadsheet(args.s, args.spreadsheet_id,
                            name, create = create)
    if sh._shid == None:
        logging.warning("%s/%s: not updating worksheet "
                        "that has to be explictly created (save space)",
                        runid, name)
        return

    def _iterate(runid, conditions):
        # conditions = [ "PASS", "FAIL" ... ] etc
        return db[args.collection_id]\
            .find(
                {
                    'runid': runid_raw,
                    'hashid': { '$exists': True },
                    'result': { '$in': conditions },
                },
                projection = [
                    "hashid",
                    "result",
                    "runid",
                    "targets",
                    "tc_name",
                ])\
            .hint('runid-hash').limit(0)

    # This list we'll keep it sorted by Result and Testcase Name
    header = [
        "Run ID",
        "Hash ID",
        "Result",
        "Testcase Name",
        "Notes",
        "Target Types",
        "Target Names",
        "Target Servers",
    ]
    rows = [ ]

    _conditions = ",".join(conditions)
    logging.warning("%s/%s: iterating for %s", runid, name, _conditions)

    url = summary_doc.get('url', "https://DOC-MISSING/")
    build_no = summary_doc.get('build_no', "NOTAVAILABLE")
    try:	# the RUNID's last -XYZ is always the Jenkins build_number
        build_no = runid_raw.split("-")[-1]	# FIXME: Hack I don't like...
    except IndexError:
        logging.warning("%s: can't extract build number" % runid_raw)

    # Load the records we care for and create those rows
    count = -1
    for doc in _iterate(runid, conditions):
        target_types = []
        target_servers = []
        target_names = []
        for target_want_name in sorted(doc.get('targets', {})):
            target = doc['targets'][target_want_name]
            if 'type' in target:
                target_type = target['type']
                if 'bsp_model' in target and target['bsp_model']:
                    target_type += ":" + target['bsp_model']
                target_types.append(target_type)
            if 'server' in target:
                target_servers.append(target['server'])
            if 'id' in target:
                target_names.append(target['server'] + "/" + target['id'])

        runid_separator = urllib.parse.quote(args.runid_separator)
        row = [
            runid,
            doc['hashid'],
            '=HYPERLINK("%(url)s/%(build_no)s/artifact/report-%(runid_raw)s%(runid_separator)s%(hashid)s.txt","%(result)s")'
            % dict(url = url, runid_raw = runid_raw,
                   runid_separator = runid_separator, build_no = build_no,
                   hashid = doc['hashid'], result = doc["result"]),
            doc["tc_name"],
            "Notes",		# insert a Notes column for us to write stuff
            ",".join(target_types) if target_types else "static",
            ",".join(target_names) if target_names else "static",
            ",".join(target_servers) if target_servers else None,
            doc["result"],	# Keep this for sorting, we'll remove later
        ]
        rows.append(row)

    if not rows:
        logging.warning("%s/%s: iterated for %s; nothing, thus skipping",
                        runid, name, _conditions)
        return
    logging.warning("%s/%s: iterated for %s; sorting",
                    runid, name, _conditions)
    # Note we sort by x[-1], the last field (we added it above) why?
    # Because we want to sort fields by result, but our result field
    # in [2] has a URL and then it does not sort. We then sort by
    # target names and then by testcase, so all the results for the
    # same machine/s group together
    rows.sort(key = lambda x: (x[-1], x[5], x[3]), reverse = True)
    for row in rows:
        row.pop()	# remove last row, just for sorting
    logging.warning("%s/%s: sorted for %s", runid, name, _conditions)

    if sh.created:
        sh.feed_rows([ header ])
        sh.sheet_size_set(1, len(header))
        sh_row_count = 1
    else:
        sh_row_count = sh.sheet_get_row_count()

    # if we will more new rows than we admit, chop that, this makes
    # the rest of the computation easier
    rows_len_orig = len(rows)
    if len(rows) > args.max_rows_np:
        new_rows = args.max_rows_np
        logging.warning("%s/%s: capped rows to feed to %d (from %d) "
                        "to keep under %d limit",
                        runid, name, new_rows, rows_len_orig,
                        args.max_rows_np)
        rows = rows[:new_rows]
    else:
        new_rows = len(rows)
    # now if we insert over the existing rows and we'll go over the
    # limit, chop the existing rows
    sh_row_count_new = sh_row_count + new_rows
    # -1 for the header
    if sh_row_count_new > args.max_rows_np - 1:
        chop_rows = sh_row_count_new - args.max_rows_np - 1
        chop_to_rows = sh_row_count - chop_rows
        logging.warning("%s/%s: pre-chopping to %d rows (from %d) to "
                        "make space for %d/%d new rows",
                        runid, name, chop_to_rows, sh_row_count,
                        new_rows, rows_len_orig)
        sh.sheet_size_set(chop_to_rows, len(header))
        sh_row_count -= chop_rows
        logging.warning("%s/%s: chopped to %d rows",
                        runid, name, sh_row_count)

    # Don't insert more rows that the max we allow

    sh.rows_insert(1, new_rows)
    sh.feed_rows(rows, fromrow = 1, clear_values = False)
    sh.flush()

    # Now we have to format colors
    row_cnt = 1	# Don't format the header
    for row in rows:
        result = row[2]
        # uses X in result, as result will be
        # =HYPERLINK("https://URL-MISSING//1786/artifact/report-ci-180614-0937-1786%3agzze.txt","ERRR")
        if result == None:
            color = dict(red = 1.0, green = 1.0, blue = 0.0)
        elif '"FAIL"' in result:
            color = dict(red = 1.0, green = 0.0, blue = 0.0)
        elif '"ERRR"' in result:
            color = dict(red = 0.75, green = 0.57, blue = 0.69)
        elif '"BLCK"' in result:
            color = dict(red = 1.0, green = 1.0, blue = 0.0)
        elif '"SKIP"'  in result:
            color = dict(red = 1.0, green = 0.7, blue = 0.0)
        else:
            color = None
        if color:
            sh.cell_format('backgroundColor', color,
                           row_cnt, 2, row_cnt + 1, 3)
        else:
            logging.error("%s: row #%d: unknown result %s",
                          name, row_cnt, result)
        row_cnt += 1
    sh.flush()
    if order:
        sh.sheet_order_update(order)


def _sheet_update_tcs_matrix(
        runid_raw, runid, summary_doc, conditions, name,
        create = False, tcs_include_target = False):
    # Create a worksheet that lists testcases based that resulted in
    # any of the @conditions
    #
    # These we take from the raw database and postprocess in place,
    # sorted by result and with a hyperlink to the result as per the
    # URL/buildno fed into the summary
    #
    # param str runid_raw: runid as consigned in the database
    # param str runid: runid as reported in the summary the database
    assert isinstance(runid, str)
    assert isinstance(conditions, list)
    assert isinstance(name, str)

    sh = googlel.spreadsheet(args.s, args.spreadsheet_id,
                             name, create = create)
    if sh._shid == None:
        logging.warning("%s/%s: not updating worksheet "
                        "that has to be explictly created (save space)",
                        runid, name)
        return

    def _iterate(runid, conditions):
        # conditions = [ "PASS", "FAIL" ... ] etc
        return db[args.collection_id]\
            .find(
                {
                    'runid': runid_raw,
                    'hashid': { '$exists': True },
                    'result': { '$in': conditions },
                },
                projection = [
                    "hashid",
                    "result",
                    "runid",
                    "targets",
                    "tc_name",
                ])\
            .hint('runid-hash').limit(0)

    _conditions = ",".join(conditions)
    logging.warning("%s/%s: iterating for %s", runid, name, _conditions)

    # FIXME: this thing to get the build artifact URL shall be refactored
    url = summary_doc.get('url', "https://DOC-MISSING/")
    build_no = summary_doc.get('build_no', "NOTAVAILABLE")
    try:	# the RUNID's last -XYZ is always the Jenkins build_number
        build_no = runid_raw.split("-")[-1]	# FIXME: Hack I don't like...
    except IndexError:
        logging.warning("%s: can't extract build number" % runid_raw)

    # Load the records we care for and create those rows
    records = {}
    for doc in _iterate(runid, conditions):
        target_types = []
        target_servers = []
        target_names = []
        for target_want_name in sorted(doc.get('targets', {})):
            target = doc['targets'][target_want_name]
            if 'type' in target:
                target_type = target['type']
                if 'bsp_model' in target and target['bsp_model']:
                    target_type += ":" + target['bsp_model']
                target_types.append(target_type)
            if 'server' in target:
                target_servers.append(target['server'])
            if 'id' in target:
                target_names.append(target['server'] + "/" + target['id'])
        val = doc["result"]
        if val == "PASS":
            val = "P"
        elif val == "FAIL":
            val = "F"
        elif val == "ERRR":
            val = "E"
        elif val == "BLCK":
            val = "B"
        elif val == "SKIP":
            val = "S"
        if tcs_include_target:
            # FIXME: move this to SERVER/ID+ID+ID
            row_header = "+".join(target_names) + " " + doc['tc_name']
        else:
            row_header = doc['tc_name']
        runid_separator = urllib.parse.quote(args.runid_separator)
        records[row_header] = \
            '=HYPERLINK("%(url)s/%(build_no)s/artifact/report-%(runid_raw)s%(runid_separator)s%(hashid)s.txt","%(result)s")' \
            % dict(
                url = url,
                runid_raw = runid_raw, runid_separator = runid_separator,
                build_no = build_no, hashid = doc['hashid'], result = val
            )

    if not records:
        logging.warning("%s/%s: iterated for %s; nothing, thus skipping",
                        runid, name, _conditions)
        return

    # now draw it
    _sheet_update_temp_matrix(runid, records, name, "target / testcase",
                              create = False, order = None)


def sheet_update(runid_raw):
    runid, runid_raw = _runid_settle(runid_raw)
    # Update the google sheet with all the info from the sumary sheet;
    # we just load it in one go and update everything
    #
    # FIXME:
    #  - find the last ID we have in the google sheet and use that
    #    as a reference?
    #  - update existing entries


    # Errors / Failure per board type
    fpbt_records = collections.defaultdict(int)
    epbt_records = collections.defaultdict(int)
    # Blockage per target
    bpt_records = collections.defaultdict(int)
    # Failure / Error per target
    fpt_records = collections.defaultdict(int)
    ept_records = collections.defaultdict(int)
    # Failure / Error Frequency
    ff_tc_names = set()
    ff_records = collections.defaultdict(int)
    ef_tc_names = set()
    ef_records = collections.defaultdict(int)

    t.tick("sheet/summary: collecting data")
    # First collect a lot of stuff from the summary collection and
    # split it in different records we'll use to create tables later
    # on
    doc = summary_collection.find_one({ '_id': runid })
    if doc == None:
        logging.error("%s: runid not found", runid)
        return
    t.tick("sheet/summary: collected data")

    # the pretty runid is what we display to the user, which might
    # carry extra info, like a version or something.
    runid_pretty = runid + doc.get('runid_extra', args.runid_extra)

    spr_record = {
	"Skipped": doc.get('skip', 0),
        # This was introduced later, so older entries don't have it
	"Errored": doc.get('errr', 0),
	"Failed": doc.get('fail', 0),
	"Blocked": doc.get('blck', 0),
	"Passed": doc.get('pass', 0),
        'Blocked%': doc.get('blck%', 0),
	'Passed%': doc.get('pass%', 0),
        'Number of used target servers': doc.get('number_used_target_servers', 0),
        'Number of used target types': doc.get('number_used_target_types', 0),
        'Total Testcases Found': doc.get('total_tcs', 0),
        'Total Testcases Scheduled': doc.get('total', 0),
        'Total Testcases Ran': doc.get('total_ran', 0),
    }
    sheet_update_key_value(runid_pretty, spr_record, "_Summary per run")

    exec_record = {
        # this also in the summary, but we are moving it here
        'Number of used target servers': doc.get('number_used_target_servers', 0),
        'Number of used target types': doc.get('number_used_target_types', 0),
    }
    if 'runtime_hrs' in doc:
        runtime_hrs = doc['runtime_hrs']
        for field in runtime_hrs:
            exec_record['Runtime for %s (hrs)' % field] = \
                float(runtime_hrs[field])
    sheet_update_key_value(runid_pretty, exec_record, "_Execution stats")

    # Collect the failures per target type into a dictionary that
    # then we will unfold later into a table -- note that if there
    # are no failures, this won't be there
    for tt_doc in doc.get('target_types', []):
        if 'target_type' in tt_doc:		# old schema
            failed_tt = tt_doc['target_type']	# newer schema
        elif 'failed_target_type' in tt_doc:
            failed_tt = tt_doc['failed_target_type']
        else:
            failed_tt = [ ]
        if failed_tt:
            failed_count = tt_doc['failed']
            # If a TC was multiple target types, split the failures equally
            ttl = failed_tt.split(',')
            failed = failed_count / len(ttl)
            for tt in ttl:
                if tt == 'tt_power':
                    continue
                fpbt_records[tt] += failed
    sheet_update_key_value(runid_pretty, fpbt_records, "_Failures per board type")

    for tt_doc in doc.get('error_per_target_type', []):
        if 'error_target_type' in tt_doc:
            error_tt = tt_doc['error_target_type']
        else:
            error_tt = [ ]
        if error_tt:
            error_count = tt_doc['error']
            # If a TC was multiple target types, split the errors equally
            ttl = error_tt.split(',')
            error = error_count / len(ttl)
            for tt in ttl:
                if tt == 'tt_power':
                    continue
                epbt_records[tt] += error
    sheet_update_key_value(runid_pretty, epbt_records, "_Errors per board type")

    # Process blockage-per-target
    for entry in doc.get('targets_blocked', []):
        blockage = entry['blocked']
        for _target_want_name, target in entry.get('targets', {}).items():
            if 'server' in target:
                target_name = target['server'] + "/" + target['id']
            else:
                target_name = 'static'
            bpt_records[target_name] += blockage
    _sheet_update_temp_matrix(runid_pretty, bpt_records, "Blockage per target",
                              "Target")

    # Process failure-per-target
    for entry in doc.get('targets_failed', []):
        failures = entry['failed']
        for target_want_name, target \
                         in entry.get('targets', {}).items():
            if 'server' in target:
                target_name = target['server'] + "/" + target['id']
            else:
                target_name = 'static'
            fpt_records[target_name] += failures
    _sheet_update_temp_matrix(runid_pretty, fpt_records, "Failure per target",
                              "Target")

    # Process errors-per-target
    for entry in doc.get('targets_errored', []):
        failures = entry['errors']
        for target_want_name, target \
                         in entry.get('targets', {}).items():
            if 'server' in target:
                target_name = target['server'] + "/" + target['id']
            else:
                target_name = 'static'
            ept_records[target_name] += failures
    _sheet_update_temp_matrix(runid_pretty, ept_records, "Error per target",
                              "Target")

    # Process Failure Freuency records tc_name / number of
    # failures
    # Each summary entry has a list of the TCs that failed, with
    # multiple entries if it failed multiple times on different
    # targets
    for tc_name in doc.get('fail_tc_names', []):
        ff_tc_names.add(tc_name)
        ff_records[tc_name] += 1
    _sheet_update_temp_matrix(runid_pretty, ff_records, "Failure frequency",
                              "Testcase")

    for tc_name in doc.get('errr_tc_names', []):
        ef_tc_names.add(tc_name)
        ef_records[tc_name] += 1
    _sheet_update_temp_matrix(runid_pretty, ef_records, "Error frequency",
                              "Testcase")	  
    # Update the percomponent charts
    sheet_update_per_component(runid_pretty, doc)
    # Update the pertargettype charts
    sheet_update_per_board_types(runid_pretty,doc)
    # update the non-passing-testcases and skipped-testcases
    _sheet_update_tcs(runid_raw, runid_pretty, doc, [ "FAIL", "ERRR", "BLCK" ],
                      "Non passing testcases", create = False)
    _sheet_update_tcs(runid_raw, runid_pretty, doc, [ "SKIP" ],
                      "Skipped testcases", create = False)

    # History of every single testcase / target in a simplified
    # temperature map--note this guy is heavy weight, use only when
    # the permutations of TCs+TARGETS is limited -- if you try to pull
    # about thousands of rows, it is likely to croak
    _sheet_update_tcs_matrix(runid_raw, runid_pretty, doc,
                             # IPG: disable PASS testcases because we
                             # are bursting the spreadsheet limits
                             #[ "PASS", "FAIL", "ERRR", "BLCK", "SKIP" ],
                             [ "FAIL", "ERRR", "BLCK", "SKIP" ],
                             "History (by target and testcase)",
                             create = False, tcs_include_target = True)
    _sheet_update_tcs_matrix(runid_raw, runid_pretty, doc,
                             # IPG: disable PASS testcases because we
                             # are bursting the spreadsheet limits
                             #[ "PASS", "FAIL", "ERRR", "BLCK", "SKIP" ],
                             [ "PASS", "FAIL", "ERRR", "BLCK", "SKIP" ],
                             "History",
                             create = False,
                             tcs_include_target = False)

    # For each KPI we support, it is in a record in the ist
    # doc['data'], which means there can be repeats, which for now we
    # override.
    #
    # [
    #   { DOMAINNAME1: { KEY: VALUE, KEY: VALUE ... } },
    #   { DOMAINNAME2: { KEY: VALUE, KEY: VALUE ... } },
    # ]
    #
    # We are assuming each target of a single type is printing to a
    # different domain, to avoid the overwrite.

    # We might translate the domains using this table:
    kpi_xlat_table = [
        # Old, converge to PnP sheet
        # AES128 ENCRYPT
        (
            re.compile("PnP \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Time taken for aes128 encrypt \(nsec\)"),
            "PnP (%(zephyr_board)s)",
            "AES128 encrypt time (nsec)"
        ),
        (
            re.compile("Footprint AES128 ENCRYPT \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Fixed_RAM_size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "AES128 encrypt RAM size (bytes)"
        ),
        (
            re.compile("Footprint AES128 ENCRYPT \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Fixed_ROM_size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "AES128 encrypt ROM size (bytes)"
        ),
        # _AES128_DECRYPT
        (
            re.compile("PnP \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Time taken for aes128 decrypt \(nsec\)"),
            "PnP (%(zephyr_board)s)",
            "AES128 decrypt time (nsec)"
        ),
        (
            re.compile("Footprint_AES128_DECRYPT \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Fixed_RAM_size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "AES128 decrypt RAM size (bytes)"
        ),
        (
            re.compile("Footprint_AES128_DECRYPT \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Fixed_ROM_size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "AES128 decrypt ROM size (bytes)"
        ),
        # SHA_HMAC
        (
            re.compile("Footprint_SHA_HMAC \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Fixed_RAM_size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "SHA-HMAC RAM size (bytes)"
        ),
        (
            re.compile("Footprint_SHA_HMAC \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Fixed_ROM_size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "SHA-HMAC ROM size (bytes)"
        ),
        # SHA256
        (
            re.compile("Footprint_SHA256 \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Fixed_RAM_size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "SHA256 RAM size (bytes)"
        ),
        (
            re.compile("PnP \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Footprint sha256 RAM size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "SHA256 RAM size (bytes)"
        ),
        (
            re.compile("Footprint_SHA256 \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Fixed_ROM_size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "SHA256 ROM size (bytes)"
        ),
        (
            re.compile("PnP \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Footprint sha256 ROM size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "SHA256 RAM size (bytes)"
        ),
        (
            re.compile("PnP \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Time taken for sha256 \(nsec\)"),
            "PnP (%(zephyr_board)s)",
            "SHA256 time (nsec)"
        ),
        # Fix missing decrypt on aes128
        (
            re.compile("PnP \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Footprint aes128 ROM size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "AES128 decrypt ROM size (bytes)"
        ),
        (
            re.compile("PnP \((?P<zephyr_board>[^)]+)\)"),
            re.compile("Footprint aes128 RAM size \(bytes\)"),
            "PnP (%(zephyr_board)s)",
            "AES128 decrypt RAM size (bytes)"
        ),

    ]

    # Go over the whole list of data in the array and translate the
    # domain/key as needed, then update those in the worksheet
    data_xlat = collections.defaultdict(dict)
    for datad in doc.get('data', []):
        for domain, values in datad.items():
            for key, value in values.items():
                for domain_regex, key_regex, new_domain, new_key in kpi_xlat_table:
                    m_domain = domain_regex.match(domain)
                    m_key = key_regex.match(key)
                    if not m_domain or not m_key:
                        continue
                    _domain = new_domain % m_domain.groupdict()
                    _key = new_key % m_key.groupdict()
                else:
                    _domain = domain
                    _key = key
                data_xlat[_domain][_key] = value

    # New version f data in database (field data-v2), includes target
    # names in columns so we do not lose data.
    #
    # Go over the whole list of data in the array and translate the
    # domain/key as needed, then update those in the worksheet
    for datad in doc.get('data-v2', []):
        # DOMAIN {
        #    NAME {
        #      TARGETID2: VALUE
        #      TARGETID3: VALUE
        #    }
        #    NAME2 {
        #      TARGETID1: VALUE
        #      TARGETID4: VALUE
        #    }
        # }
        for domain, values in datad.items():
            for key, value_data in values.items():
                for target_fullid, value in value_data.items():
                    for domain_regex, key_regex, new_domain, new_key in kpi_xlat_table:
                        m_domain = domain_regex.match(domain)
                        m_key = key_regex.match(key)
                        if not m_domain or not m_key:
                            continue
                        _domain = new_domain % m_domain.groupdict()
                    else:
                        _domain = domain
                        _key = key
                    if target_fullid and target_fullid != "local":
                        # local is the "name" given to a test-wide deck
                        # of data that is not target attached
                        _key += f" [{target_fullid}]"
                    data_xlat[_domain][_key] = value

    for domain, data in data_xlat.items():
        sheet_update_key_value(runid_pretty, data, "_KPI: %s" % domain)

    t.tick("sheet: updated")

app_name = "CI"

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description = __doc__,
        parents = [ oauth2client.tools.argparser ],
        formatter_class = argparse.RawDescriptionHelpFormatter)
    arg_parser.add_argument("-n", "--dry-run", action = "store_true", default = False,
                            help = "Do not actually modify the Google Sheet")
    arg_parser.add_argument("-u", "--url", action = "store", type = str,
                            default = None,
                            help = "URL (to generate hyperlinks) [%(default)s]")
    arg_parser.add_argument("-b", "--build-no", action = "store", type = str,
                            default = None,
                            help = "Build identifier (number), for reports")
    arg_parser.add_argument("-i", "--spreadsheet-id", action = "store", type = str,
                            default = None,
                            help = "ID of the spreadsheet where to store [%(default)s]")
    arg_parser.add_argument("-c", "--credentials-file", action = "store", type = str,
                            default = './credentials-%s.json' % app_name,
                            help = "Where to store credentials [%(default)s]")
    arg_parser.add_argument("-s", "--client-secret-file", action = "store", type = str,
                            default = './client-secret-%s.json' % app_name,
                            help = "Path to the client secrets file "
                            "[%(default)s]; this is the file "
                            "downloaded from the Google Developer "
                            "Console, API section" )
    arg_parser.add_argument("--limit-bpt", action = "store", type = int,
                            default = 100,
                            help = "Limit runids to display for Blockage Per "
                            "Target (%(default)d)")
    arg_parser.add_argument("--limit-fpt", action = "store", type = int,
                            default = 100,
                            help = "Limit runids to display for Failure Per "
                            "Target (%(default)d)")
    arg_parser.add_argument("--limit-ff", action = "store", type = int,
                            default = 60,
                            help = "Limit RunIDs to display for"
                            " Failure Frequency Target (%(default)d)")
    arg_parser.add_argument("--runid", action = "append", type = str,
                            default = [],
                            help = "Summarize this RunID")
    arg_parser.add_argument("--runid-no-raw", action = "store_true",
                            default = False,
                            help = "No cooking of runids;"
                            " long story short, in the past we assumed all runids started with 'ci-'"
                            " and we defined two strings ci-RUNID (raw) and RUNID (cooked); the code"
                            " was trying to be smart about it and if RUNID didn't start with ci-, it"
                            " auto-added it."

                            " Some stuff depends on this still, but if you specify this option, that"
                            " behaviour is disabled. In the future, this will be the default.")
    arg_parser.add_argument("--runid-extra", action = "store", type = str,
                            default = "",
                            help = "Extra info to add to RunID in certain "
                            "entries; keep it short!")
    arg_parser.add_argument("--ws-runid", action = "append", type = str,
                            default = [],
                            help = "Refresh this RUnID in the worksheet")
    arg_parser.add_argument("--max-rows-np", action = "store", type = int,
                            default = 10000,
                            help = "Limit to a maximum of [%(default)d] rows "
                            "on non passing testcase data")
    arg_parser.add_argument("--max-runids", action = "store", type = int,
                            default = 300,
                            help = "Limit the amount of rows we keep "
                            "per different RunIDs")
    arg_parser.add_argument("--max-runids-horizontal", action = "store", type = int,
                            default = 30,
                            help = "Limit the amount of column we keep "
                            "per different RunIDs for horizontal matrixes")
    arg_parser.add_argument("--mk-indexes", action = "store_true",
                            default = False,
                            help = "Create indexes (in background)")
    arg_parser.add_argument("--runid-summary-list", action = "store_true",
                            default = False,
                            help = "List runids available in summary")
    arg_parser.add_argument("--runid-separator", action = "store",
                            default = ":",
                            help = "Separate RUNID and TCHASH with %(default)s")
    arg_parser.add_argument("--runid-cache-file", action = "store",
                            default = None,
                            help = "Cache file for runids")
    arg_parser.add_argument("--remove-worksheets", action = "store",
                            default = None,
                            help = "(Internal) regex of worksheets to remove")
    mongol.arg_parse_add(arg_parser)

    args = arg_parser.parse_args()
    dry_run = args.dry_run
    logging.basicConfig(level = logging.WARNING)

    extra_params = {}
    mongol.args_chew(args, extra_params)
    mc = pymongo.MongoClient(args.mongo_url, **extra_params)
    db = mc[args.mongo_db]

    if not args.collection_id:
        raise ValueError("Please specify --collection-id")
    summary_collection = db[args.summary_collection_id]

    t = timestamp_c()
    if args.mk_indexes:
        _mongo_mk_indexes()
        sys.exit(0)

    if args.url and args.runid == None:
        print("ERROR: can only specify --url|-u with a single --runid")
        sys.exit(1)

    if args.runid_summary_list:
        for runid in sorted(summary_collection.distinct('_id')):
            print(runid)
        sys.exit(1)

    if args.runid_no_raw:
        runid_raw_prefix = ""
        runid_raw_prefix_len = len(runid_raw_prefix)

    if any(i == 'redo' for i in  args.runid):
        args.runid = _summary_runids_redo()
        for runid in _summary_runids_redo():
            if runid == '':
                continue
            try:
                _summary_refresh(runid)
            except pymongo.errors.PyMongoError as e:
                # go for next
                print("%s: error processing: " % runid, e)
    elif 'refresh' in args.runid:
        args.runid = _summary_runids_missing()
        for runid in args.runid:
            try:
                _summary_refresh(runid)
            except pymongo.errors.PyMongoError as e:
                # go for next
                print("%s: error processing: " % runid, e)
    elif args.runid:
        for runid in args.runid:
            _summary_refresh(runid)


    if args.spreadsheet_id:
        googlel.dry_run = args.dry_run
        g = googlel.app(app_name, args.credentials_file, args.client_secret_file)
        args.s = g.service_get(args)

        # We iterate over ws_runid to update only the runids specified
        # in the command line, defaulting to the same we were given to
        # refresh
        if 'redo' in args.ws_runid:
            t.tick("caching runids to refresh in worksheet")
            args.ws_runid = sorted(set(summary_collection.distinct('_id')))
            t.tick("cached %d runids to refresh in worksheet" % len(args.ws_runid))
        elif 'refresh' in args.ws_runid:
            # Ok, this is very basic an non complete "just run this",
            # but it is not enough BECAUSE it will not fill them in
            # the right order if there are holes
            # FIXME: how this has to evolve is that we keep, for each
            # worksheet, a cache of which RunIDs it contains and
            # before inserting with sheet_update_*, we look it up; if
            # already there, we skip, otherwise we INSERT it in the
            # right column/row
            t.tick("caching runids to refresh in worksheet")
            runids = summary_collection.distinct('_id')
            t.tick("cached %d runids to refresh in worksheet" % len(runids))
            sh = googlel.spreadsheet(args.s, args.spreadsheet_id,
                                    "_Summary per run", create = False)
            if sh == None:
                existing = [ ]
            else:
                existing = sh.sheet_column_get("A", fromrow = 2)
            args.ws_runid = sorted(runids - set(existing))
        elif args.ws_runid == []:
            args.ws_runid = args.runid

        for runid in args.ws_runid:
            sheet_update(runid)

        if args.remove_worksheets:
            regex = re.compile(args.remove_worksheets)
            sh = googlel.spreadsheet(args.s, args.spreadsheet_id, "_Summary per run")
            for worksheet in sh.metadata['sheets']:
                properties = worksheet.get('properties', {})
                title = properties.get('title', None)
                shid = properties.get('sheetId', None)
                if title.lower() == "_summary per run":
                    logging.warning("%s [%s]: not removing main worksheet", title, shid)
                    continue
                if regex.match(title):
                    logging.warning("%s [%s]: removing worksheet", title, shid)
                else:
                    logging.warning("%s [%s]: not removing worksheet (doesn't match)", title, shid)
                sh.sheet_delete(shid)
