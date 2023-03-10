#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
Sort the KPI worksheets at the end of a Google Spreadsheet

The worksheets names that are '_KPI: ' will be placed at the end in
alphabetical order.
"""

import argparse
import bisect
import logging
import pprint

import mongol
import oauth2client.tools
import googlel

app_name = "CI"


arg_parser = argparse.ArgumentParser(
    description = __doc__,
    parents = [ oauth2client.tools.argparser ],
    formatter_class = argparse.RawDescriptionHelpFormatter)
arg_parser.add_argument("-n", "--dry-run", action = "store_true", default = False,
                        help = "Do not actually modify the Google Sheet")
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

mongol.arg_parse_add(arg_parser)

args = arg_parser.parse_args()
dry_run = args.dry_run
logging.basicConfig(level = logging.WARNING)

def worksheets_list(sh):
    _worksheets = []
    metadata = sh.sheet_metadata_get()
    for worksheet in metadata['sheets']:
        for key, val in worksheet.items():
            if key == 'properties':
                break
        else:
            continue
        title = val['title']
        index = val['index']
        _worksheets.append((title, index))

    return _worksheets

googlel.dry_run = args.dry_run
g = googlel.app(app_name, args.credentials_file, args.client_secret_file)
args.s = g.service_get(args)

# Just load any wokrsheet we know has to be there
sh = googlel.spreadsheet(args.s, args.spreadsheet_id,
                         "_Summary per run", create = False)

worksheets = sorted(worksheets_list(sh), key = lambda x: x[1])
count = len(worksheets)
print("D: original worksheet order")
pprint.pprint(worksheets)
for title, index in reversed(worksheets):
    if not title.startswith("_KPI: "):
        break
    count -= 1

print("D: will move KPI worksheets at #%d %s" % (count, title))

# We are going to put the _KPIs: at the end of the list. We know where
# we have to start appending (count which gives us the half of the
# sublist where the KPIs have to be).
#
# Then we scan the list, if we find a KPI, we remove it from its
# current position and find it where it has to be inserted at the KPI
# bottom half.
index2 = 0
for title, index in list(worksheets):
    if not title.startswith("_KPI: "):
        index2 += 1
        continue
    del worksheets[index2]
    new_pos = bisect.bisect_right(worksheets, (title, index), lo = count)
    print("D: moving to #%d/%s to %d" % (index2, title, new_pos))
    bisect.insort_right(worksheets, (title, index), lo = count)
    worksheet = googlel.spreadsheet(args.s, args.spreadsheet_id, title)
    worksheet.sheet_order_update(new_pos)
    count -= 1

print("D: final worksheet order")
pprint.pprint(worksheets)
