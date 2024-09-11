#! /usr/bin/env python3
#
# Copyright (c) 2024 Intel Corporation
#
# SPDX-License-Identifier: Apache 2.0
"""Miscellaneous helpers for MongoDB databases
-------------------------------------------

This helper is used to create an HTTP bridge to a MongoDB database,
since they can't be accessed directly by Javascript.

It does a query for information that the UI Widget Runner
(ttbd/ui/static/js/widget-target-runner.js) can use to display
information about previous runs.

"""
import bisect
import collections
import logging
import os
import re
import urllib.parse

import pymongo

import commonl
import ttbl

def widget_runner_mongo_build_query(
        mongourl: str, dbname: str, collection: str,
        server: str, targetid: str, tc_name: str):
    """Helper for widget runner to query a MondoDB

    :param str mongourl: URL for the database, including the authentication

    :param str dbname: name of the database in the server

    :param str collection: collection's name

    :param str server: server name (for searching records)
    :param str targetid: target name (for searching records)
    :param str tc_name: tc_name (for searching records)

    This call will issue a find in the database for the records that match:

      - server (as a regex)
      - targetid (whole match)
      - tc_name (as a regex)

    This records are in the format done in :mod:`tcfl.report_mongodb`.

    To enable this,


    """
    # let's expand the password if needed
    url = urllib.parse.urlparse(mongourl)
    # If there is no password specified, look in commonl.passwords
    # keyrings that allow us to set passwords by USERNAME@HOSTNAME
    password = url.password
    if not password:
        password = commonl.password_lookup(f"{url.username}@{url.hostname}")
    if password:
        # now possibly expand passwords from the keyrings that are
        # specified as KEYRING:, FILE:, ENVIRONMENT:, etc
        password = ":" + commonl.password_get(url.netloc, url.username, password)
    else:
        password = ""
    # because mongourl specs have three components in the hostname,
    # it's kinda hard to parse in urllib.parse
    #
    # >>> s = "mongodb://user@p1or1mon031.amr.corp.intel.com:7764,p2or1mon031.amr.corp.intel.com:7764,p3or1mon031.amr.corp.intel.com:7764/capi_healthcheck?ssl=true&replicaSet=mongo7764"
    # >>> u = urllib.parse.urlparse(s)
    # >>> u.hostname
    # 'p1or1mon031.amr.corp.intel.com'
    # >>> u
    # ParseResult(scheme='mongodb', netloc='user@p1or1mon031.amr.corp.intel.com:7764,p2or1mon031.amr.corp.intel.com:7764,p3or1mon031.amr.corp.intel.com:7764', path='/capi_healthcheck', params='', query='ssl=true&replicaSet=mongo7764', fragment='')
    #
    # So we wipe off user@ from u.netloc
    netloc = url.netloc[len(url.username) + 1:]

    mongourl_password = \
        f"{url.scheme}://{url.username}{password}@{netloc}" \
        f"{url.path}?{url.query}"

    client = pymongo.MongoClient(mongourl_password)
    db = client[dbname]
    db_collection = db[collection]

    @commonl.lru_cache_disk(
        path = os.path.realpath(
            os.path.join(
                # FIXME: ugh, we need a global for daemon cache path,
                # then this can be moved up outside of here
                # Also, we need this defined here so state_path is defined
                ttbl.test_target.state_path,
                "..", "cache", "ttbd.mongo_get_records"
            )
        ),
        max_age_s = 24 * 60 * 60,	# 24hr forced refresh period
        max_entries = 1024,		# note these can be 30K each
        exclude_exceptions = [ Exception ])
    def _mongo_get_records(mongo_url: str, collection: str, doc_count: int,
                           server: str, targetid: str, tc_name: str):
        conditions = {
            'targets.target.id': targetid,
            'targets.target.server': { '$regex': server, },
            'tc_name': { '$regex': tc_name, },
        }
        projection = [
            "_id",
            "timestamp",
            "result",
            "tc_name",
        ]
        iterator = db_collection.find(conditions,
                                      projection = projection).hint('tc_name')

        # sort by build, so the called doesn't have to do it, since we
        # are bucketing by build anyway to make it easier to render
        # and then cache it
        by_build = collections.defaultdict(list)
        for i in iterator:
            # note these are completely unsorted, so we have to sort'em later
            # _id --looks like YYYYMMDD-HHMM-BUILDNUMBER-HASHID or :HASHID
            _id = i['_id']
            if ":" in _id:	# COMPAT
                _id = _id.replace(":", "-")
            build_id = _id.split("-")[2]
            timestamp = i['timestamp'].timestamp()
            # Convert REPO/PATH/TCNAME##SUBCASE... to SUBCASE;
            # Why? because we are searching for specific stuff for
            # this tc_name only, so it's going to repeat a lot and
            # saves a lot in caching info and storage (10x reduction)
            #
            # *? -> non greedy, so we don't catch
            # path##subcase##subcase##endcase -> endcase, we want
            # subcase##subcase##endcase
            #
            # _id -> we need it to generate URL links to the report,
            # since it contains all the resolution info
            # (RUNID-BUILDID-HASHID)
            tc_name = re.sub("^.*?##", "", i['tc_name'])
            bisect.insort(by_build[build_id],
                          [ timestamp, i['result'], tc_name, _id ])

        # now sort by build number and then for each, sort by the
        # timestamps, then
        by_build_sorted = {}
        ts0 = collections.defaultdict(None)
        for ( build_id, build_data ) in sorted(by_build.items(), reverse = True):
            build_data_sorted = sorted(build_data)
            by_build_sorted[build_id] = build_data_sorted

        # we sort here by timestamp--in Unix format, so it JSONs
        # easily, so they display as expected and are cached alredy;
        # the display option will later bucket them by run ID; note
        # the _id in here is RUNID-BUILD#:HASH and instead
        return by_build_sorted

    # we count how many documents we have; since we only append and we
    # don't modify the database records, this will only change when we add
    # records -- also when we purge, but that won't happen that often
    doc_count = db.command("collstats", collection)['count']
    data = _mongo_get_records(mongourl_password, collection, doc_count,
                              server, targetid, tc_name)
    return data



