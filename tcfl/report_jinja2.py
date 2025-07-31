#! /usr/bin/python3
#
# Copyright (c) 2017-20 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""Create reports using Jinja2 templates
-------------------------------------

:class:`tcfl.report_jinja2.driver` generates reports to files for
human or machine consumption using the Jinja2 templating to gather
templates and fill them out with information, so it can create text,
HTML, Junit XML, etc...

This driver saves log messages to separate temporary files based on
their :term:`hashid` (which is unique to each testcase running
separately on a thread). When it detects a *COMPLETION* message (a top
level conclussion), it will generate the report for each configured
template, using data from the testcase metadata and the output it
saved to those separate files.

The default configuraton (the *text* template) will generate files
called ``report-[RUNID:]HASHID.txt`` files for each
error/failure/blockage.

To enable it for passed or skipped test cases, add to any :ref:`TCF
configuration file <tcf_client_configuration>`:

>>> tcfl.report_jinja2.driver.templates['text']['report_pass'] = True
>>> tcfl.report_jinja2.driver.templates['text']['report_skip'] = True

The junit template (disabled by default) will generate
``junit-[RUNID:]HASHID.xml`` files with information from all the
testcases executed based on the configuration settings below.

To enable it for all conditions (or disable any replacing *True* with
*False*), add to any :ref:`TCF configuration file
<tcf_client_configuration>`:

>>> tcfl.report_jinja2.driver.templates['junit']['report_pass'] = True
>>> tcfl.report_jinja2.driver.templates['junit']['report_skip'] = True
>>> tcfl.report_jinja2.driver.templates['junit']['report_error'] = True
>>> tcfl.report_jinja2.driver.templates['junit']['report_fail'] = True
>>> tcfl.report_jinja2.driver.templates['junit']['report_block'] = True

See :data:`driver.templates` for more information.

Limitations:

- FIXME: only produces output at the end (not realtime); this due to
  some fields being only available at the end (eg counts, etc). Change
  to a two pass system, where the the file is generated as data comes
  out, unresolved fields left as fields and then a second pass during
  COMPLETION resolves the missing fields.

