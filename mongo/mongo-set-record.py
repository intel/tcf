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
import ssl

import mongol

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
arg_parser.add_argument("RECORDID", action = "store",
                        nargs = 1,
                        help = "ID for the record")
arg_parser.add_argument("FIELDVALUE", action = "store",
                        nargs = "+",
                        default = [], help = "Fields/values to store")
mongol.arg_parse_add(arg_parser)

args = arg_parser.parse_args()

extra_params = {}
mongol.args_chew(args, extra_params)
mc = pymongo.MongoClient(args.mongo_url, **extra_params)
db = mc[args.mongo_db]
collection = db[args.collection_id]

record_id = args.RECORDID[0]
records = {}
logging.error("RID %s FIELD %s", record_id, args.FIELDVALUE)
for record in args.FIELDVALUE:
    if not ":" in record:
        logging.error("Malformed FIELD:VALUE, missing colon/value? %s", record)
        continue
    key, value = record.split(":")
    try:
        value = int(value)
    except ValueError as e:
        value = value
    records[key] = value
if records:
    logging.info("Inserting %s", records)
    collection.update_one({ '_id': record_id }, { "$set": records }, upsert = True)
