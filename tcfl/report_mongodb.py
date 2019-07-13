#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

# TCF report driver for MongoDB
import codecs
import datetime
import pymongo
import tcfl.tc
import tcfl.report

class report_mongodb_c(tcfl.report.report_c):
    """Report results of testcase execution into a MongoDB database

    The database used is pointed to by MongoDB URL :attr:`url` and
    name :attr:`db_name`.

    **Testcase execution results**

    The results of execution (pass/errr/fail/skip/block) are stored in
    a collection called *results*.

    For each testcase and the targets where it is ran on
    (identified by a *hashid*) we generate a *document*; each
    report done for that this *hashid* is a *record* in said
    document with any attachments stored.

    Each result document is keyed by *runid:hashid* and structured
    as:

    - result:
    - runid:
    - hashid
    - tc_name
    - target_name
    - target_types
    - target_server
    - timestamp
    - targest: dict of keyed by target name

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

    Notes:

    - When a field is missing we don't insert it to save space, it
      has to be considered an empty string (if we expected one) or
      none present

    Usage:

    1. Ensure you have a access to a MongoDB in ``HOST:PORT``,
       where you can create (or there is already) a database called
       ``DATABASENAME``.

    2. Create a TCF configuration file
       ``{/etc/tcf,~,.}/.tcf/conf_mongodb.py`` with:

       .. code-block:: python

          import tcfl.report
          import tcfl.report_mongodb
          m = tcfl.report_mongodb.report_mongodb_c()
          m.url = "mongodb://HOST:PORT" # Or a more complex mongodb URL
          m.db_name = "DATABASENAME"
          m.collection_name = "COLLECTIONNAME"
          # Optional: modify the record before going in
          m.complete_hooks.append(SOMEHOOKFUNCTION)
          tcfl.report.report_c.driver_add(m)

    **Troubleshooting**

    - When giving SSL and passwords in the URL, the connection fails
      with messages such as *ConfigurationError: command SON(...)
      failed: auth failed*

      The installation of PyMongo in your system might be too old, we
      need > v3.

    """
    # FIXME: need a better idea on how to figure out the
    #        revisions, definitely something along the lines of a
    #        dictionary of repositoryies with their URLs, top
    #        levels (relative to where?) and the rev for each; for
    #        example, if I call /usr/share/tcf/examples/xyz.py
    #        that refere to something off $ZEPHYR_BASE, how do I
    #        record the version of xyz.py and the fact that it
    #        sucked off $ZEPHYR_BASE?

    #: MongoDB URL where to connect to
    url = None
    #: MongoDB client extra params, as described in
    #: :class:`pymongo.mongo_client.MongoClient`; this you want to use
    #: to configure SSL, such as:
    #:
    #: .. code-block:: python
    #:
    #:    tcfl.report_mongodb.report_mongodb_c.extra_params = dict(
    #:        ssl_keyfile = PATH_TO_KEY_FILE,
    #:        ssl_certfile = PATH_TO_CERT_FILE,
    #:        ssl_ca_certs = PATH_TO_CA_FILE,
    #:    )
    extra_params = dict()
    #: Name of the database to which to connect
    db_name = None
    #: Name of the collection in the database to fill out
    collection_name = None

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

    complete_hooks = []

    def __init__(self):
        tcfl.report.report_c.__init__(self)
        # Where we keep all the file descriptors to the different
        # files we are writing to based on the code
        self.docs = {}
        self.mongo_client = None
        self.db = None
        self.results = None

    def _report(self, level, alevel, ulevel, _tc, tag, message, attachments):
        """
        Report data to documents in mongodb; we accumulate all the
        data until the completion message and at that point we
        upload to MongoDB.
        """
        # Extreme chitchat we ignore it -- this is mainly the failed
        # to acquire (busy, retrying), which can add to a truckload of
        # messages
        if tag == "INFO" and level >= 6:
            return
        # MongoDB not configured
        if not self.url or not self.db_name:
            return
        # Okie, this is a hack -- don't report on things tagged as this
        if getattr(_tc, "skip_reports", False) == True:
            return	# We don't operate on the global reporter fake TC

        # We don't report on ident-less objects, they don't
        # have enough information for us to record
        if not hasattr(_tc, "_ident"):
            return

        # FIXME: runid should be in tc_c.runid, as well as hashid,
        # instead of having to parse like this -- so they can be
        # extracted as in the block below
        if ':' in _tc._ident:
            runid, hashid = _tc._ident.split(':', 1)
        else:
            runid = ""
            hashid = _tc._ident

        # Extract the target name where this message came from (if the
        # reporter is a target)
        if isinstance(_tc, tcfl.tc.target_c):
            target_name = " @" + _tc.fullid + _tc.bsp_suffix()
            target_server = _tc.rtb.aka
            target_type = _tc.type
            tc_name = _tc.testcase.name
        elif isinstance(_tc, tcfl.tc.tc_c):
            target_name = None
            target_server = None
            target_type = None
            tc_name = _tc.name
        else:
            assert False, "_tc is %s, not tcfl.tc.{tc,target}_c" \
                % type(_tc).__name__

        doc = self.docs.setdefault((runid, hashid, tc_name),
                                   dict(results = [], data = {}))

        # Summarize the current ident by removing the
        # runid:hashid, which is common to the whole report
        # Otherwise we repeat it all the time, and it doesn't make
        # sense because it is at the top level doc[runid] and
        # doc[hashid] plus it's ID in the DB.
        ident = tcfl.msgid_c.ident()
        if ident.startswith(_tc._ident):
            ident = ident[len(_tc._ident):]
        result = dict(
            timestamp = datetime.datetime.utcnow(),
            ident = ident,
            level = level,
            tag = tag,
            message = message if tag != "DATA" else "",
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
            #
            # These must exist, otherwise it is a bug
            #
            # data Domain and name must be valid MongoDB fields, so we
            # replace periods and starting dollar signs with an
            # underscore.
            domain = attachments['domain']
            assert isinstance (domain, basestring), \
                "data domain name '%s' is a %s, need a string" \
                % (domain, type(domain).__name__)
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
            doc['data'][domain][name] = value
        else:
            if attachments:
                result['attachment'] = {}
                for key, attachment in attachments.iteritems():
                    if attachment == None:
                        continue
                    if hasattr(attachment, "name"):
                        # Is it a file? reopen it to read so we don't
                        # modify the original pointer FIXME: kinda
                        # lame, will fail for big files
                        with codecs.open(attachment.name, "r",
                                         encoding = 'utf-8',
                                         errors = 'ignore') as f:
                            # We don't want to report all the file,
                            # just since the last change
                            if not attachment.closed:
                                f.seek(attachment.tell())
                            result['attachment'][key] = f.read()
                    else:
                        result["attachment"][key] = attachment

        doc['results'].append(result)
        del result

        # We file all documents for a RUNID under the same
        # collection
        if message.startswith("COMPLETION"):
            doc['result'] = tag
            self._complete(_tc, runid, hashid, tc_name, doc)
            del self.docs[(runid, hashid, tc_name)]
            del doc

    def _mongo_setup(self):
        # We open a connection each time because it might have
        # been a long time in between and it might have timed out
        self.mongo_client = pymongo.MongoClient(self.url, **self.extra_params)
        self.db = self.mongo_client[self.db_name]
        self.results = self.db[self.collection_name]

    def _complete(self, _tc, runid, hashid, tc_name, doc):
        """
        Deliver to mongodb after adding a few more fields
        """

        doc['runid'] = runid
        doc['hashid'] = hashid
        doc['tc_name'] = tc_name
        doc['timestamp' ] = datetime.datetime.utcnow()
        doc['_id'] = _tc._ident

        doc['target_name'] = _tc.target_group.name \
                             if _tc.target_group else 'n/a'
        if _tc.targets:
            servers = set()		# We don't care about reps in servers
            target_types = []	# Here we want one per target
            doc['targets'] = {}
            # Note this is sorted by target-want-name, the names
            # assigned by the testcase to the targets, so all the
            # types and server lists are sorted by that.
            for tgname in sorted(_tc.targets.keys()):
                target = _tc.targets[tgname]
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
        for tag in _tc._tags:
            (value, _origin) = _tc.tag_get(tag, "", "")
            tags[tag] = str(value)
            if tag == 'components':
                components = value.split()
        doc['tags'] = tags
        doc['components'] = components

        for complete_hook in self.complete_hooks:
            complete_hook(_tc, runid, hashid, tc_name, doc)

        retry_count = 1
        while retry_count <= 3:
            if not self.results:
                self._mongo_setup()
            try:
                # We replace any existing reports for this _id -- if that
                # is not to happen, provide a different runid...
                self.results.find_one_and_replace({ '_id': doc['_id'] },
                                                  doc, upsert = True)
                break
            except pymongo.errors.PyMongoError as e:
                if retry_count <= 3:
                    raise tcfl.tc.blocked_e(
                        "MongoDB error, can't record result: %s" % e)
                else:
                    self.results = None
                    _tc.warning("MongoDB error, reconnecting (%d/3): %s"
                                % (e, retry_count))
