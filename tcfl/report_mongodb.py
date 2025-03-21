#! /usr/bin/python3
#
# Copyright (c) 2017-20 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""Report data to a MongoDB database
---------------------------------

This driver dumps all reported data to a MongoDB database, creating
one document per testcase.

Each document is a dictionary hierarchy of which includes summary data
and detailed messages and attachments.

See :class:`tcfl.report_mongodb.driver <driver>` for configuration
details.

The execution messages (pass/errr/fail/skip/block) are stored in a
subdocument called *results*. Data reports in a subdocument called
*data*.

For each testcase and the targets where it is ran on (identified by a
*hashid*) we generate a *document*; each report done for that this
*hashid* is a *record* in said document with any attachments stored.

Testcase execution results
^^^^^^^^^^^^^^^^^^^^^^^^^^

Each result document is keyed by *runid:hashid* and structured
as:

- result
- runid
- hashid
- tc_name
- target_name
- target_types
- target_server
- timestamp
- targets: dict of keyed by target name

  - TARGETNAME:

    - id
    - server
    - type
    - bsp_model

- results: list of

  - timestamp
  - ident
  - level
  - tag
  - message
  - attachments

- data: dictionary of data domain, name and value

Notes:

- When a field is missing we don't insert it to save space, it
  has to be considered an empty string (if we expected one) or
  none present


Troubleshooting
^^^^^^^^^^^^^^^

- When giving SSL and passwords in the URL, the connection fails
  with messages such as *ConfigurationError: command SON(...)
  failed: auth failed*

  The installation of PyMongo in your system might be too old, we
  need > v3.

Pending
^^^^^^^

- when told to store an attachment PyMongo can't take, it is just
  throwing an exception--we shall convert that to something so the
  document is not lost
