#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""


1. Obtain credentials:
   - Navigate to https://console.developers.google.com
   - Select *Credentials*
   - Select *Create Credential* > *Oauth client ID*
   - Select ID* *None*, and give it a name (NAME)
   - Select *Application Type* > *Other*
   - click *OK* and ignore the details presented

2. Download the new client secret credentials:
   - Enable *Google Sheet API* in the project link
     https://console.developers.google.com
   - Go back to https://console.developers.google.com/apis/credentials
   - Look for the new credential name *NAME*
   - Select the icon that allows to download the JSON file, download
     and save to be the client_secret_NAME.json file

3. Create a new sheet:
   - Go to https://docs.google.com/spreadsheets
   - Start a new *blank* spreadsheet
   - Name the sheet by clicking on *Untitled spreadsheet*
   - Save the sheet ID from the URL; eg, in
     https://docs.google.com/spreadsheets/d/SHEETID/edit#gid=0
     it would be *SHEETID*, but about 40 chars long.

   Initialize the sheet:

   - Create subsheets named:

     - *_coverity issues*

     the script relies on this being properly spelled.

5. Launch the script from the console and feed it some log file,
   pointing to the client secret file::

     $ ./import-google-sheet.py -v -i SHEETID \
           --noauth_local_webserver \
           -s client_secret.json \
           /dev/null

   A message like::

     .../site-packages/oauth2client/_helpers.py:255: UserWarning: Cannot access ./credentials.json: No such file or directory
     warnings.warn(_MISSING_FILE_MESSAGE.format(filename))

     Go to the following link in your browser:

       https://accounts.google.com/o/oauth2/auth?scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fspreadsheets&redirect_uri=urn%3Aietf%3Awg%3Aoauth%3A2.0%3Aoob&response_type=code&client_id=6663245526205-ad6j411pfppqtfib1pgkd1vuut6joijh.apps.googleusercontent.com&access_type=offline

     Enter verification code:


   go to a web browser, paste that URL and follow the instructions
   until you are given a page that says something like::

     Please copy this code, switch to your application and paste it there:

     4/op8lpe_M5nEIcjPt7ejkejdUGJb24fd-czxhWC-ptU

   enter it back in the terminal that was asking for it.

   This creates a credential file
   (*credentials.json*) that you can remove to
   restart the process.

Notes:

- The following warning appear on fedora, but it doesn't have any
  impact and can be ignored::

    Traceback (most recent call last):
      File "/usr/lib/python2.7/site-packages/googleapiclient/discovery_cache/__init__.py", line 41, in autodetect
        from . import file_cache
      File "/usr/lib/python2.7/site-packages/googleapiclient/discovery_cache/file_cache.py", line 41, in <module>
        'file_cache is unavailable when using oauth2client >= 4.0.0')
    ImportError: file_cache is unavailable when using oauth2client >= 4.0.0