def widget_runner_flask_mongo_build_query(flask):
    """Helper to export widget_runner_mongo_build_query() from Flask.

    Define as an endpoint in a `server configuration file #:
    <ttbd_configuration>`, with an entry such as:

    >>> import ttbl.mongodb
    >>> @app.route('/mongo_build_query', methods = [ 'GET' ])
    >>> @flask_login.login_required
    >>> def _flask_mongo_build_query():
    >>>     return ttbl.mongodb.widget_runner_flask_mongo_build_query(flask)

    With this, pass a GET request authenticating with the server's
    cookies with the parameters named in
    :func:`widget_runner_mongo_build_query` *URLencoded* (since there will be special chars)

    eg:

    - mongourl: mongourl://USERNAME[:PASSWORD]@HOSTNAME:PORT,HOSTNAME:PORT,HOSTNAMEPORT/DBNAME?ssl=true&replicaSet=<replicavalue>

    - dbname: name of the database
    - collection: name of the collection
    - server: serverid
    - targetid: targetname
    - tc_name: somerepo.git/testcases/test_sometest.py

    Note the MongoURL canuse the password registration facilities
    provided by :func:`commonl.password_lookup` and
    :func:`commonl.password_get`.

    """
    try:
        return flask.jsonify(widget_runner_mongo_build_query(
            urllib.parse.unquote(flask.request.args.get('mongourl')),
            urllib.parse.unquote(flask.request.args.get('dbname')),
            urllib.parse.unquote(flask.request.args.get('collection')),
            urllib.parse.unquote(flask.request.args.get('server')),
            urllib.parse.unquote(flask.request.args.get('targetid')),
            urllib.parse.unquote(flask.request.args.get('tc_name')),
        ))
    except pymongo.errors.OperationFailure as e:
        if e.code == 18:	# can't find a definition; 18 is auth error
            logging.exception("/mongo_build_query: authentication error %s: %s", e.code, e)
            return str(e), 403
        logging.exception("/mongo_build_query: exception code %s: %s", e.code, e)
        return str(e), 500
    except Exception as e:
        logging.exception("/mongo_build_query: exception: %s", e)
        return str(e), 500