"""

import codecs
import datetime
import logging
import os
import types
import urllib.parse

import pymongo

import commonl
import tcfl
import tcfl.tc

class driver(tcfl.tc.report_driver_c):
    """
    Report results of testcase execution into a MongoDB database

    The records are written to a database pointed to by MongoDB URL :attr:`url`,
    database name :attr:`db_name`, collection :attr:`collection_name`.

    **Usage**

    1. Ensure you have a access to a MongoDB in ``HOST:PORT``,
       where you can create (or there is already) a database called
       ``DATABASENAME``.

    2. Create a TCF configuration file
       ``{/etc/tcf,~,.}/.tcf/conf_mongodb.py`` with:

       .. code-block:: python

          import tcfl.report_mongodb
          m = tcfl.report_mongodb.driver(
              url = "mongodb://HOST:PORT", # Or a more complex mongodb URL
              db_name = "DATABASENAME",
              collection_name = "COLLECTIONNAME"
          )
          # Optional: modify the record before going in
          m.complete_hooks.append(SOMEHOOKFUNCTION)
          tcfl.tc.report_driver_c.driver_add(m)

    :param str url: MongoDB URL where to connect to

    :param str db_name: name of the database to which to connect

    :param str collection_name: name of the collection in the database
      to fill out

    :param dict extra_params: MongoDB client extra params, as described in
       :class:`pymongo.mongo_client.MongoClient`; this you want to use
       to configure SSL, such as:

       .. code-block:: python

          tcfl.report_mongodb.report_mongodb_c.extra_params = dict(
              ssl_keyfile = PATH_TO_KEY_FILE,
              ssl_certfile = PATH_TO_CERT_FILE,
              ssl_ca_certs = PATH_TO_CA_FILE,
          )
    """
    def __init__(self, url, db_name, collection_name, extra_params = None):
        assert isinstance(url, str)
        assert isinstance(db_name, str)
        assert isinstance(collection_name, str)
        assert extra_params == None or isinstance(extra_params, dict)

        tcfl.tc.report_driver_c.__init__(self)
        # Where we keep all the file descriptors to the different
        # files we are writing to based on the code
        self.docs = {}
        self.mongo_client = None
        self.db = None
        self.results = None
        # It might happen dep on the version of pymongo that we get
        # this if we pass the data structure over forks and then it
        # doesn't work:
        #
        #   /usr/lib64/python2.7/site-packages/pymongo/topology.py:149:
        #     UserWarning: MongoClient opened before fork. Create
        #     MongoClient only after forking. See PyMongo's documentation
        #     for details:
        #     http://api.mongodb.org/python/current/faq.html#is-pymongo-fork-safe
        #
        #   "MongoClient opened before fork. Create MongoClient only "
        #
        # So we record on _mongo_setup() what was the PID we used to
        # create it and when we recheck if we have to call
        # _mongo_setup() again, we also do it if we are in a different PID.
        self.made_in_pid = None

        #: URL for the databsae
        self.url = url
        #: Name of the database in :attr:url
        self.db_name = db_name
        #: Name of the collection in :attr:url and :attr:db_name
        self.collection_name = collection_name
        self.extra_params = extra_params if extra_params else dict()

        #: List of functions to run when a document is completed before
        #: uploading to MongoDB; each is passed the arguments:
        #:
        #: :param tcfl.tc.tc_c _tc: testcase object
        #: :param str runid: current TC's runid
        #: :param str hashid: current TC's hashid
        #: :param str tc_name: current testcase name
        #: :param dict doc: current document that will be inserted into
        #:   the database; the hook function can add fields, but it is not
        #:   recommended modifying existing fields.
        self.complete_hooks = []

    #: Maximum size of a console attachment
    #:
    #: If set to a positive number, any attachment with *console* in
    #: the name and of type *bytes* or *str* will be capped at that
    #: maximum size and another attachment with a message about it
    #: will be added.
    console_max_size = 0

    def report(self, testcase, target, tag, ts, delta,
               level, message, alevel, attachments):
        """
        Collect data to report to a MongoDB record

        We accumulate all the data until the completion message and at
        that point we upload to MongoDB.
        """
        # Extreme chitchat we ignore it -- this is mainly the failed
        # to acquire (busy, retrying), which can add to a truckload of
        # messages
        if tag == "INFO" and level >= 6:
            return
        # skip global reporter, not meant to be used here
        if testcase == tcfl.tc.tc_global:
            return

        runid = testcase.kws.get('runid', None)
        hashid = testcase.kws.get('tc_hash', None)
        if not hashid:	            # can't do much if we don't have this
            return

        # Extract the target name where this message came from (if the
        # reporter is a target)
        tc_name = testcase.name
        if target:
            fullid = target.fullid
            target_name = " @" + target.fullid
            target_server = target.server.aka
            target_type = target.type
        else:
            fullid = None
            target_name = None
            target_server = None
            target_type = None

        doc = self.docs.setdefault((runid, hashid, tc_name),
                                   dict(results = [], data = {}))

        result = dict(
            timestamp = datetime.datetime.utcnow(),
            ident = testcase.ident(),
            level = level,
            tag = tag,
            # MongoDB doesn't like bad UTF8, so filter a wee bit
            message = commonl.mkutf8(message) if tag != "DATA" else "",
        )
        if target_name:
            result["target_name"] = target_name
        if target_server:
            result["target_server"] = target_server
        if target_type:
            result["target_type"] = target_type

        if tag == "DATA":
            # We store data attachments in a different place, so it is
            # easier to get to them.
            domain = attachments['domain']
            assert isinstance (domain, str), \
                "data domain name '%s' is a %s, need a string" \
                % (domain, type(domain).__name__)
            # clean up field (domain.name=value), can't have ., $ on start
            # as *domain* and *name* are being used as MongoDB fields,
            # thus must be valid field names.
            domain = domain.replace(".", "_")
            if domain.startswith("$"):
                domain = domain.replace("$", "_", 1)
            name = attachments['name']
            assert isinstance (domain, str), \
                "data name '%s' is a %s, need a string" \
                % (name, type(name).__name__)
            name = name.replace(".", "_")
            if name.startswith("$"):
                name = name.replace("$", "_", 1)
            value = attachments['value']
            # there are  scripts that depend on this, thus keep both
            doc.setdefault('data', {})
            doc['data'].setdefault(domain, {})
            doc.setdefault('data-v2', {})
            doc['data-v2'].setdefault(domain, {})
            if isinstance(value, str):
                # MongoDB doesn't like bad UTF8, so filter a wee bit
                value = commonl.mkutf8(value)
            doc['data'][domain][name] = value
            doc['data-v2'][domain].setdefault(name, {})
            if target:
                doc['data-v2'][domain][name][fullid] = value
            else:
                doc['data-v2'][domain][name]["local"] = value
        else:
            if attachments:
                result['attachment'] = {}
                for key_raw, attachment in attachments.items():
                    if attachment == None:
                        continue
                    # MongoDB uses periods (.) as subdictionary
                    # separator, plus also disallowing other chars as
                    # record names; escape them to avoid issues.
                    # Now quote() doesn't make it easy to add '.' as a
                    # char to escape...ugh
                    key = urllib.parse.quote(key_raw).replace(".", "%2E")
                    # FIXME: that thing after the or is a horrible
                    # hack; see why in the comment to
                    # commonl.ast_expr(), which has the same horrible
                    # hack.
                    if isinstance(attachment, commonl.generator_factory_c) \
                       or "commonl.generator_factory_c'" in repr(attachment.__class__):
                        for data in attachment.make_generator():
                            if isinstance(data, bytes):
                                data = data.decode('utf-8')
                            if not key in result["attachment"]:
                                result["attachment"][key] = data
                            else:
                                result["attachment"][key] += data
                    elif isinstance(attachment, types.GeneratorType):
                        result["attachment"][key] = ""
                        for data in attachment:
                            # FIXME: this is assuming the attachment is a string...
                            result["attachment"][key] += data
                    elif isinstance(attachment, str):
                        # MongoDB doesn't like bad UTF8, so filter a wee bit
                        result["attachment"][key] = commonl.mkutf8(attachment)
                    elif isinstance(attachment, Exception):
                        # We can't really encode everyhing, so we'll take
                        # the message and be done
                        result["attachment"][key] = str(attachment)
                    elif isinstance(attachment, tcfl.tc.target_c):
                        result["attachment"][key] = attachment.fullid
                    else:
                        result["attachment"][key] = attachment

                    # do we need to cap console attachments?
                    if 'console' in key and self.console_max_size > 0:
                        # cap maximum size of any console looking
                        # attachment; we cap to the beginning only,
                        # because we want to see what happened and
                        # lead us to a lot of console
                        if not isinstance(attachment, ( str, bytes )):
                            continue
                        result["attachment"][key + "-WARNING"] = \
                            "attachment capped from %d to %d" \
                            % (len(attachment), self.console_max_size)
                        result["attachment"][key] = \
                            attachment[:self.console_max_size]


        doc['results'].append(result)
        del result

        # We file all documents for a RUNID under the same
        # collection
        if message.startswith("COMPLETION"):
            doc['result'] = tag
            self._complete(testcase, runid, hashid, tc_name, doc)
            del self.docs[(runid, hashid, tc_name)]
            del doc

    def _mongo_setup(self):
        # We open a connection each time because it might have
        # been a long time in between and it might have timed out
        self.mongo_client = pymongo.MongoClient(self.url, **self.extra_params)
        self.db = self.mongo_client[self.db_name]
        self.results = self.db[self.collection_name]
        self.made_in_pid = os.getpid()

    def _complete(self, testcase, runid, hashid, tc_name, doc):
        # Deliver to mongodb after adding a few more fields

        doc['runid'] = runid
        doc['hashid'] = hashid
        doc['tc_name'] = tc_name
        doc['timestamp' ] = datetime.datetime.utcnow()
        if runid:
            doc['_id'] = runid + tcfl.tc.report_runid_hashid_separator + hashid
        else:
            doc['_id'] = hashid

        doc['target_name'] = testcase.target_group.name \
                             if testcase.target_group else 'n/a'
        if testcase.targets:
            servers = set()		# We don't care about reps in servers
            target_types = []	# Here we want one per target
            doc['targets'] = {}
            # Note this is sorted by target-want-name, the names
            # assigned by the testcase to the targets, so all the
            # types and server lists are sorted by that.
            for tgname in sorted(testcase.targets.keys()):
                target = testcase.targets[tgname]
                doc['targets'][tgname] = dict(
                    server = target.server.aka, id = target.id,
                    type = target.type, bsp_model = target.bsp_model)
                servers.add(target.server.aka)
                if len(target.rt.get('bsp_models', {})) > 1:
                    target_types.append(target.type + ":" + target.bsp_model)
                else:
                    target_types.append(target.type)
            doc['target_types'] = ",".join(target_types)
            doc['target_servers'] = ",".join(servers)
        else:
            doc['target_types'] = 'static'
            doc['target_servers'] = 'static'

        tags = {}
        components = []
        for tag in testcase._tags:
            (value, _origin) = testcase.tag_get(tag, "", "")
            tags[tag] = str(value)
            if tag == 'components':
                components = value.split()
        doc['tags'] = tags
        doc['components'] = components

        for complete_hook in self.complete_hooks:
            complete_hook(_tc, runid, hashid, tc_name, doc)

        # FIXME: update summaries
            
        retry_count = 1
        while retry_count <= 3:
            if self.results == None or self.made_in_pid != os.getpid():
                self._mongo_setup()
            try:
                # We replace any existing reports for this _id -- if that
                # is not to happen, provide a different runid...
                self.results.find_one_and_replace({ '_id': doc['_id'] },
                                                  doc, upsert = True)
                break
            except Exception as e:
                # broad exception, could be almost anything, but we
                # don't really know what PyMongo can't throw at us
                # (pymongo.errors, bson errors...the lot)
                if retry_count > 3:
                    testcase.log.error(
                        f"{tc_name}:{hashid}: MongoDB error: {str(e)}")
                    break
                else:
                    retry_count += 1
                    self.results = None
                    testcase.log.warning(
                        f"{tc_name}:{hashid}: MongoDB error, retrying"
                        " ({retry_count}/3): {str(e)}")

# backwards compat	# COMPAT
report_mongodb_c = driver
