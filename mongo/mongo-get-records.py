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
import sys
import ssl

import mongol

def print_no_console_output(doc, target_list):
    if args.project == [] or args.project == None:
        args.project = [
            'runid', 'hashid', 'tc_name',
            'target_names', 'target_types', 'bsp_models'
        ]
    vals = [ doc.get(field, "n/a") for field in args.project ]
    print(",".join([ str(val) for val in vals ]))

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

def has_console_output(doc):
    # check which wanted targets we have to consider; this is how the
    # test calls the target (kinda like the target role)--in some
    # cases we don't want to consider some targets to test for no
    # console ouput, because thy do not produce console output
    # naturally.
    targets = doc.get('targets', {})
    targets_to_consider = set()
    if args.no_console_output_targets == []:
        twns = targets.keys()
    else:
        twns = args.no_console_output_targets
    for twn in twns:
        targets_to_consider.add(
            targets[twn]['server'] + "/" + targets[twn]['id'])

    if doc['result'] in ( "SKIP", 'BLCK', 'PASS' ):
        # SKIPs or BLCKs can't run, so they can't be considered as
        # having console output or not. PASS we consider to be good too
        return True
    else:
        for result in doc['results']:
            if 'message' in result and (
                    'build errored:' in result['message']
                    # before we did not use past tense in 'error'
                    or 'build error:' in result['message']
                    or 'build failed:' in result['message']
                    or 'subtestcase errored:' in result['message']
            ):
                # Fake it, this won't run, so it won't print console output
                return True
            # if this result message comes from a target, let's see if
            # we have to consider it
            if 'target_name' in result:
                target_name = result['target_name']
                # printed as ' @SERVER/NAME', not sure why
                if target_name.startswith(' @'):
                    target_name = target_name[2:]
                if not target_name in targets_to_consider:
                    continue
            for attachment, value in result.get('attachment', {}).items():
                if attachment == 'console output' and value != "":
                    # yepppp, there is console output
                    return True
    return False

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
                        help = "runid to pull")
arg_parser.add_argument("--field", metavar = "FIELD:VALUE", action = "store",
                        default = None,
                        help = "Search for records with VALUE in FIELD")
arg_parser.add_argument("--fieldregex", metavar = "FIELD:REGEX", action = "append",
                        default = [],
                        help = "Search for records with FIELD mathing REGEX")
arg_parser.add_argument("--project", action = "append",
                        default = [],
                        help = "fields to project (only get those fields "
                        "and print them in CSV format)")
arg_parser.add_argument("--hashid", action = "store",
                        default = None,
                        help = "hashid to pull")
arg_parser.add_argument("--tcname", action = "store",
                        default = None,
                        help = "testcase name to pull")
arg_parser.add_argument("--tcs-list", action = "store", metavar = "RUNID",
                        default = None,
                        help = "List all the testcases on a RunID; "
                        "use 'all' for all runs")
arg_parser.add_argument("--runids-list", action = "store_true",
                        default = False,
                        help = "List all the RunIDs available")
arg_parser.add_argument("--runids-raw-list", action = "store_true",
                        default = False,
                        help = "List all the RunIDs available from "
                        "the raw database")
arg_parser.add_argument("--result", action = "store", type = str,
                        choices = [ 'PASS', 'ERRR', 'FAIL', 'SKIP', 'BLCK' ],
                        default = None,
                        help = "Only testcases with given result")
arg_parser.add_argument("--pass", action = "store_const",
                        dest = 'result', const = 'PASS',
                        help = "Only testcases that pass")
arg_parser.add_argument("-i", action = "store", dest = '', help = "Ignored")
arg_parser.add_argument("--target-types", action = "store", type = str,
                        dest = None,
                        help = "Only instances running on the given target type")
arg_parser.add_argument("--no-console-output", action = "store_true",
                        default = False,
                        help = "Print only TCs which errored or failed with "
                        "no console output (except skips and build errors)")
arg_parser.add_argument("--no-console-output-targets", metavar = "TARGET-WANT-NAME",
                        action = "append", default = [],
                        help = "Consider only the named targets when "
                        "looking for lack of console output "
                        "(e.g. target, ic)--defaults to all")
arg_parser.add_argument("--no-hint", action = "store_false", dest = 'hint',
                        default = True,
                        help = "Print only TCs with no console output")
arg_parser.add_argument("--collections", action = "store_true",
                        default = False,
                        help = "List available collections")
arg_parser.add_argument("--collection-count", action = "store_true",
                        default = False,
                        help = "Print number of records in the collections")
arg_parser.add_argument("--headers", action = "store_true",
                        default = False,
                        help = "Print column headers")
mongol.arg_parse_add(arg_parser)

args = arg_parser.parse_args()

