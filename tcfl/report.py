#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Report infrastructure
=====================

Infrastructure for reporting test case results and progress in a modular way.

"""
import codecs
import contextlib
import inspect
import logging
import os
import sys
import threading
import time
import traceback

import jinja2
import jinja2.filters

import commonl
import tcfl
import tcfl.tc
import tcfl.config

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


class report_c(object):
    """
    Report driver to write to stdout (for human consumption) and to a
    log file

    :param int verbosity: (optional) maximum verbosity to report;
      defaults to 1, for failures only
    """

    def __init__(self, verbosity = 1):
        self.verbosity = verbosity

    def verbosity_set(self, verbosity):
        self.verbosity = verbosity

    def _report(self, level, alevel, ulevel, _tc, tag, message, attachments):
        """
        Low level reporting

        :param level: report level for the main, one liner message
        :param alevel: report level for the attachments, or extra messages
        :param tc_c _tc: Test case
        :param tag: tag for this message (PASS, ERRR, FAIL, BLCK, INFO), all
           same length
        :param message: message string
        :param dict: dictionary of attachments; either an open file,
            to report the contents of the file or list of strings or
            strings or whatever
        """
        for rd in self._drivers:
            rd._report(level, alevel, ulevel, _tc, tag, message, attachments)
        raise NotImplementedError

    _drivers = []
    @classmethod
    def driver_add(cls, obj, origin = None):
        """
        Add a driver to handle other report mechanisms

        A report driver is used by *tcf run*, the meta test runner, to
        report information about the execution of testcases.

        A driver implements the reporting in whichever way it decides
        it needs to suit the application, uploading information to a
        server, writing it to files, printing it to screen, etc.

        >>> import tcfl.report
        >>> class my_report_driver(tcfl.report.report_c)
        >>> tcfl.report.report_c.driver_add(my_report_driver)

        :param tcfl.report.report_c obj: object subclasss of
          :class:tcfl.report.report_c that implements the reporting.

        :param str origin: (optional) where is this being registered;
          defaults to the caller of this function.

        """
        assert isinstance(obj, cls)
        if origin == None:
            o = inspect.stack()[1]
            origin = "%s:%s" % (o[1], o[2])
        setattr(obj, "origin", origin)
        cls._drivers.append(obj)

    @classmethod
    def driver_rm(cls, obj):
        """
        Add a driver to handle other report mechanisms

        :param str origin:
        """
        assert isinstance(obj, cls)
        cls._drivers.remove(obj)


    @classmethod
    def report(cls, level, alevel, ulevel, _tc,
               tag, message, attachments):
        """
        Low level reporting

        :param int level: report level for the main, one liner
          message; note report levels greater or equal to 1000 are
          using to pass control messages, so they might not be subject
          to normal verbosity control (for example, for a log file you
          might want to always include them).
        :param int alevel: report level for the attachments, or extra messages
        :param int ulevel: report level for unabridged attachments
        :param str obj: string identifying the reporting object
        :param str prefix: prefix for the message
        :param str tag: tag for this message (PASS, ERRR, FAIL, BLCK, INFO),
            all same length
        :param str message: message string
        :param dict: dictionary of attachments; either an open file,
            to report the contents of the file or list of strings or
            strings or whatever

        When a testcase completes execution, it will issue a report
        with a message **COMPLETION <result>** (where result is
        *passed*, *error*, *failed*, *blocked* or *skipped*) and a very high
        verbosity level which is meant for the driver do to any
        synchronization tasks it might need to do (eg: uploading the
        data to a database).

        Likewise, when all the testcases are run, the global testcase
        reporter will use a **COMPLETION <result>** report. The global
        testcase reporter can be identified because it has an
        attribute *skip_reports* set to *True* and thus can be
        identified with:

        .. code-block:: python

           if getattr(_tc, "skip_reports", False) == True:
               do_somethin_for_the_global_reporter

        """
        assert isinstance(level, int)
        assert isinstance(alevel, int)
        assert isinstance(ulevel, int)
        assert hasattr(_tc, "report_mk_prefix")
        assert isinstance(tag, basestring)
        assert isinstance(message, basestring)
        if level < 0:
            level = 0
        if alevel < 0:
            alevel = 0
        if ulevel < 0:
            ulevel = 0
        if attachments != None:
            assert isinstance(attachments, dict)
        for rd in cls._drivers:
            rd._report(level, alevel, ulevel, _tc,
                       tag, message, attachments)


class report_console_c(report_c):
    """
    Report driver to write to stdout (for human consumption) and to a
    log file

    :param int verbosity_logf: (optional) maximum verbosity to report
      to the logfile; defaults to all of them, but on some cases you
      might want to limit to cut on disk consumption.
    """
    # FIXME: might want to remove that log_dir and just pass a proper
    # log_file, have the shell frontend produce it
    def __init__(self, verbosity, log_dir, log_file = None,
                 verbosity_logf = 999):
        if log_file:
            assert isinstance(log_file, basestring)

        if log_file != None:
            if os.path.dirname(log_file) == '':
                self.log_file = os.path.join(log_dir, log_file)
            else:
                self.log_file = os.path.abspath(log_file)
        else:
            self.log_file = None

        self.lock = threading.Lock()
        report_c.__init__(self, verbosity)
        if self.log_file != None:
            self.logf = codecs.open(log_file, "w+", encoding = 'utf-8',
                                    errors = 'ignore')
        else:
            self.logf = None
        self.verbosity_logf = verbosity_logf

    def _report_writer(self, l, s):
        if l <= self.verbosity:
            # FIXME: hack -- avoid issues with different encoding
            # environments--I dislike this, but I don't have a better
            # solution
            sys.stdout.write(s.encode('utf-8', errors = 'replace'))
        # note we always want to log messages with verbosity greater
        # or equal to 1000, as those are used for control.
        if self.logf and (l >= 1000 or l <= self.verbosity_logf):
            self.logf.write(s)

    def _report_line(self, prefix, key, line_cnt, maxlines,
                     line, alevel, ulevel, maxlines_hit):
        s = "%s: %s: %s\n" % (prefix, key, line.rstrip())
        if line_cnt < maxlines:
            if line != '':
                self._report_writer(alevel, s)
        else:	# Over the limit? if maybe log to console
            if ulevel <= self.verbosity:
                # FIXME: hack -- avoid issues with different encoding
                # environments--I dislike this, but I don't have a better
                # solution
                sys.stdout.write(s.encode('utf-8', errors = 'replace'))
            elif maxlines_hit == False:
                if alevel <= self.verbosity:
                    msg = "%s: %s: SS <more output abridged>\n" % (prefix, key)
                    sys.stdout.write(msg)
                maxlines_hit = True
            if self.logf:		# But always log to the file
                self.logf.write(s)
        return maxlines_hit

    # FIXME: this is kind of broken -- base class (and driver) need to
    # provide a method to report attachments, so that the driver can
    # determine how to report it
    def _report_f_attachment(self, alevel, ulevel,
                             prefix, key, attachment):
        """
        :param int alevel: verbosity for attachments
        :param int ulevel: verbosity for unabridged attachment; if
                           verbosity is more than this, we print the
                           whole thing, otherwise only an abridged
                           version
        """
        maxlines = 50
        maxlines_hit = False
        cnt = 0
        try:
            if isinstance(attachment, basestring):
                for line in attachment.splitlines(False):
                    if line == '':
                        cnt += 1
                        continue
                    maxlines_hit = self._report_line(
                        prefix, key, cnt, maxlines,
                        line, alevel, ulevel, maxlines_hit)
            elif hasattr(attachment, "name"):
                # Is it a file? reopen it to read so we don't modify the
                # original pointer
                with codecs.open(attachment.name, "r",
                                 encoding = 'utf-8', errors = 'ignore') as f:
                    # We don't want to report all the file, just since
                    # the last change
                    if not attachment.closed:
                        f.seek(attachment.tell())
                    for line in f:
                        maxlines_hit = self._report_line(
                            prefix, key, cnt, maxlines,
                            line, alevel, ulevel, maxlines_hit)
            else:
                # all this needs a serious cleanup, what a mess -- if
                # we get attachments that are not lines or files it
                # fails badly.
                try:
                    for item in attachment:
                        if isinstance(item, basestring):
                            item = item.rstrip()
                        self._report_line(prefix, key, cnt, maxlines,
                                          item, alevel, ulevel,
                                          maxlines_hit)
                except TypeError as e:
                    self._report_line(prefix, key, 0, maxlines,
                                      "%s\n" % attachment, alevel, ulevel,
                                      maxlines_hit)
        except Exception as e:
            self._report_writer(alevel, "%s: %s: EE %s\n%s"
                                % (prefix, key, e, traceback.format_exc()))


    def _report(self, level, alevel, ulevel, _tc, tag, message, attachments):
        _prefix = "%s%d/%s\t" % (tag, level,
                                 tcfl.msgid_c.ident()) + _tc.report_mk_prefix()
        _aprefix = "%s%d/%s\t" % (
            tag, alevel, tcfl.msgid_c.ident()) + _tc.report_mk_prefix()
        with self.lock:
            self._report_writer(level, "%s: %s\n" % (_prefix, message))
            if attachments != None:
                assert isinstance(attachments, dict)
                for key, attachment in attachments.iteritems():
                    self._report_f_attachment(alevel, ulevel,
                                              _aprefix, key, attachment)
        sys.stdout.flush()
        if self.logf:
            self.logf.flush()


class file_c(report_c):
    """Report driver to write report files with information about a
    testcase.

    The Jinja2 templating engine is used to gather templates and fill
    them out with information, so it can create text, HTML, Junit XML,
    etc using templates.

    This driver saves log messages to separate files based on their
    :class:`tcfl.msgid_c` code (which is unique to each testcase
    running separately on a thread). When it detects a "COMPLETION"
    message (a top level conclussion), it will generate a report for
    each configured template, using data from the testcase metadata
    and the output it saved to those separate files.

    The default configuraton (the *text* template) will generate files
    called ``report-[RUNID:]ID.txt`` files for each
    error/failure/blockage. To enable it for passed or skipped test
    cases:

    >>> tcfl.report.file_c.templates['junit']['report_pass'] = False
    >>> tcfl.report.file_c.templates['junit']['report_skip'] = False

    The junit template (disabled by default) will generate
    ``junit-[RUNID:]ID.xml`` files with information from all the
    testcases executed based on the configuration settings below.

    To enable it for all conditions (or disable any replacing *True*
    with *False*):

    >>> tcfl.report.file_c.templates['junit']['report_pass'] = True
    >>> tcfl.report.file_c.templates['junit']['report_skip'] = True
    >>> tcfl.report.file_c.templates['junit']['report_error'] = True
    >>> tcfl.report.file_c.templates['junit']['report_fail'] = True
    >>> tcfl.report.file_c.templates['junit']['report_block'] = True

    See :data:`templates` for more information.

    """

    #:
    #: To create more templates, add a new dictionary:
    #:
    #: >>> tcfl.report.file_c.templates['MYTEMPLATE'] = dict(
    #: >>>    #:  name = 'report.j2.txt',
    #: >>>    #:  output_file_name = 'report-%(runid)s:%(tc_hash)s.txt',
    #: >>>    #:  report_pass = False,
    #: >>>    #:  report_skip = False,
    #: >>>    #:  report_error = True,
    #: >>>    #:  report_fail = True,
    #: >>>    #:  report_block = True
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
        "text" : dict(
            name = 'report.j2.txt',
            output_file_name = 'report-%(runid)s:%(tc_hash)s.txt',
            report_pass = False,
            report_skip = False,
            report_error = True,
            report_fail = True,
            report_block = True,
        ),
        "junit" : dict(
            name = 'junit.j2.xml',
            output_file_name = 'junit-%(runid)s:%(tc_hash)s.xml',
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
    #:        assert isinstance(tcfl.report.file_c, obj)
    #:        assert isinstance(tcfl.tc.tc_c, testcase)
    #:        assert isinstance(dict, kws)
    #:        kws['some new keyword'] = SOMEVALUE
    #:
    #:    tcfl.report.file_c.hooks.append(my_hook)
    #:
    #: Note these is done for all the templates; do not use global
    #: variables, as these function might be called from multiple
    #: threads.
    hooks = []

    @staticmethod
    def _write(f, s):
        if isinstance(s, unicode):
            f.write(s)
        else:
            f.write(unicode(s).encode('utf-8', errors = 'ignore'))

    def __init__(self, log_dir):
        assert isinstance(log_dir, basestring)
        assert isinstance(self.templates, dict)
        assert all([ isinstance(template, dict)
                     for template in self.templates.values() ])

        self.lock = threading.Lock()
        report_c.__init__(self)
        # Where we keep all the file descriptors to the different
        # files we are writing to based on the code
        self.log_dir = log_dir
        self.fs = {}

    def _report_f_attachment(self, f, prefix, key, attachment):
        """
        Write an attachment to descripror @f
        """
        if isinstance(attachment, basestring):
            # String
            for line in attachment.splitlines(False):
                if line == '':
                    continue
                line = line.encode('utf-8', errors = 'replace')
                self._write(f, u"%s %s: %s\n" % (prefix, key, line.rstrip()))
        elif hasattr(attachment, "name"):
            # Is it a file? reopen it to read so we don't modify the
            # original pointer
            with codecs.open(attachment.name, "r",
                             encoding = 'utf-8', errors = 'ignore') as fa:
                # We don't want to report all the file, just since the
                # last change
                if not attachment.closed:
                    fa.seek(attachment.tell())
                for line in fa:
                    self._write(
                        f, u"%s %s: %s\n" % (prefix, key, line.rstrip()))
        else:
            try:
                self._write(f, u"%s %s: %s\n" % (prefix, key, attachment))
            except TypeError:
                # FIXME: shouldn't this write about the exception?
                self._write(f, u"%s %s: [can't represent type %s]\n"
                            % (prefix, key, type(attachment).__name__))

    @staticmethod
    def _get_code():
        """
        Find out what the code is from the :class:`tcfl.msgid_c` stack, but
        only up to the top level (thus, by convention, the first four
        chars). Note we might have a runid (so [RUNID:]ABCD is our
        code) and we ignore the rest.
        """
        msgid = tcfl.msgid_c.ident()
        if ":" in msgid:
            runid, i = msgid.split(":", 1)
            runid += ":"
        else:
            runid = ""
            i = msgid
        # the root msgid is four characters (the default in msgid_c.generate())
        i = i[:4]
        return "%s%s" % (runid, i)

    def _report(self, level, alevel, ulevel, _tc, tag, message, attachments):
        """
        Report data to log files for a possible failure report later

        We don't even check the levels, we log everything here by
        INFO <= 4.

        We report to the file ``TAG LEVEL CODE MESSAGE`` which we'll
        parse later to generate the report.
        """
        # This is what marks all the testcase runs being done, so we
        # can use it to wrap things up.
        if _tc == tcfl.tc.tc_global:
            return
        # Okie, this is a hack -- this means this is a testcase, but
        # we need something better.
        if getattr(_tc, "skip_reports", False) == True:
            return	# We don't operate on the global reporter fake TC
        # Note we open the file for every thing we report -- we can be
        # running *A LOT* of stuff in parallel and run out of file
        # descriptors.
        if tag == "INFO" and level > 4:
            return
        code = self._get_code()
        if not code in self.fs:
            f = codecs.open(
                os.path.join(_tc.tmpdir, "report-" + code + ".txt"),
                "w", encoding = 'utf-8', errors = 'ignore')
            self.fs[code] = f.name
        else:
            f = codecs.open(self.fs[code], "a+b",
                            encoding = 'utf-8', errors = 'ignore')

        # Extract the target name where this message came from (if the
        # reporter is a target)
        if isinstance(_tc, tcfl.tc.target_c):
            tgname = " @" + _tc.fullid + _tc.bsp_suffix()
        else:
            tgname = " @local"
        with contextlib.closing(f):
            # Remove the ticket from the ident string, as it will be
            # the same for all and makes no sense to have it.
            ident = tcfl.msgid_c.ident()
            if ident.startswith(_tc._ident):
                ident = ident[len(_tc._ident):]
            if ident == "":
                # If empty, give it a to snip token that we'll replace
                # later in mkreport
                ident = "<snip>"
            _prefix = "%s %d %s%s\t" % (tag, level, ident, tgname)
            self._write(f, u"%s %s\n" % (_prefix, message))
            if attachments != None:
                assert isinstance(attachments, dict)
                for key, attachment in attachments.iteritems():
                    self._report_f_attachment(f, _prefix, key, attachment)
            f.flush()
            # This is an indication that the testcase is done and we
            # can generate final reports
            if message.startswith("COMPLETION "):
                self._mkreport(tag, code, _tc, message)
                # Wipe the file, it might have errors--it might be not
                # a file, so wipe hard
                commonl.rm_f(self.fs[code])
                del self.fs[code]

    def _log_iterator(self, code):
        """
        Filter from the log file things we are interested in (maybe
        everything)
        """
        with codecs.open(self.fs[code], "a+b",
                         encoding = 'utf-8', errors = 'ignore') as fi:
            # FIXME: can't we just pickle this?
            for line in fi:
                if line == "":
                    break
                # Note this might be we read a "^M" (\r)
                line = line.rstrip()
                if line == "":
                    continue
                token = line.split(None, 4)
                # Tokens are TAG LEVEL IDENT TGNAME MESSAGE
                if not token:
                    continue
                if len(token) < 3:
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
                else:
                    logging.error("BUG: missing message in line: %s", line)
                    message = "BUG:message-MISSING"
                try:
                    level = int(level_s)
                except ValueError:
                    logging.error("BUG: bad level in line: %s", line)
                    level = 0
                if tag == "INFO" and level > 2:
                    continue
                if ident == "<snip>":
                    # This is just so it aligns well; <snip> comes from
                    # _report() above.
                    ident = "   "
                # in Jinja2 templates, you can use the escape() or e()
                # filter to automatically escape anything that might
                # not be *ML kosher...but 0x00. So as we only need
                # this for reporting, we'll make an ugly exception.
                yield ident, tgname, message.replace("\x00", "<NULL>")

    def _mkreport(self, msg_tag, code, _tc, message):
        """
        Generate a failure report

        """
        # FIXME: initialize this in the core, so it shows in test_dump_kws*.py
        kws = commonl.dict_missing_c(_tc.kws)
        kws['msg_tag'] = msg_tag
        kws['result'] = tcfl.tc.valid_results.get(
            msg_tag, ( None, "BUG-RESULT-%s" % msg_tag))[0]
        kws['result_past'] = tcfl.tc.valid_results.get(
            msg_tag, ( None, "BUG-RESULT-%s" % msg_tag))[1]
        kws['message'] = message
        tfids = []
        for target_want_name, target in _tc.targets.iteritems():
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
                       for i in (list, dict, tuple, basestring, int)]):
                kws['tcfl_config_%s' % symbol] = value
            else:
                pass

        kws['targets'] = []
        for target_want_name, target in _tc.targets.iteritems():
            entry = {}
            entry['want_name'] = target_want_name
            entry['fullid'] = target.fullid
            entry['type'] = _tc.type_map.get(target.type, target.type)
            kws['targets'].append(entry)
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

        kws['ts_start'] = _tc.ts_end
        kws['ts_start_h'] = time.ctime(_tc.ts_end)
        kws['ts_end'] = _tc.ts_end
        kws['ts_end_h'] = time.ctime(_tc.ts_end)
        kws['duration_s'] = _tc.ts_end - _tc.ts_start

        for hook in self.hooks:
            hook(self, _tc, kws)

        # Write to report file
        # FIXME: consider compiling the template as we'll keep reusing it
        template_path = [ i for i in reversed(tcfl.config.path) ] \
                        + [ tcfl.config.share_path ]
        j2_env = jinja2.Environment(
            loader = jinja2.FileSystemLoader(template_path))
        j2_env.filters['xml_escape'] = jinja2_xml_escape
        for entry_name, template_entry in self.templates.iteritems():
            template_name = template_entry['name']
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

            # Need to do this every time so the iterator is reset
            kws['log'] = self._log_iterator(code)

            template = j2_env.get_template(template_name)
            file_name = template_entry['output_file_name'] % kws
            if not os.path.isabs(file_name):
                file_name = os.path.join(self.log_dir, file_name)
            # the template might specify a new directory path that
            # still does not exist
            commonl.makedirs_p(os.path.dirname(file_name), 0o750)
            with codecs.open(file_name, "w", encoding = 'utf-8',
                             errors = 'ignore') as fo:
                for text in template.generate(**kws):
                    fo.write(text)