"""
import io
import logging
import os
import sys
import threading
import time
import datetime
import pytz

import functools
import jinja2
import jinja2.filters

import commonl
import tcfl
from . import config
from . import tc

def jinja2_xml_escape(data):
    """
    Lame filter to XML-escape any characters that are allowed in XML
    according to https://www.w3.org/TR/xml/#charsets

    That'd be:

    #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]

    The rest need to be escaped as &#HHHH;
    """
    # run also the HTML scaper, as it does the rest (<>&, etc...)
    _data = jinja2.filters.do_forceescape(data)
    new = type(_data)()
    for c in data:
        point = ord(c)
        if point in [ 0x9, 0xa, 0xd ] \
           or (point >= 0x20 and point < 0xfffd) \
           or (point >= 0x10000 and point < 0x10ffff):
            #print "char %s VALID point %x" % (c, point)
            new += c
        else:
            #print "char %s INVALID point %x" % (c, point)
            new += type(data)("&#%x;" % point)
    # run also the HTML scaper, as it does the rest (<>&, etc...)
    return new


class driver(tc.report_driver_c):

    # timezone the reports will have. You can set it in various ways:
    # you can set it as an enviorment variable named REPORT_TZ or TZ.
    # If you dont want to change your enviorment variables, you can set it
    # like:
    # tcfl.report_jinja2.driver.timezone = 'US/Pacific'
    # in your tcf config directory (it's probably under your home directory
    # ~/.tcf) you can add the variable to any file there named conf*, or
    # create a new one yourself.
    # NOTE: you need to write the time zone in (Canonical) names NOT in
    # abbreviations.
    timezone = os.environ.get('REPORT_TZ', os.environ.get('TZ', None))

    def __init__(self, log_dir, timezone = None):
        """
        Initialize the Jinja2 templating driver

        :params str log_dir: directory where to write reports
        """
        assert isinstance(log_dir, str)
        assert isinstance(self.templates, dict)
        assert all([ isinstance(template, dict)
                     for template in self.templates.values() ])

        tc.report_driver_c.__init__(self)
        # Where we write the final reports
        self.log_dir = log_dir
        # dictionary where we store the names of the temporary files
        # where we are writing the log entries while the testcase
        # executes; we don't keep them open since we'd exhaust the
        # open file descriptor count really quick.
        self.fs = {}
        # thread local storage for TLS-based prefix formatting
        self.tls = threading.local()
        if timezone:
            assert isinstance(timezone, str)
            self.timezone = timezone
        if not self.timezone:
            self.timezone = os.environ.get(
                'REPORT_TZ', os.environ.get('TZ', None))


    #:
    #: To create more templates, add a new dictionary:
    #:
    #: >>> tcfl.report_jinja2.driver.templates['MYTEMPLATE'] = dict(
    #: >>>     name = 'report.j2.txt',
    #: >>>     output_file_name = 'report-%(runid)s:%(tc_hash)s.txt',
    #: >>>     report_pass = False,
    #: >>>     report_skip = False,
    #: >>>     report_error = True,
    #: >>>     report_fail = True,
    #: >>>     report_block = True
    #: >>> )
    #:
    #: - 'name`` (str): name of a Jinja2 template file available on ``.tcf``,
    #:   ``~/.tcf``, ``/etc/tcf`` or ``/usr/share/tcf/`` (this is the
    #:   configuration path and will change if it has other configuration
    #:   prefix FIXME: reference).
    #:
    #: - ``output_file_name`` (str): Pyhton template that defines the name
    #:   of the output file. The fields are the :ref:`testcase keywords
    #:   <finding_testcase_metadata>` and those described below for
    #:   templates.
    #:
    #: - ``report_pass`` (bool): report (or not) if the testcase passes
    #: - ``report_fail`` (bool): report (or not) if the testcase fails
    #: - ``report_error`` (bool): report (or not) if the testcase errors
    #: - ``report_block`` (bool): report (or not) if the testcase blocks
    #: - ``report_skip`` (bool): report (or not) if the testcase skips
    #:
    #: *Creating templates*
    #:
    #: The `Jinja2 templating
    #: <http://jinja.pocoo.org/docs/2.10/templates/>`_ mechanism allows
    #: for extensions to create any kind of file you might need.
    #:
    #: To create templates, as described above, define a dictionary that
    #: describes it and create a template file.
    #:
    #: To quickly change the existing ones, you can use Jinja2 template
    #: inheriting; for example, the default ``report.j2.txt``::
    #:
    #:   {% extends "report-base.j2.txt" %}
    #:
    #: which uses all the default settings in ``report-base.j2.txt`` and
    #: can use things like block replacing to add more information::
    #:
    #:   {% extends "report-base.j2.txt" %}
    #:   {%- block HEADER_PREFIX -%}
    #:   Add some more information here that will end up in the final
    #:   report.
    #:   {%- endblock -%}
    #:
    #: Jinja2 will replace that in the final report in the placeholder
    #: for ``{%= block HEADER_PREFIX -%}``.
    #:
    #: Fields available (to be used as Jinja2 variables with ``{{ FIELD
    #: }}`` and other Jinja2 operators:
    #:
    #: - Any :ref:`testcase keywords <finding_testcase_metadata>`
    #:
    #: - *{{ msg_tag }}*: testcase's result (``PASS``,
    #:   ``FAIL``, ``ERRR``, ``SKIP``, ``BLCK``), also as ``{{ result }}``
    #:   and ``{{ result_past }}`` formatted for text in present and past
    #:   tense (eg: *pass* vs *passed*)
    #:
    #: - *{{ message }}*: message that came with the top level report
    #:   (``COMPLETION passed|failed|error|failed|skip|block``)
    #:
    #: - any variable defined in the the ``tcfl.config`` space is
    #:   mapped to ``tcfl_config_``; for example *{{
    #:   tcfl_config_urls }}* which maps to :data:`tcfl.config.urls`
    #:
    #:   Only variables of the following types are exported: integers,
    #:   strings, lists, dictionaries and tuples.
    #:
    #: - *{{ t_option }}* a value that indicates what has to be given to
    #:   *tcf* to select the targets where the testcase was run.
    #:
    #: - *{{ log }}*: an iterator to the contents of log files that
    #:   returns three fields:
    #:   - message identifier
    #:   - target group name
    #:   - message itself
    #:
    #:   Can be used as::
    #:
    #:     {% for ident, tgname, message in log -%}
    #:     {{ "%-10s %-25s %s" | format(ident, tgname, message) }}
    #:     {% endfor %}
    #:
    #:   Depending on the destination format, you can pipe this
    #:   through Jinja2 `filters
    #:   <http://jinja.pocoo.org/docs/2.10/templates/#filters>`_ to
    #:   escape certain characters. For example, there is:
    #:
    #:   - :func:`escape <jinja2.escape>` which escapes suitable for HTML
    #:
    #:   - :func:`xml_escape <jinja2_xml_escape>` which escapes
    #:     suitable for XML
    #:
    #:   which can be used as::
    #:
    #:     {% for ident, tgname, message in log -%}
    #:     {{ "%-10s %-25s %s" | format(ident, tgname, message) | xml_escape }}
    #:     {% endfor %}
    #:
    #: - *{{ targets }}*: list of targets used for the testcases, with
    #:   fields:
    #:
    #:   - ``want_name`` (str): name the testcase gave to this target
    #:     (e.g.: *target*)
    #:
    #:   - ``fullid`` (str): name of the actual target at the server
    #:     (e.g.: *SERVERNAME/qz43i-x86*)
    #:
    #:   - ``type`` (str): type of the target (e.g.: *qemu-linux-XYZ*)
    #:
    #: *Extending and modifying keywords*
    #:
    #: :data:`Hook <hooks>` functions can be configured to execute
    #: before the testcase is launched, they can be used to extend the
    #: keywords available to the templates or any other things.
    templates = {
        "html" : dict(
            name = 'report.j2.html',
            output_file_name = '%(report_file_prefix)shtml',
            report_pass = False,
            report_skip = False,
            report_error = False,
            report_fail = False,
            report_block = False,
        ),
        "text" : dict(
            name = 'report.j2.txt',
            output_file_name = '%(report_file_prefix)stxt',
            report_pass = False,
            report_skip = False,
            report_error = True,
            report_fail = True,
            report_block = True,
        ),
        "junit" : dict(
            name = 'junit.j2.xml',
            output_file_name = '%(report_file_prefix)sxml',
            report_pass = False,
            report_skip = False,
            report_error = False,
            report_fail = False,
            report_block = False,
        )
    }

    #: List of hook functions to call before generating a report
    #:
    #: For example::
    #:
    #:    def my_hook(obj, testcase, kws):
    #:        assert isinstance(obj, tcfl.report_jinja2.driver)
    #:        assert isinstance(testcase, tc.tc_c)
    #:        assert isinstance(kws, dict)
    #:        kws['some new keyword'] = SOMEVALUE
    #:
    #:    tcfl.report_jinja2.driver.hooks.append(my_hook)
    #:
    #: Note these is done for all the templates; do not use global
    #: variables, as these function might be called from multiple
    #: threads.
    hooks = []

    @functools.lru_cache(maxsize = 200)
    def _get_fd(self, code, tmpdir):
        # FIXME: document the decorator
        if not code in self.fs:
            # open truncating because this is a new entry
            f = io.open(
                os.path.join(tmpdir, "report-" + code + ".txt"),
                "wb")
            self.fs[code] = f.name
        else:
            f = io.open(self.fs[code], "a+b")
        # reassign the stream so we use the prefix printing
        # capabilities
        return commonl.io_tls_prefix_lines_c(
            self.tls, f.detach())

    def _log_iterator(self, code):
        # Read the temporary log file
        #
        # This is called by the Jinja2 rendering engine, line per
        # line, as it is rendering stuff. We will filter some lines we
        # don't care for.
        #
        # FIXME: maybe this should just pickle tuples and be done
        with io.open(self.fs[code], "r", encoding = 'utf-8', errors = 'replace') as fi:
            for line in fi:
                if line == "":
                    break
                # escape any that doesn't render clearly
                # so we don't miss anything
                line = line.rstrip()
                if line == "":	# Note this might be we read a "^M" (\r)
                    continue
                token = line.split(None, 4)
                # Tokens are TAG LEVEL IDENT TGNAME MESSAGE
                if not token or len(token) < 3:
                    continue
                tag = token[0]
                level_s = token[1]
                ident = token[2]
                if not tag in [ "DATA", "INFO", "PASS", "ERRR",
                                "FAIL", "SKIP", "BLCK" ]:
                    continue
                if len(token) == 3:
                    # Bad line, ignore it
                    continue
                if len(token) > 3:
                    tgname = token[3]
                else:
                    tgname = "BUG:tgname-MISSING"
                    logging.error("BUG: missing tgname in line: %s", line)
                if len(token) > 4:
                    message = token[4]
                    # if a leading \x01\x01, this means these lines
                    # are attachments and we want to format them indented
                    if message.startswith("\x01\x01"):
                        message = "  " + message[2:]
                else:
                    logging.error("BUG: missing message in line: %s", line)
                    message = "BUG:message-MISSING"
                try:
                    level = int(level_s)
                except ValueError:
                    logging.error("BUG: bad level in line: %s", line)
                    level = 0
                if ident == "<snip>":
                    # This is just so it aligns well; <snip> comes from
                    # _report() above.
                    ident = "   "
                # in Jinja2 templates, you can use the escape() or e()
                # filter to automatically escape anything that might
                # not be *ML kosher...but 0x00. So as we only need
                # this for reporting, we'll make an ugly exception.
                # the *log* field in the template generator expands
                # for each line on a tuple ident, targetname, message,
                # which are these -- then for example it is consumed
                # by tcf.git/report-base.j2.txt [execution log
                # section] which is loaded by _mkreport()
                # below.
                yield ident, tgname, commonl.str_invisible_escape(message)

    def _mkreport(self, msg_tag, code, _tc, message):
        #
        # The testcase is complete, render the templates from the
        # temporary collected log file.
        #

        #
        # Generate a dictionary of fields we can use in the templates
        # and the values they will be replaced with
        #
        # FIXME: move this to report_driver_c, as others might want to
        # use it

        # FIXME: initialize this in the core, so it shows in test_dump_kws*.py
        kws = commonl.dict_missing_c(_tc.kws)
        kws['msg_tag'] = msg_tag
        kws['result'] = tc.valid_results.get(
            msg_tag, ( None, "BUG-RESULT-%s" % msg_tag))[0]
        kws['result_past'] = tc.valid_results.get(
            msg_tag, ( None, "BUG-RESULT-%s" % msg_tag))[1]
        kws['message'] = message

        # target filter ids, to print a message that says which -t
        # option has to be given to "tcf run" to run this report.
        # FIXME: move to common infra in
        # report_driver_c.mk_t_option()
        tfids = []
        for target_want_name, target in _tc.targets.items():
            if len(target.rt.get('bsp_models', {})) > 1:
                tfids.append(
                    '(' + target.fullid
                    + ' and bsp_model == "%s")' % target.bsp_model)
            else:
                tfids.append(target.fullid)
        if tfids:
            kws['t_option'] = " -t '" + " or ".join(tfids) + "'"
        else:
            kws['t_option'] = ""

        # tcfl.config.VARNAME -> tcfl_config_VARNAME
        # this makes it easy to publish configuration items into the
        # tcfl.config space that then can be used in templates. It's a
        # hack, but makes configuration later on way easier
        tcfl_config = sys.modules['tcfl.config']
        for symbol in dir(tcfl_config):
            value = getattr(tcfl_config, symbol)
            if symbol.startswith("__"):
                continue
            elif callable(value):
                continue
            elif any([ isinstance(value, i)
                       for i in (list, dict, tuple, str, int)]):
                kws['tcfl_config_%s' % symbol] = value
            else:
                pass

        kws['targets'] = []
        for target_want_name, target in _tc.targets.items():
            entry = {}
            entry['want_name'] = target_want_name
            entry['id'] = target.id
            entry['fullid'] = target.fullid
            entry['type'] = _tc.type_map.get(target.type, target.type)
            entry['server_url'] = target.server.url
            kws['targets'].append(entry)

        # list only the servers that contain the current targets
        servers = set(target.server for target in _tc.targets.values())
        kws['tcfl_config_urls'] = []
        for server in sorted(servers, key = lambda server: server.url):
            kws['tcfl_config_urls'].append((
                server.url,
                not server.ssl_verify,	# ssl_ignore
                server.aka,
                server.ca_path,
            ))

        kws['tags'] = {}
        for tag in _tc._tags:
            (value, origin) = _tc.tag_get(tag, None, None)
            kws['tags'][tag] = dict(value = value, origin = origin)
        kws['count'] = 1
        kws['count_passed'] = 1 if msg_tag == 'PASS' else 0
        kws['count_failed'] = 1 if msg_tag == 'FAIL' else 0
        kws['count_errored'] = 1 if msg_tag == 'ERRR' else 0
        kws['count_skipped'] = 1 if msg_tag == 'SKIP' else 0
        kws['count_blocked'] = 1 if msg_tag == 'BLCK' else 0

        kws['ts_start'] = _tc.ts_start
        kws['ts_start_h'] = time.ctime(_tc.ts_start)
        kws['ts_end'] = _tc.ts_end
        kws['ts_end_h'] = time.ctime(_tc.ts_end)
        kws['duration_s'] = _tc.ts_end - _tc.ts_start

        kws['pid'] = _tc.kws['pid']
        kws['host_name'] = _tc.kws['host_name']
        kws['host_addrs'] = _tc.kws['host_addrs']

        for hook in self.hooks:		# call pre-rendeing hooks
            hook(self, _tc, kws)

        # Write to report file
        # FIXME: consider compiling the template as we'll keep reusing it
        template_path = [
            # new code as of 25/06 install in tcfl to
            # simplify wheel installs
            os.path.dirname(__file__),
            config.share_path
        ] + [ i for i in reversed(config.path) ]
        j2_env = jinja2.Environment(
            loader = jinja2.FileSystemLoader(template_path))
        j2_env.filters['xml_escape'] = jinja2_xml_escape
        for entry_name, template_entry in self.templates.items():
            template_name = template_entry['name']
            # each template might contain info that says in which
            # conditions it has to be rendered, so filter out those
            # who don't
            if message.startswith("COMPLETION failed") \
               and not template_entry.get('report_fail', True):
                _tc.log.info("%s|%s: reporting failed disabled"
                             % (entry_name, template_name))
                continue
            elif message.startswith("COMPLETION error") \
               and not template_entry.get('report_error', True):
                _tc.log.info("%s|%s: reporting errors disabled"
                             % (entry_name, template_name))
                continue
            elif message.startswith("COMPLETION skipped") \
               and not template_entry.get('report_skip', False):
                _tc.log.info("%s|%s: reporting skips disabled"
                             % (entry_name, template_name))
                continue
            elif message.startswith("COMPLETION blocked") \
               and not template_entry.get('report_block', True):
                _tc.log.info("%s|%s: reporting blockages disabled"
                             % (entry_name, template_name))
                continue
            elif message.startswith("COMPLETION passed") \
               and not template_entry.get('report_pass', False):
                _tc.log.info("%s|%s: reporting pass disabled"
                             % (entry_name, template_name))
                continue
            else:
                assert True, "Unknown COMPLETION message: %s" % message

            # Render this template; generate an entry that the
            # templating engine can use to iterate over the log file
            # (need to do this every time so the iterator is reset)
            kws['log'] = self._log_iterator(code)

            template = j2_env.get_template(template_name)
            file_name = template_entry['output_file_name'] % kws
            if not os.path.isabs(file_name):
                file_name = os.path.join(self.log_dir, file_name)
            # the template might specify a new directory path that
            # still does not exist
            commonl.makedirs_p(os.path.dirname(file_name), 0o750)
            with io.open(file_name, "w", encoding = 'utf-8',
                             errors = 'replace') as fo:
                for text in template.generate(**kws):	# and render!
                    fo.write(text)


    def report(self, testcase, target, tag, ts, delta,
               level, message, alevel, attachments):
        """
        Writes data to per-testcase/target temporary logfiles to
        render upon completion all the configured templates.

        We don't even check the levels, we log everything here by
        INFO <= 4.

        We report to the file ``TAG LEVEL CODE MESSAGE`` which we'll
        parse later to generate the report. When a *COMPLETION*
        message is reported, we assume the testcase is completed and
        call _mkreport() to render the templates.
        """
        if testcase == tc.tc_global:		# ignore the global reporter
            return
        # FIXME: config
        if tag == "INFO" and level > 4:	# ignore way chatty stuff
            return

        # Who's is this coming from?
        if target:
            tgname = "@" + target.fullid
        else:
            tgname = "@local"

        # Note we open the file for every thing we report -- we can be
        # running *A LOT* of stuff in parallel and run out of file
        # descriptors. get stream LRU caches them -- pass arguments
        # like that (instead of passing the testcase) so the LRU cache
        # decorator in _get_fd() can use it to hash.
        # NOTE WE ALWAYS save relative to the testcase's tmpdir, not
        # the reporter.tmpdir, which might be different (if the
        # reporter is a target)
        of = self._get_fd(testcase.ticket, testcase.tmpdir)
        # Remove the ticket from the ident string, as it will be
        # the same for all and makes no sense to have it.
        ident = testcase.ident()
        if ident == "":
            # If empty, give it a to snip token that we'll replace
            # later in mkreport
            ident = "<snip>"

        # The of file descriptor uses a buffer implementation that
        # takes the prefix from a thread-local-storage for every line
        # it writes, so just use that to flush the message and the
        # attachments.
        _prefix = u"%s %d %s %s\t " % (tag, level, ident, tgname)
        with commonl.tls_prefix_c(self.tls, _prefix):
            if not message.endswith('\n'):
                message += "\n"
            # @of writes _prefix for us, because we set it with
            # commonl.tls_prefix_c and @of is a
            # commonl.io_tls_prefix_lines_c(), which prefixes _prefix
            # on each line.
            # the timestamp is a horrible hack which we have to fix
            # properly by propagating it as a field in the temporary
            # log so later the templates can decide how to render it

            # if timezone is not set we will use local, if it is, we
            # change it to the one set by the user.
            # we need to localize the timezone before changing it, we can get
            # it in UTC straight from the timestamp, so no need to be guessing
            # the timezone of the machine.
            if self.timezone:
                try:
                    d = datetime.datetime.fromtimestamp(
                        ts, pytz.timezone(self.timezone))
                except pytz.exceptions.UnknownTimeZoneError:
                    logging.warning(
                        f"bad timezone '{self.timezone}' set for reporting."
                        f" REPORT_TZ: {os.environ.get('REPORT_TZ', 'n/a/')},"
                        f" TZ: {os.environ.get('TZ', 'n/a')}; defaulting to local")
                    d = datetime.datetime.fromtimestamp(ts)
            else:
                d = datetime.datetime.fromtimestamp(ts)
            # e.g. 22-02-28.12:56:00
            d = d.strftime('%y-%m-%d.%H:%M:%S')
            try:
                of.write(f"[{d} +{delta:.1f}s] " + message)
            except ValueError as e:
                testcase.log.error(f"can't write to dump file fd {of.name}/{of.fileno()}")
                return

        if attachments != None:
            # FIXME: \x01\x01 hack to denote an attachment, will
            # replace in _log_iterator() because the intermediate
            # format we have splits spaces--real fix will be to
            # convert that format to something more flexible
            _prefix = u"%s %d %s %s\t \x01\x01" % (tag, level, ident, tgname)
            with commonl.tls_prefix_c(self.tls, _prefix):
                assert isinstance(attachments, dict)
                commonl.data_dump_recursive_tls(attachments, self.tls,
                                                of = of)
        of.flush()
        # This is an indication that the testcase is done and we
        # can generate final reports
        if message.startswith("COMPLETION "):
            of.flush()
            self._mkreport(tag, testcase.ticket, testcase, message)
            # Wipe the file, it might have errors--it might be not
            # a file, so wipe hard
            #commonl.rm_f(self.fs[reporter.ticket])
            del self.fs[testcase.ticket]
            # can't remove from the _get_fd() cache, but it will be
            # removed once it's unused
            of.close()
            del of