extra_params = {}
mongol.args_chew(args, extra_params)
mc = pymongo.MongoClient(args.mongo_url, **extra_params)
db = mc[args.mongo_db]

if args.collections:
    for collection in db.collection_names():
        print(collection)
    sys.exit(0)

collection = db[args.collection_id]

if args.tcs_list and args.tcs_list.lower() == "all":
    collection = db[args.collection_id + "_summary_per_run"]
    iterator = collection.aggregate([
            {
                "$unwind" : "$tcs" ,
            },
            {
                "$group" : {
                    "_id": "$tcs"
                },
            }
    ])
    for tcname in sorted([ doc['_id'] for doc in iterator ]):
        print(tcname)
    sys.exit(0)
if args.tcs_list != None:
    summary_collection = db[args.collection_id + "_summary_per_run"]
    runid = args.tcs_list
    doc = summary_collection.find_one({ "_id": runid })
    for tc in sorted(doc['tcs']):
        print(tc)
    sys.exit(0)

if args.runids_list:
    collection = db[args.collection_id + "_summary_per_run"]
    iterator = collection.find({ }, projection = { "runid": True })
    l = [ doc['_id'] for doc in iterator ]
    for _id in sorted(l):
        print(_id)
    sys.exit(0)

if args.collection_count:
    collection = db[args.collection_id]
    # this should be allowing us to only get that data, but I can't find it
    doc_count = db.command("collstats", "widget-runner")['count']
    print(doc_count)
    sys.exit(0)

if args.runids_raw_list:
    collection = db[args.collection_id]
    iterator = collection.aggregate([
            {
                "$match": {
                    # match on both fields so the runid-hash index is used
                    "runid": { "$exists": True },
                    "hashid": { "$exists": True },
                }
            },
            {
                "$project" : {
                    # 1 means pass these through
                    "runid": 1,
                },
            },
            {
                "$group": {
                    "_id": '$runid',
                }
            }
    ])
    for doc in iterator:
        print(doc)
    sys.exit(0)

if args.hint:
    conditions = {
        'runid': { "$exists": True },
        'hashid': { "$exists": True },
    }
else:
    conditions = { }
if args.result:
    conditions['result'] = args.result
if args.target_types:
    conditions['target_types'] = args.target_types
if args.runid_hashid:
    conditions['_id'] = args.runid_hashid
if args.runid:
    conditions['runid'] = args.runid
if args.hashid:
    conditions['hashid'] = args.hashid
if args.tcname:
    conditions['tc_name'] = args.tcname
if args.field:
    field, value = args.field.split(":", 1)
    conditions[field] = value
    args.hint = False
for arg in args.fieldregex:
    field, value = arg.split(":", 1)
    conditions[field] = {'$regex' : value }
    if 'hashid' not in conditions and 'runid' not in conditions:
        args.hint = False

logging.warning("Querying DB with conditions: %s", conditions)
if args.project == []:
    projection = None
else:
    projection = { i: 1 for i in args.project }

if (args.runid or args.hashid) and args.hint:
    iterator = collection.find(conditions, projection = projection).hint('runid-hash')
elif 'tc_name' in conditions:
    iterator = collection.find(conditions, projection = projection).hint('tc_name')
else:
    iterator = collection.find(conditions, projection = projection)
cnt = 0

if args.headers:
    print(",".join(args.project))

for doc in iterator.limit(0):
    # fake adding the target_names and bsp_models records, because we
    # suck and don't add it on the database. This makes it easier to
    # print info later, rather than trying to parse the full targets
    # array.
    targets = doc.get('targets', {})
    if not 'target_names' in doc:
        target_names = []
        for twn in sorted(targets.keys()):
            target_names.append(
                targets[twn].get('server', 'n-a') + "/" + targets[twn]['id'])
        doc['target_names'] = "|".join(target_names)
    if not 'bsp_models' in doc:
        bsp_models = []
        for twn in sorted(targets.keys()):
            bsp_model = targets[twn].get('bsp_model', 'n/a')
            if bsp_model:
                bsp_models.append(targets[twn].get('bsp_model', 'n/a'))
        doc['bsp_models'] = "|".join(bsp_models)
    cnt += 1
    if cnt > 0 and cnt % 1000 == 0:
        logging.warning("Record #%d", cnt)
    if args.no_console_output:
        if not has_console_output(doc):
            print_no_console_output(doc, args.no_console_output)
    elif args.project:
        values = []
        for field in args.project:
            if '.' in field:
                value = doc
                subscripts = field.split('.')
                for subscript in subscripts:
                    try:
                        value = value.get(subscript, 'n/a')
                    except AttributeError:
                        break
                    except (AttributeError, IndexError) as e:
                        value = "n/a"
                        break
            else:
                value = doc.get(field, 'n/a')
            values.append(value)
        print(",".join([ str(value) for value in values ]))
    else:
        print_doc(doc)
