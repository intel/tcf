#! /usr/bin/env python3
#
# Copyright (c) 2026 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""Download a Google Spreadsheet

Needs a client secret file with permissions to download; see
:module:`googlel` for details.

"""
# pylint: disable = bad-whitespace

import argparse
import logging
import pathlib

import oauth2client
import oauth2client.tools

import googleapiclient.discovery
import googleapiclient.http

import googlel


app_name = "CI"

arg_parser = argparse.ArgumentParser(
    description = __doc__,
    parents = [ oauth2client.tools.argparser ],
    formatter_class = argparse.RawDescriptionHelpFormatter)
arg_parser.add_argument(
    "file_name", action = "store", type = str,
    default = None,
    help = "where to download; extension determines the"
    " format: .xlsx, .ods, .csv")
arg_parser.add_argument(
    "spreadsheet_id", action = "store", type = str,
    default = None,
    help = "ID of the spreadsheet to download")
arg_parser.add_argument(
    "credentials_file", action = "store", type = str,
    default = './credentials-%s.json' % app_name,
    help = "Where to store credentials [%(default)s]")
arg_parser.add_argument(
    "client_secret_file", action = "store", type = str,
    default = './client-secret-%s.json' % app_name,
    help = "Path to the client secrets file [%(default)s]; this is"
    " the file downloaded from the Google Developer Console, API section" )

args = arg_parser.parse_args()
logging.basicConfig(level = logging.WARNING)

out_path = pathlib.Path(args.file_name)

# Google Sheets export MIME types
if out_path.suffix.lower() == ".xlsx":
    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
elif out_path.suffix.lower() == ".ods":
    mime_type = "application/x-vnd.oasis.opendocument.spreadsheet"
elif out_path.suffix.lower() == ".csv":
    # CSV export is single-sheet; Drive exports the first/active sheet
    mime_type = "text/csv"
else:
    raise ValueError("Use .xlsx|.csv|.ods for out_path")

g = googlel.app(app_name, args.credentials_file, args.client_secret_file)
store = g.store_get(args)
drive = googleapiclient.discovery.build(
    "drive", "v3", credentials = store.get())
request = drive.files().export_media(
    fileId = args.spreadsheet_id, mimeType = mime_type)

with out_path.open("wb") as f:
    downloader = googleapiclient.http.MediaIoBaseDownload(f, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

print(f"I: downloaded {args.spreadsheet_id} to {out_path}")
