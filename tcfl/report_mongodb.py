#! /usr/bin/python2
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
import os
import types

import pymongo

import commonl
import tcfl
import tc

class driver(tc.report_driver_c):
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
        assert isinstance(url, basestring)
        assert isinstance(db_name, basestring)
        assert isinstance(collection_name, basestring)
        assert extra_params == None or isinstance(extra_params, dict)

        tc.report_driver_c.__init__(self)
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
        #: :param tc.tc_c _tc: testcase object
        #: :param str runid: current TC's runid
        #: :param str hashid: current TC's hashid
        #: :param str tc_name: current testcase name
        #: :param dict doc: current document that will be inserted into
        #:   the database; the hook function can add fields, but it is not
        #:   recommended modifying existing fields.
        self.complete_hooks = []


    def report(self, reporter, tag, ts, delta,
               level, message,
               alevel, attachments):
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
        if reporter == tc.tc_global:
            return

        runid = reporter.kws.get('runid', None)
        hashid = reporter.kws.get('tc_hash', None)
        if not hashid:	            # can't do much if we don't have this
            return

        # Extract the target name where this message came from (if the
        # reporter is a target)
        if isinstance(reporter, tc.target_c):
            target_name = " @" + reporter.fullid + reporter.bsp_suffix()
            target_server = reporter.rtb.aka
            target_type = reporter.type
            tc_name = reporter.testcase.name
        elif isinstance(reporter, tc.tc_c):
            target_name = None
            target_server = None
            target_type = None
            tc_name = reporter.name
        else:
            raise AssertionError(
                "reporter is not tc.{tc,target}_c but %s" % type(reporter))

        doc = self.docs.setdefault((runid, hashid, tc_name),
                                   dict(results = [], data = {}))

        # Summarize the current ident by removing the
        # runid:hashid, which is common to the whole report
        # Otherwise we repeat it all the time, and it doesn't make
        # sense because it is at the top level doc[runid] and
        # doc[hashid] plus it's ID in the DB.
        ident = self.ident_simplify(tcfl.msgid_c.ident(), runid, hashid)
        result = dict(
            timestamp = datetime.datetime.utcnow(),
            ident = ident,
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
            assert isinstance (domain, basestring), \
                "data domain name '%s' is a %s, need a string" \
                % (domain, type(domain).__name__)
            # clean up field (domain.name=value), can't have ., $ on start
            # as *domain* and *name* are being used as MongoDB fields,
            # thus must be valid field names.
            domain = domain.replace(".", "_")
            if domain.startswith("$"):
                domain = domain.replace("$", "_", 1)
            name = attachments['name']
            assert isinstance (domain, basestring), \
                "data name '%s' is a %s, need a string" \
                % (name, type(name).__name__)
            name = name.replace(".", "_")
            if name.startswith("$"):
                name = name.replace("$", "_", 1)
            value = attachments['value']
            doc['data'].setdefault(domain, {})
            if isinstance(value, basestring):
                # MongoDB doesn't like bad UTF8, so filter a wee bit
                value = commonl.mkutf8(value)
            doc['data'][domain][name] = value
        elif attachments:
            result['attachment'] = {}
            for key, attachment in attachments.iteritems():
                if attachment == None:
                    continue
                if isinstance(attachment, commonl.generator_factory_c):
                    for data in attachment.make_generator():
                        if not key in result["attachment"]:
                            result["attachment"][key] = data
                        else:
                            result["attachment"][key] += data
                elif isinstance(attachment, types.GeneratorType):
                    result["attachment"][key] = ""
                    for data in attachment:
                        # FIXME: this is assuming the attachment is a string...
                        result["attachment"][key] += data
                elif isinstance(attachment, basestring):
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

        doc['results'].append(result)
        del result

        # We file all documents for a RUNID under the same
        # collection
        if message.startswith("COMPLETION"):
            doc['result'] = tag
            self._complete(reporter, runid, hashid, tc_name, doc)
            del self.docs[(runid, hashid, tc_name)]
            del doc

    def _mongo_setup(self):
        # We open a connection each time because it might have
        # been a long time in between and it might have timed out
        self.mongo_client = pymongo.MongoClient(self.url, **self.extra_params)
        self.db = self.mongo_client[self.db_name]
        self.results = self.db[self.collection_name]
        self.made_in_pid = os.getpid()

    def _complete(self, reporter, runid, hashid, tc_name, doc):
        # Deliver to mongodb after adding a few more fields

        doc['runid'] = runid
        doc['hashid'] = hashid
        doc['tc_name'] = tc_name
        doc['timestamp' ] = datetime.datetime.utcnow()
        if runid:
            doc['_id'] = runid + ":" + hashid
        else:
            doc['_id'] = hashid

        doc['target_name'] = reporter.target_group.name \
                             if reporter.target_group else 'n/a'
        if reporter.targets:
            servers = set()		# We don't care about reps in servers
            target_types = []	# Here we want one per target
            doc['targets'] = {}
            # Note this is sorted by target-want-name, the names
            # assigned by the testcase to the targets, so all the
            # types and server lists are sorted by that.
            for tgname in sorted(reporter.targets.keys()):
                target = reporter.targets[tgname]
                doc['targets'][tgname] = dict(
                    server = target.rtb.aka, id = target.id,
                    type = target.type, bsp_model = target.bsp_model)
                servers.add(target.rtb.aka)
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
        for tag in reporter._tags:
            (value, _origin) = reporter.tag_get(tag, "", "")
            tags[tag] = str(value)
            if tag == 'components':
                components = value.split()
        doc['tags'] = tags
        doc['components'] = components

        for complete_hook in self.complete_hooks:
            complete_hook(_tc, runid, hashid, tc_name, doc)

        retry_count = 1
        while retry_count <= 3:
            if not self.results or self.made_in_pid != os.getpid():
                self._mongo_setup()
            try:
                # We replace any existing reports for this _id -- if that
                # is not to happen, provide a different runid...
                self.results.find_one_and_replace({ '_id': doc['_id'] },
                                                  doc, upsert = True)
                break
            except pymongo.errors.PyMongoError as e:
                if retry_count <= 3:
                    raise tc.blocked_e(
                        "MongoDB error, can't record result: %s" % e)
                else:
                    self.results = None
                    reporter.warning("MongoDB error, reconnecting (%d/3): %s"
                                     % (e, retry_count))

# backwards compat	# COMPAT
report_mongodb_c = driver
