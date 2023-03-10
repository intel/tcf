#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""
Wipe from the database records matching a certain build
"""
import argparse
import bisect
import commonl
import datetime
import logging
import oauth2client
import oauth2client.tools
import pymongo
import pymongo.operations
import time

import mongol

app_name = "CI"

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description = __doc__,
        parents = [ oauth2client.tools.argparser ],
        formatter_class = argparse.RawDescriptionHelpFormatter,)
    arg_parser.set_defaults(level = logging.ERROR)
    arg_parser.add_argument("-d", "--details",
                            action = "count", default = 0,
                            help = "Increase amount of details printed")
    arg_parser.set_defaults(level = logging.ERROR, logging_level = 'ERROR')
    arg_parser.add_argument("-n", "--dry-run", action = "store_true", default = False,
                            help = "Do not actually modify the Google Sheet")
    arg_parser.add_argument("-u", "--url", action = "store", type = str,
                            default = 'https://FIXMEURL/',
                            help = "URL (to generate hyperlinks) [%(default)s]")
    arg_parser.add_argument("-r", "--run-id", action = "store", type = str,
                            default = None,
                            help = "ID of this run, defaults to "
                            "YYYY/MM/DD-HH:MM timestamp of the file)")
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
                            default = 60,
                            help = "Limit runids to display for Blockage Per "
                            "Target (%(default)d)")
    arg_parser.add_argument("--limit-ff", action = "store", type = int,
                            default = 60,
                            help = "Limit RunIDs to display for"
                            " Failure Frequency Target (%(default)d)")
    arg_parser.add_argument("--runid", action = "store", type = str,
                            default = None,
                            help = "Refresh summaries starting with "
                            " this runid or "
                            "after; note this is meant to sort against "
                            "the RunIDs (ci-000000-0000 < "
                            "ci-170201-1231-43 < ci-170303)")
    arg_parser.add_argument("--max-rows-np", action = "store", type = int,
                            default = 10000,
                            help = "Limit to a maximum of [%(default)d] rows "
                            "on non passing testcase data")
    arg_parser.add_argument("--mk-indexes", action = "store_true",
                            default = False,
                            help = "Create indexes (in background)")
    arg_parser.add_argument("--total-ran-lt", metavar = "N",
                            action = "store", default = None, type = int,
                            help = "Wipe anything that ran less than N testcases"
    )
    arg_parser.add_argument("--since-runid", metavar = "RUNID",
                            action = "store", default = "ci-0000", type = str,
                            help = "Start at the given runid [%(default)s]"
    )
    mongol.arg_parse_add(arg_parser)

    args = arg_parser.parse_args()

    extra_params = {}
    mongol.args_chew(args, extra_params)
    mc = pymongo.MongoClient(args.mongo_url, **extra_params)
    db = mc[args.mongo_db]
    collection = db[args.collection_id]
    summary_collection = db[args.collection_id + "_summary_per_run"]

    import sys, pprint


    if args.total_ran_lt:
        sorts = set()

        # Collect the runids from the summary first, don't delete them yet
        for doc in summary_collection.find({
                '_id': { "$gte": args.since_runid },
                'total_ran': { "$lt": args.total_ran_lt }
        }):
            docid = doc['_id']
            sorts.add(docid)
        print("%s: identified from summary DB: " % args.collection_id, sorts)

        print("%s: removing from main DB" % args.collection_id, sorts)
        collection.delete_many({
                'runid': { "$in": list(sorts) },
        })
        print("%s: removed from main DB" % args.collection_id, sorts)

        print("%s: removing summary entries" % args.collection_id)
        sorts = set()
        summary_collection.remove({
                '_id': { "$gte": "ci-170720" },
                'total_ran': { "$lt": 1000 }
        })
        print("%s: removed summary entries" % args.collection_id)
