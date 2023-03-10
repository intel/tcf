#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import argparse
import logging
import pprint
import pymongo
import pymongo.operations

import mongol

def print_doc(doc, **kwargs):
    if args.mode == 'raw':
        pprint.pprint(doc)
        for kw, val in kwargs.items():
            print("  %s" % kw, val)
    elif args.mode == 'chewed':
        print("""\
%(result)s %(_id)s %(tc_name)s @ %(target_name)s on %(timestamp)s""" % doc)
        for kw, val in kwargs.items():
            print("  ", kw, val)
        for result in doc['results']:
            if result['tag'] != 'DATA':
                prefix = "  %(tag)s%(level)-4d  " % result
                message = result['message'].encode('utf-8', errors = 'ignore')
                print("  %(tag)s%(level)-4d" % result, message)
                for key, val in result.get('attachment', {}).items():
                    if isinstance(val, str):
                        for line in val.split('\n'):
                            line = line.strip()
                            print(" " * (len(prefix) + 1), \
                                key.encode('utf-8', errors = 'ignore'), \
                                line.encode('utf-8', errors = 'ignore'))
                    else:
                        print(" " * (len(prefix) + 1), key, val)
                        print()
        for data in doc.get('data', []):
            print("  %s" % pprint.pformat(data))

arg_parser = argparse.ArgumentParser(
    description = __doc__,
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
arg_parser.add_argument("--mode", action = "store",
                        choices = [ "chewed", "raw" ], type = str,
                        default = "chewed",
                        help = "print mode")
arg_parser.add_argument("--runid-hashid", action = "store",
                        default = None,
                        help = "runid:hashid to pull")
arg_parser.add_argument("--runid", action = "store",
                        default = None,
                        help = "runid:hashid to pull")
arg_parser.add_argument("--tcname", action = "store",
                        default = None,
                        help = "testcase name to pull")
arg_parser.add_argument("--result", action = "store", type = str,
                        choices = [ 'PASS', 'FAIL', 'SKIP', 'BLCK' ],
                        default = None,
                        help = "Only testcases with given result")
arg_parser.add_argument("--pass", action = "store_const",
                        dest = 'result', const = 'PASS',
                        help = "Only testcases that pass")
arg_parser.add_argument("--target-types", action = "store", type = str,
                        dest = None,
                        help = "Only instances running on the given target type")
arg_parser.add_argument("--no-console-output", action = "store_true", dest = None,
                        help = "Print only TCs with no console output")
mongol.arg_parse_add(arg_parser)
args = arg_parser.parse_args()

extra_params = {}
mongol.args_chew(args, extra_params)
mc = pymongo.MongoClient(args.mongo_url, **extra_params)
db = mc[args.mongo_db]
collection = db[args.collection_id]

conditions = {}
if args.result:
    conditions['result'] = args.result
if args.target_types:
    conditions['target_types'] = args.target_types
if args.runid_hashid:
    conditions['_id'] = args.runid_hashid
if args.runid:
    conditions['runid'] = args.runid
if args.tcname:
    conditions['tc_name'] = args.tcname


for doc in db[args.collection_id].aggregate([
        {
            "$project" : {
                "target_types": "$target_types",
            }
        },
        {
            "$group": {
                "_id": "$target_types",
                "count": { "$sum": 1 }
            }
        },
]):
    print(doc)


logging.warning("Querying DB with conditions: %s", conditions)
for doc in collection.find(conditions):
    if args.no_console_output:
        console_output_present = False
        for result in doc['results']:
            if 'message' in result and 'build failed' in result['message']:
                # Fake it, this won't run, so it won't print console output
                console_output_present = True
                break
            for attachment, value in result.get('attachment', {}).items():
                if attachment == 'console output' and value != "":
                    console_output_present = True
                    break
            if console_output_present:
                break
        if console_output_present == False:
            print_doc(doc,
                      tcname = doc.get('tc_name', None),
                      targets = doc.get('target_name', None))
    else:
        print_doc(doc)