"""

import httplib2
import logging
import oauth2client
import oauth2client.file
import oauth2client.tools
import string
import time
import pprint

from googleapiclient import discovery

dry_run = False

def retryable_error(s, count):
    if 'Insufficient tokens for quota' in s \
        or 'Quota exceeded for quota' in s \
        or 'Bad Gateway' in s \
        or 'The service is currently unavailable' in s \
        or 'The operation was aborted' in s \
        or 'Deadline expired before operation could complete' in s:
        cutoff = 3
        # semi-exponential backoff -- otherwise we hit about 10min by
        # iteration #4 and this will take for ever
        if count < 3:
            wait = 5 ** count
        else:
            wait = 5 * cutoff + 5 * count
        return wait
    # linear backoff
    elif 'Internal error encountered' in s:
        return 5 * count
    else:
        return  0

def retry_google_operation(_func):

    def _wrapper(*args, **kwargs):
        top_retries = 10
        retry = 0
        while retry < top_retries:
            retry += 1
            try:
                return _func(*args, **kwargs)
            except Exception as e:
                s = str(e)
                wait = retryable_error(s, retry)
                if retry >= top_retries:
                    logging.error("over quota / deadline, Too many retries (%d)", retry)
                    raise
                elif wait:
                    logging.warning("quota or timeout? retrying #%d after %ds, exception %s",
                                    retry, wait, e)
                    time.sleep(wait)
                    continue
                else:
                    logging.error("unretriable exception: %s", e)
                    raise

    return _wrapper

class bunch_c:
    def __init__(self, **kwds):
        self.__dict__.update(kwds)

class app(object):

    def __init__(self, name, credentials_filename, client_secret_filename):
        self.name = name
        self.credentials_filename = credentials_filename
        self.client_secret_filename = client_secret_filename

    def _credentials_get(self, args):
        """
        FIXME
        """
        store = oauth2client.file.Storage(self.credentials_filename)
        credentials = store.get()
        if not credentials or credentials.invalid:
            flow = oauth2client.client.flow_from_clientsecrets(
                self.client_secret_filename,
                'https://www.googleapis.com/auth/spreadsheets')
            flow.user_agent = self.name
            credentials = oauth2client.tools.run_flow(flow, store, args)
            logging.info('storing credentials at: ' + self.credentials_filename)
        return credentials

    def service_get(self, args):
        credentials = self._credentials_get(args)
        http = credentials.authorize(httplib2.Http())
        service = discovery.build(
            'sheets', 'v4', http = http, cache_discovery=False,
            discoveryServiceUrl = ('https://sheets.googleapis.com/$discovery/rest?'
                                   'version=v4')
        )
        return service


class spreadsheet(object):
    def __init__(self, service, spreadsheet_id, sheet_name, sheet_id = None,
                 create = True):
        """
        :param str sheet_name: Name of the worksheet; note it is case
           insensitive, so internally it has to be all done in lower case.
        """
        self.service = service
        self.spid = spreadsheet_id
        self.sheet_name = sheet_name
        self._shid = None
        self._last_flush = time.time()
        self._last_requests = 0
        self._format_requests = []
        self._values = []
        self._spreadsheet_requests = []
        self.created = False
        if sheet_id == None:
            try:
                self._shid = self.sheet_name_to_id()
            except ValueError:
                if create:
                    self._sheet_add()
                    self.created = True
                    if dry_run:
                        self._shid = None
                    else:
                        self._shid = self.sheet_name_to_id()
                else:
                    self.sheet_metadata_get()
        else:
            self._shid = sheet_id
            self.sheet_metadata_get()

    @retry_google_operation
    def sheet_metadata_get(self):
        return self.service.spreadsheets().get(spreadsheetId = self.spid)\
                                          .execute()

    @staticmethod
    @retry_google_operation
    def result_get_values(result, _id, default):
        return result.get(_id, default)

    def sheet_get_row_count(self):
        """
        Return the number of rows the sheet had when this object was created
        """
        sheet_name_lower = self.sheet_name.lower()
        for worksheet in self.metadata['sheets']:
            # DEBUG pprint.pprint(worksheet)
            properties = worksheet.get('properties', {})
            title = properties.get('title', None).lower()
            if title == sheet_name_lower:
                return properties['gridProperties']['rowCount']
        raise RuntimeError('%s: worksheet not found? BUG?' % self.sheet_name)

    def sheet_get_column_count(self):
        """
        Return the number of columns the sheet had when this object was created
        """
        sheet_name_lower = self.sheet_name.lower()
        for worksheet in self.metadata['sheets']:
            properties = worksheet.get('properties', {})
            title = properties.get('title', None).lower()
            if title == sheet_name_lower:
                return properties['gridProperties']['columnCount']
        raise RuntimeError('%s: worksheet not found? BUG?' % self.sheet_name)

    def sheet_column_get(self, colno = 0, fromrow = 1, torow = ""):
        """
        Return the number of columns the sheet had when this object was created
        """
        if isinstance(colno, str):
            colno_ab = colno
        else:
            assert colno > 0
            colno_ab = self.number_to_letters(colno)

        @retry_google_operation
        def _get():
            return self.service.spreadsheets().values().get(
                spreadsheetId = self.spid,
                range = "%s!%s%d:%s%s" % (self.sheet_name, colno_ab, fromrow, colno_ab, torow)).execute()
        column = [ ]
        for row in self.result_get_values(_get(), 'values', []):
            column += row
        return column

    def sheet_name_to_id(self, sheet_name = None, raise_exception = True):
        # Note all the chart names are case insensitive :/
        if dry_run:
            # yah, something dud but unique, we don't use it anyway
            return id(sheet_name)
        if sheet_name == None:
            sheet_name = self.sheet_name
        # name comparsion for effects of chart creation is case insensitive :/
        sheet_name = sheet_name.lower()
        self.metadata = self.sheet_metadata_get()
        sheets = self.metadata.get('sheets', [])
        if not sheets:
            raise ValueError("%s: BUG? no metadata" % self.sheet_name)
        #print "DEBUG sheets", pprint.pformat(sheets)
        for sheet in sheets:
            #print "DEBUG sheet", sheet
            properties = sheet.get("properties", {})
            #print "DEBUG properties", properties
            #print "DEBUG title", properties.get("title", None)
            title = properties.get("title", None).lower()
            if sheet_name == title:
                return properties.get("sheetId", 0)
        if raise_exception:
            raise ValueError("%s: unknown sub-sheet" % self.sheet_name)
        else:
            return None

    @property
    def shid(self):
        if self._shid == None:
            self._shid = self.sheet_name_to_id()
        return self._shid


    def cell_format(self, attr, value,
                    fromrow = 0, fromcol = 0, torow = 0, tocol = 0):
        self._format_requests.append({
            'repeatCell': {
                'range': {
                    'sheetId': self.shid,
                    'startRowIndex': fromrow, 'startColumnIndex': fromcol,
                    'endRowIndex': torow, 'endColumnIndex': tocol,
                },
                'cell':  {
                    'userEnteredFormat': {
                        attr: value
                    }
                },
                'fields': 'userEnteredFormat.' + attr,
            }
        })
        self.formatting_maybe_flush()

    def sheet_format_clear(self):
        self._spreadsheet_requests.append({
            "updateCells": {
                'range': {
                    'sheetId': self.shid
                },
                'fields': "userEnteredFormat"
            }
        })

    def sheet_chart_make(self, name, chartspec):
        shid = self.sheet_name_to_id(name, False)
        #print "DEBUG chart make", name, shid
        if shid:
            # Already existing, return an object representing it
            return type(self)(self.service, self.spid, name,
                              sheet_id = shid)

        self._spreadsheet_requests.append({
            "addChart": {
                'chart': chartspec
            }
        })
        r = self.flush()
        # FIXME: maybe  check for errors before assuming?
        new_shid = r[0]['addChart']['chart']['position']['sheetId']

        newsh = type(self)(self.service, self.spid, name, sheet_id = new_shid)
        newsh.sheet_title_set(name)
        newsh.flush()
        return newsh

    def title_set(self, newtitle):
        self._spreadsheet_requests.append({
            'updateSpreadsheetProperties': {
                'properties': {
                    'title': newtitle
                },
                'fields': 'title'
            }
        })

    def sheet_order_update(self, newindex):
        """
        Change the order of the worksheet this object represents to be
        in the @newindex

        :param int newindex: New (zero based) index where the sheet
            will be moved to.
        """
        self._spreadsheet_requests.append({
            'updateSheetProperties': {
                'properties': {
                    'sheetId': self.shid,
                    'index': newindex,
                },
                'fields': 'index'
            }
        })
        self.spreadsheet_requests_flush()

    def sheet_title_set(self, newtitle):
        self._spreadsheet_requests.append({
            'updateSheetProperties': {
                'properties': {
                    'sheetId': self.shid,
                    'title': newtitle
                },
                'fields': 'title'
            }
        })

    def sheet_size_set(self, rows, columns):
        """
        Change the size of a sheet to said rows and columns

        :param int rows: number of rows
        :param int columns: number of columns
        """
        self._spreadsheet_requests.append({
            'updateSheetProperties': {
                'properties': {
                    'sheetId': self.shid,
                    'gridProperties': {
                        'rowCount': rows,
                        'columnCount': columns,
                    }
                },
                'fields': 'gridProperties'
            }
        })
        self.spreadsheet_requests_flush()

    def rows_insert(self, index, rows = 1):
        """
        Change the order of the worksheet this object represents to be
        in the @newindex

        :param int newindex: New (zero based) index where the sheet
            will be moved to.
        """
        self._spreadsheet_requests.append({
            'insertDimension': {
                'range': {
                    'sheetId': self.shid,
                    'dimension': "ROWS",
                    'startIndex': index,
                    'endIndex': index + rows,
                },
                'inheritFromBefore': True,
            }
        })
        self.spreadsheet_requests_flush()


    def columns_insert(self, index, columns = 1):
        """
        Insert one or more columns at column @index
        """
        self._spreadsheet_requests.append({
            'insertDimension': {
                'range': {
                    'sheetId': self.shid,
                    'dimension': "COLUMNS",
                    'startIndex': index,
                    'endIndex': index + columns,
                },
                'inheritFromBefore': True,
            }
        })
        self.spreadsheet_requests_flush()


    @staticmethod
    def number_to_letters(n):
        n += 1	# Indexes are base 0, AA notation is base 1
        letters = ''
        alphas = string.ascii_uppercase
        while n:
            m = (n - 1) % 26
            n = int((n - m) / 26)
            letters += alphas[m]
        return letters[::-1]

    @retry_google_operation
    def feed_rows(self, rows, fromrow = 0, fromcol = 0,
                  torow = -1, tocol = -1, clear_values = True):
        if not rows:
            return
        fromcol_letter = self.number_to_letters(fromcol)
        if tocol == -1:
            maxcols = max([len(row) for row in rows])
            tocol = fromcol = maxcols
        tocol_letter = self.number_to_letters(fromcol)
        if torow == -1:
            torow = fromrow + len(rows)
            # For clearing, if torow is set to default, then clear it all
            torow_clear = ""
        else:
            torow_clear = "%d" % (torow + 1)
        if dry_run:
            return

        # Clear existing values (not formatting)
        if clear_values:
            self.service.spreadsheets().values().clear(
                spreadsheetId = self.spid,
                # Clear everything
                range = "%s!%s%d:%s%s" % (
                    self.sheet_name,
                    fromcol_letter, fromrow + 1,
                    tocol_letter, torow_clear
                ),
                body = {}).execute()
        result = self.service.spreadsheets().values().update(
            spreadsheetId = self.spid,
            range = "%s!%s%d:%s%d" % (
                self.sheet_name,
                fromcol_letter, fromrow + 1,
                tocol_letter, torow + 1
            ),
            valueInputOption = "USER_ENTERED",
            body = { 'values' : rows }).execute()
        return result

    def column_format_autoresize(self, fromcol, tocol):
        # Autoresize column width
        self._spreadsheet_requests.append({
            "autoResizeDimensions": {
                "dimensions": {
                    'sheetId': self.shid,
                    "dimension": "COLUMNS",
                    "startIndex": fromcol,
                    "endIndex": tocol,
                }
            }
        })
        self.spreadsheet_requests_maybe_flush()


    def sheet_column_width(self, width, fromcol, tocol):
        self._spreadsheet_requests.append({
            "updateDimensionProperties": {
                "range": {
                    'sheetId': self.shid,
                    "dimension": "COLUMNS",
                    "startIndex": fromcol,
                    "endIndex": tocol,
                },
                "properties": {
                    "pixelSize": width
                },
                "fields": "pixelSize"
            }
        })
        self.spreadsheet_requests_maybe_flush()


    def sheet_row_height(self, width, fromrow, torow):
        self._spreadsheet_requests.append({
            "updateDimensionProperties": {
                "range": {
                    'sheetId': self.shid,
                    "dimension": "ROWS",
                    "startIndex": fromrow,
                    "endIndex": torow,
                },
                "properties": {
                    "pixelSize": width
                },
                "fields": "pixelSize"
            }
        })
        self.spreadsheet_requests_maybe_flush()


    def _sheet_add(self):
        # Autoresize column width
        self._spreadsheet_requests.append({
            "addSheet": {
                "properties": {
                    'title': self.sheet_name,
                    'gridProperties': {
                        'rowCount': 100,
                        'columnCount': 26,
                    },
                },
            }
        })
        self.spreadsheet_requests_flush()


    def sheet_delete(self, shid = None):
        if shid == None:
            shid = self._shid
        # Autoresize column width
        self._spreadsheet_requests.append({
            "deleteSheet": {
                "sheetId": shid,
            }
        })
        self.spreadsheet_requests_flush()

    @retry_google_operation
    def formatting_flush(self):
        if not self._format_requests:
            return
        if dry_run:
            r = { 'replies': [ True ] }
        else:
            r = self.service.spreadsheets().batchUpdate(
                spreadsheetId = self.spid,
                body = { 'requests': self._format_requests}).execute()
        self._format_requests = []
        return r

    def formatting_maybe_flush(self):
        if len(self._format_requests) < 400:
            return
        self.formatting_flush()

    @retry_google_operation
    def spreadsheet_requests_flush(self):
        if not self._spreadsheet_requests:
            return
        if dry_run:
            r = { 'replies': [ True ] }
        else:
            r = self.service.spreadsheets().batchUpdate(
                spreadsheetId = self.spid,
                body = { "requests": self._spreadsheet_requests }).execute()
        self._spreadsheet_requests = []
        return r

    def spreadsheet_requests_maybe_flush(self):
        if len(self._values) < 400:
            return
        self.spreadsheet_requests_flush()

    def values_flush(self):
        if not self._values:
            return
        if dry_run:
            r = { 'replies': [ True ] }
        else:
            r = self.service.spreadsheets().values().batchUpdate(
                spreadsheetId = self.spid,
                body = {
                    'valueInputOption': 'USER_ENTERED',
                    'data': self._values }).execute()
        self._values = []
        return r

    def values_maybe_flush(self):
        if len(self._values) < 400:
            return
        self.values_flush()

    def flush(self):
        r = []
        rr = self.values_flush()
        if rr:
            r += rr['replies']
        rr  = self.formatting_flush()
        if rr:
            r += rr['replies']
        rr = self.spreadsheet_requests_flush()
        if rr:
            r += rr['replies']
        return r
