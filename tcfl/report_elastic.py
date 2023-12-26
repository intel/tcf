#! /usr/bin/python3
"""
Report data to Elastic Search
-----------------------------

Simple driver to report each message we receive to an ES database.

Each report is submitted individually, to take advantage of elastic
indexing capabilities, thus, we do not report everything related to a
single testcase as a batch.

This driver uses the :ref:`python3-elasticsearch
<https://elasticsearch-py.readthedocs.io>` package to connect to an
Elastic Search cluster.

**Client setup**

 1. install dependencies::

    $ dnf install -y python3-elasticsearch

 2. Add on any :ref:`TCF configuration file
    <tcf_client_configuration>`:

    >>> tcfl.tc.report_driver_c.add(
    >>>     ttbl.report_elastic.driver(
    >>>         'https://USERNAME:PASSWORD@HOSTNAME:9200',
    >>>          'MYINDEXNAME', verify_certs = False),
    >>>      name = "elasticsearch1")

**Pending**

- Submit asynchronously, through a non-blocking pipe for performance.


**Utils**

- Deleting an index and all its docs from Elastic::

    $ curl http[s]://USERNAME[:PASSWORD]@HOSTNAME:5601/INDEXNAME -X DELETE

"""
import logging
import types

import elasticsearch

import commonl
import tcfl.tc

class driver(tcfl.tc.report_driver_c):
    """
    :param str|list(str) es_hosts: Elastic Search database to connect
      to; this might be one URL or a list of URLs composing
      an Elastic Search cluster.

      >>> es_hosts = 'https://USERNAME:PASSWORD@HOSTNAME:9200'

    :param str index_name: index on which to push the data; if it not
      existant, Elastic Search will auto-create it (all lower case),
      assuming the accounts have permission.

      >>> index_name = 'index1'

    :params: other arguments are passed straight to
      :elasticsearch:`elasticsearch.Elasticsearch` and have to do with
      connection tweaks, maybe certificates, etc.

      >>> verify_certs = False

    """
    def __init__(self, es_hosts, index_name, **es_args):
        assert isinstance(index_name, str), \
            f"index_name: expected str; got {type(index_name)}"
        assert index_name.islower(), \
            f"index_name: expected all lower case [Elastic Search" \
            f" condition]; got '{index_name}'"
        if isinstance(es_hosts, str):
            self.es_hosts = [ es_hosts ]
        else:
            commonl.assert_list_of_strings(es_hosts, "es_hosts", "host")
            self.es_hosts = es_hosts
        tcfl.tc.report_driver_c.__init__(self)
        self.index_name = index_name
        self.es_args = es_args
        self.es = None

    def _connect(self):
        # create/update a connection
        self.es = elasticsearch.Elasticsearch(self.es_hosts, **self.es_args)

    def report(self, testcase, target, tag, ts, delta,
               level, message, alevel, attachments):
        if not self.es:
            self._connect()

        doc = dict(
            timestamp = ts,
            delta = delta,
            # verbosity settings
            level = level,
            alevel = alevel,
            tag = tag,
        )

        if target:
            # We are reporting from an specific target, so fill the field
            doc['target'] = {}
            doc['target']['fullid'] = target.fullid
            doc['target']['id'] = target.id
            doc['target']['server'] = target.server.aka
            doc['target']['type'] = target.type

        doc['tc_name'] = testcase.name
        doc['runid'] = testcase.runid
        doc['hashid'] = testcase.ticket
        doc['ident'] = testcase.ident()

        if testcase.target_group:
            doc['targets'] = {}
            for target_role, target in testcase.target_group.targets.items():
                td = {}
                td['fullid'] = target.fullid
                td['id'] = target.id
                td['server'] = target.server.aka
                td['server_url'] = target.server.url
                td['type'] = target.type
                doc['targets'][target_role] = td

        if tag == "DATA":
            # Since ES will identify attachments and type them, we
            # can't just feed attachments as it is, plus it would be
            # useless, so we report it as data.DOMAIN.NAME=value
            domain = attachments['domain']
            name = attachments['name']
            value = attachments['value']
            if target:
                fullid = target.fullid
            else:
                fullid = "local"
            doc.setdefault('data',  {})\
               .setdefault(domain, {})\
               .setdefault(name, {})[fullid] = value
        else:
            # attachments maybe should be appended after the message,
            # so the types are not overriden?
            doc['message'] = message
            doc['attachments'] = {}
            for name, attachment in attachments.items() if attachments else []:

                # FIXME: that thing after the or is a horrible
                # hack; see why in the comment to
                # commonl.ast_expr(), which has the same horrible
                # hack.
                if isinstance(attachment, commonl.generator_factory_c) \
                   or "commonl.generator_factory_c'" in repr(attachment.__class__):
                    for data in attachment.make_generator():
                        if isinstance(data, bytes):
                            data = data.decode('utf-8')
                        if not name in doc['attachments']:
                            doc['attachments'][name] = data
                        else:
                            doc['attachments'][name] += data
                elif isinstance(attachment, Exception):
                    doc["attachments"][name] = str(attachment)
                elif isinstance(attachment, types.GeneratorType):
                    doc["attachments"][name] = ""
                    for data in attachment:
                        # FIXME: this is assuming the attachment is a string...
                        doc['attachments'][name] += data
                else:
                    doc['attachments'][name] = attachment

        try:
            # submit; see note about batching on top level
            self.es.index(index = self.index_name, body = doc)
        except elasticsearch.exceptions.ElasticsearchException as e:
            logging.error("can't push record to Elastic: %s", e)
            # just log it and keep going, so we don't hold a hold run
            # while we find all these issues
            #raise
