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
import cPickle
import glob
import errno
import inspect
import logging
import os
import StringIO
import sys
import threading
import time
import traceback

import jinja2
import junit_xml

import commonl
import tcfl
import tcfl.tc

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

        :param str origin:
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
                try:
                    for line in attachment:
                        self._report_line(prefix, key, cnt, maxlines,
                                          line.rstrip(), alevel, ulevel,
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
    """Report driver to write a text file with information about a
    testcase failure

    This driver is always enabled by default to generate text
    reports. You can flip the configuration to enable JUnit reports
    with:

    >>> tcfl.report.file_c.junit = True

    in any TCF configuration file.

    This driver will log messages to separate log files based on their
    :class:`tcfl.msgid_c` code (which is unique to each testcase
    running separately on a thread). When it detects a "COMPLETION"
    message (a top level conclussion), it will generate a report using
    the data gathered in the log file to a formatted file (text or
    JUnit) and remove the log file.

    This will generate ``report-ID.txt`` files for each
    error/failure/skip/blockage or a ``junit.xml`` file with information
    from all the testcases executed based on the configuration
    settings below.

    """

    #: (str) Text to be inserted as reproduction instructions (e.g.:
    #: to checkout the code at the right versions and locations).
    #:
    #: Note: This is a Jinja2 template in which you can use any *{{
    #: FIELDNAME }}* Python codes to replace values from the testcase
    #: dictionary and:
    #:
    #: - *{{ tcfl_config_urls }}* which maps to :data:`tcfl.config.urls`
    #:
    #: - *{{ t_option }}* a value that indicates what has to be given to
    #:   *tcf* to select the targets where the testcase was run.
    #:
    #: - FIXME: how to find about more kws
    #:
    #: See http://jinja.pocoo.org/docs/2.10/templates/# for more
    #: information.
    text_template = """\
FIXME: pending

 - move junit to use this
 - support having this being a file in the filesystem
 - support specifying multiple templates w/ filenames that would
   generate multiple files (eg: one .txt, one .html, one junit_.xml)
   via a templates = { 
         "report-%(runid)s:%(tc_hash)s.txt": templatespec1,
         "report-%(runid)s:%(tc_hash)s.html": templatespec2,
         "junit_%(DOMAINWHATEVER)...:%(tc_hash)s.txt": templatespec3,
    }
 - support layering, do it the proper jinja2 way


TCF: {{ tc_name_short }} @ {{ target_group_info }} **{{ result }}**

Target Name         Remote ID                     Type
------------------- ----------------------------- -------------------------\
{% for target_info in targets %}
{{ "%-19s %-29s %-25s"
   | format(target_info.want_name, target_info.fullid,
            target_info.type) }}
{% endfor %}

Execution log
=============

- console output in lines tagged 'console output'
- the target might have produced none; GDB might be needed at this point
- information for all testcase build, deployment and execution phases
  is included; filter by the first column

{% for ident, tgname, message in log %}\
{{ "%-10s %-30s %s" | format(ident, tgname, message) }}
{% endfor %}

Reproduce it [*]:

  tcf run -vvv{{ t_option }} -s 'name:".*{{ tc_name }}$"' {{ thisfile }}

Find more information about targets:

  tcf list -vv TARGETNAME1 TARGETNAME2 ...

Acquire them for exclusive use:

  tcf acquire TARGETNAME1 TARGETNAME2 ...

(note the daemon will relinquish them after 5min of inactivity)

Start debugging with

  tcf debug-start TARGETNAME
  tcf debug-info TARGETNAME

Power on

  tcf power-on TARGETNAME1 TARGETNAME2 ...

Reset with

  tcf reset TARGETNAME1 TARGETNAME2 ...

Read the console with

  tcf console-read -a TARGETNAME

Release when done

  tcf release TARGETNAME1 TARGETNAME2 ...

[*] Make sure your TCF configuration in ~/.tcf is set to access the servers
    used in this run:
{% for server_url, ssl_ignore, server_aka, ca_path in tcfl_config_urls %}
     tcfl.config.url_add("{{ server_url }}", ssl_ignore = {{ ssl_ignore }}\
{{ ', aka = \"' + server_aka + '\"' if server_aka }}\
{{ ', ca_path = \"' + ca_path + '\"' if ca_path }})\
{% endfor %}


Testcase Tag        Value + Origin
------------------- -------------------------------------------------------\
{% for tag in tags %}
{{ "%-19s %s" | format(tag, tags[tag]['value']) }}
{{ "                    @" + tags[tag]['origin'] }}\
{% endfor %}


How do I install TCF?
=====================
Go to http://intel.github.com/tcf/02-QUICKSTART.html

(You can configure this text by modifying the Jinja2 template
tcfl.report.text_template in any of TCF's conf_*.py configuration
files)

"""

    #: (str) Overrides :data:`reproduction` for JUnit reports
    junit_reproduction = None

    #: (bool) produce Junit reports (default False) to *junit.xml*
    junit = False

    #: (str) Domain to which to output JUnit reports for this testcase
    #:
    #: When completing the report on a testcase, it will be written to
    #: a `junit-DOMAIN.xml` file in the current working directory,
    #: where *DOMAIN* is extracted from this variable.
    #:
    #: Note you can use any *%(FIELD)TYPE* Python codes to replace
    #: values from the testcase dictionary. See :data:`text_template`. This
    #: allows you to use something like :data:`tcfl.tc.tc_c.hook_pre`
    #: to scan testcases and assign them a keyword (see the example in
    #: there) and then use the keyword to generate a domain:
    #:
    #: >>> ...
    #: >>> tcfl.tc.tc_c.hook_pre.append(_my_hook_fn)
    #: >>> tcfl.tc.report.file_c.junit_domain = "$(categories)s"
    #:
    #: Following the example in :data:`tcfl.tc.tc_c.hook_pre`,
    #: depending on the categorization of each testcases, a run would
    #: provide multiple JUnit output files to match the different
    #: categories a testcase would match under:
    #:
    #: - ``junit-uncategorized.xml``
    #: - ``junit-red.xml``
    #: - ``junit-green.xml``
    #: - ``junit-blue.xml``
    #: - ``junit-red.xml``
    #: - ``junit-blue,red.xml``
    #: - ``junit-red,green.xml``
    #: - ``junit-red,blue,green.xml``
    #: - ...
    #:
    #: If the *DOMAIN* is *default*, then the file will be called
    #: ``junit.xml``
    junit_domain = "default"

    #: List of hook functions to call before finalizing a Junit report
    #: to modify anything
    junit_hooks = []

    #: (bool) in Junit reports, include output of a testcase if it
    #: passed (defaults to False to reduce the amount of data in the XML
    #: file); if *None*, the *stderr* and *stdout* fields will be omitted.
    junit_report_pass = False
    #: (bool) in Junit reports, include output of a testcase if it
    #: is skipped (defaults to False to reduce the amount of data in the XML
    #: file)
    junit_report_skip = False
    #: (str) Classname for the JUnit testcase
    #:
    #: Note you can use any *%(FIELD)TYPE* Python codes to replace
    #: values from the testcase dictionary. See :data:`text_template`
    junit_name = "%(tc_name)s"
    #: (str) Classname for the JUnit testcase
    #:
    #: Note you can use any *%(FIELD)TYPE* Python codes to replace
    #: values from the testcase dictionary. See :data:`text_template`
    junit_classname = "%(target_group_types)s:%(tc_name_short)s"

    #: (str) Name of the JUnit test suite.
    #:
    #: Note you can use any *%(FIELD)TYPE* Python codes to replace
    #: values from the testcase dictionary. See :data:`text_template`
    junit_suite_name = "TCF test suite"
    #: (str) Name of the JUnit test suite package field.
    #:
    #: Note you can use any *%(FIELD)TYPE* Python codes to replace
    #: values from the testcase dictionary. See :data:`text_template`
    junit_suite_package = "n/a"
    #: (dict) Properties of the JUnit test suite.
    #:
    #: This is a dictionary of string values that will be filled in as
    #: test suite properties.
    junit_suite_properties = None

    #: (bool) produce text reports (default True) to *report-HASH.txt*
    text = True
    #: (bool) in text reports, include output of a testcase if it
    #: passed (defaults to False to reduce the amount of data)
    text_report_pass = False
    #: (bool) in text reports, include output of a testcase if it
    #: skipped (defaults to True) FIXME: unimplemented yet
    text_report_skip = True

    @staticmethod
    def _write(f, s):
        if isinstance(s, unicode):
            f.write(s)
        else:
            f.write(unicode(s).encode('utf-8', errors = 'ignore'))

    def __init__(self, log_dir):
        assert isinstance(log_dir, basestring)

        assert self.text_template == None \
            or isinstance(self.text_template, basestring)
        assert self.junit_reproduction == None \
            or isinstance(self.junit_reproduction, basestring)

        assert isinstance(self.junit, bool)
        assert self.junit_domain == None \
            or isinstance(self.junit_domain, basestring)
        assert not self.junit_report_pass \
            or isinstance(self.junit_report_pass, bool)
        assert isinstance(self.junit_report_skip, bool)
        assert self.junit_name == None \
            or isinstance(self.junit_name, basestring)
        assert self.junit_classname == None \
            or isinstance(self.junit_classname, basestring)
        assert self.junit_suite_name == None \
            or isinstance(self.junit_suite_name, basestring)
        assert self.junit_suite_package == None \
            or isinstance(self.junit_suite_package, basestring)
        assert self.junit_suite_properties == None \
            or isinstance(self.junit_suite_properties, dict)

        assert isinstance(self.text, bool)
        assert isinstance(self.text_report_pass, bool)
        assert isinstance(self.text_report_skip, bool)

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
                for line in attachment:
                    self._write(
                        f, u"%s %s: %s\n" % (prefix, key, line.rstrip()))
            except TypeError:
                # FIXME: shouldn't this write about the exception?
                self._write(f, u"%s %s: %s\n" % (prefix, key, attachment))

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
        INFO > 2.

        We report to the file ``TAG LEVEL CODE MESSAGE`` which we'll
        parse later to generate the report.
        """
        # This is what marks all the testcase runs being done, so we
        # can use it to wrap things up.
        if _tc == tcfl.tc.tc_global:
            if message.startswith("COMPLETION"):
                self._finalize(_tc)
            return
        # Okie, this is a hack -- this means this is a testcase, but
        # we need something better.
        if getattr(_tc, "skip_reports", False) == True:
            return	# We don't operate on the global reporter fake TC
        # Note we open the file for every thing we report -- we can be
        # running *A LOT* of stuff in parallel and run out of file
        # descriptors.
        if tag == "INFO" and level > 2:
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
            # FIXME: this is an unsmokable mess and needs to be fixed.
            # will defer cleaning up until we move the whole reporting
            # to be done with a Jinja2 template so the report paths
            # are fully split.
            if self.junit and message.startswith("COMPLETION") \
               or message.startswith("COMPLETION failed") \
               or message.startswith("COMPLETION error") \
               or message.startswith("COMPLETION blocked") \
               or message.startswith("COMPLETION skipped") \
               or (message.startswith("COMPLETION passed")
                   and (
                       _tc.tag_get('report_always', (False, ))[0] == True
                       or self.text_report_pass
                   )):
                self._mkreport(tag, code, _tc, message, f)
                # Wipe the file, it might have errors--it might be not
                # a file, so wipe hard
                commonl.rm_f(self.fs[code])
                del self.fs[code]

    def _log_filter(self):
        """
        Filter from the log file things we are interested in (maybe
        everything)
        """
        max_fullid_len = kws['max_fullid_len']
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
            yield ident, tgname, message

    def _mkreport_junit(self, _tc, kws, header, output,
                        tag_info, reproduction):

        for hook in self.junit_hooks:
            hook(self, _tc, kws, output)
        jtc = junit_xml.TestCase(
            self.junit_name % kws,
            classname = self.junit_classname % kws,
            elapsed_sec = 123.456,
            stdout = header + tag_info + reproduction,
            stderr = None)

        # FIXME: nail down the exception
        # <error/failure/blockage/skipped/or cause to put that only in
        # the messagee and let's put the whole output always in
        # stdout, with the rest of the info on stderr
        msg_tag = kws['msg_tag']
        if msg_tag == "FAIL":
            jtc.add_failure_info(message = "Failed", output = output)
        elif msg_tag == "ERRR":
            jtc.add_error_info(message = "Error", output = output)
        elif msg_tag == "BLCK":
            jtc.add_error_info(message = "Infrastructure", output = output)
        elif msg_tag == "SKIP":
            if self.junit_report_skip:
                jtc.add_skipped_info(message = "Skipped", output = output)
            else:
                jtc.add_skipped_info(message = "Skipped")
                jtc.stdout = None
                jtc.stderr = None
        elif msg_tag == "PASS":
            if self.junit_report_pass:
                jtc.stderr = output
            elif self.junit_report_pass == None:
                # we don  want *anything*
                jtc.stderr = None
                jtc.stdout = None
            else:	# False
                jtc.stderr = "<inclusion of output disabled by " \
                             "configuration setting of " \
                             "tcfl.report.junit_report_pass>"
                jtc.stdout = "<inclusion of output disabled by " \
                             "configuration setting of " \
                             "tcfl.report.junit_report_pass>"

        # Write the JUNIT to a pickle file, as we'll join it later
        # with the rest in _finalize. We can't put it in a
        # global because this testcase might be running in a separate
        # thread or process.  later == when the global testcase
        # reporter (tcfl.tc.tc_global) emits a COMPLETION message,
        # then we call _finalize()
        domain = commonl.file_name_make_safe(self.junit_domain % kws)
        # use the core keywords, so it is not modified
        tc_hash = _tc.kws['tc_hash']
        # Note we store it in the common
        pathname = os.path.join(tcfl.tc.tc_c.tmpdir, "junit", domain)
        commonl.makedirs_p(pathname)
        with open(os.path.join(pathname, tc_hash + ".pickle"), "w") as picklef:
            cPickle.dump(jtc, picklef, protocol = 2)

    def _mkreport_header(self, _tc, kws):
        header = u"""
TCF: %(tc_name)s @ %(target_group_info)s %(message)s
""" % kws
        if kws['report_header']:
            header += kws['report_header']
        # These definitions need to be always available, as we'll
        # use them for formatting elsewhere beyond the printing of
        # the target list
        # FIXME: move to function
        max_fullid_len = 0
        max_twn_len = 0
        max_type_len = 0
        if _tc.targets:
            # There might be a more pythonic way to do this, but
            # this one is readable
            for target_want_name, target in _tc.targets.iteritems():
                twn_len = len(target_want_name)
                if twn_len > max_twn_len:
                    max_twn_len = twn_len
                fullid_len = len(target.fullid)
                if fullid_len > max_fullid_len:
                    max_fullid_len = fullid_len
                target_type = _tc.type_map.get(target.type, target.type)
                type_len = len(target_type)
                if type_len > max_type_len:
                    max_type_len = type_len
        max_twn_len = max(max_twn_len, len("Target Name"))
        max_fullid_len = max(max_fullid_len, len("Remote ID"))
        max_type_len = max(max_type_len, len("Type"))
        if _tc.targets:
            tfids = []
            header += \
                u"\n{twn:{twn_len}s} {fullid:{fullid_len}s} " \
                "{ttype:{ttype_len}s}\n".format(
                    twn = "Target Name", twn_len = max_twn_len + 1,
                    fullid = "Remote ID",
                    fullid_len = max_fullid_len + 1,
                    ttype = "Type", ttype_len = max_type_len + 1)
            header += \
                u"{twn:{twn_len}s} {fullid:{fullid_len}s} " \
                "{ttype:{ttype_len}s}\n".format(
                    twn = "-" * max_twn_len, twn_len = max_twn_len + 1,
                    fullid = "-" * max_fullid_len,
                    fullid_len = max_fullid_len + 1,
                    ttype = "-" * max_type_len,
                    ttype_len = max_type_len + 1)
            for target_want_name, target in _tc.targets.iteritems():
                if len(target.rt.get('bsp_models', {})) > 1:
                    tfids.append(
                        '(' + target.fullid
                        + ' and bsp_model == "%s")' % target.bsp_model)
                else:
                    tfids.append(target.fullid)
                target_type = _tc.type_map.get(target.type, target.type)
                header += \
                    u"{twn:{twn_len}s} {fullid:{fullid_len}s} " \
                    "{ttype:{ttype_len}s}\n".format(
                        twn = target_want_name, twn_len = max_twn_len + 1,
                        fullid = target.fullid,
                        fullid_len = max_fullid_len + 1,
                        ttype = target_type,
                        ttype_len = max_type_len + 1)
            kws['t_option'] = " -t '" + " or ".join(tfids) + "'"
        kws['max_fullid_len'] = max_fullid_len
        kws['max_twn_len'] = max_twn_len
        kws['max_type_len'] = max_type_len
        return header

    def _mkreport_output(self, kws, filename):
        outputf = StringIO.StringIO(u"")
        outputf.write(u"""\

Execution log
=============

- console output in lines tagged 'console output'
- the target might have produced none; GDB might be needed at this point
- information for all testcase build, deployment and execution phases
  is included; filter by the first column

""" % kws)
        with codecs.open(os.path.join(self.log_dir, filename.name), "r",
                         encoding = 'utf-8', errors = 'ignore') as fi:
            self._log_filter(outputf, fi, kws)
        outputf.flush()
        return outputf.getvalue()

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
                yield ident, tgname, message

    def _mkreport(self, msg_tag, code, _tc, message, f):
        """
        Generate a failure report

        """
        # FIXME: break out into smaller flows
        global targets_all

        kws = commonl.dict_missing_c(_tc.kws)
        kws['msg_tag'] = msg_tag
        kws['result'] = _tc.valid_results.get(
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

        # Once the rest of the keys are available, generate the
        # user-provided ones

        # Seriously, I can't get right the Unicode and Python misterious ways
        # without getting thrown exceptions in the middle, so open the output
        # file normally and we just forcibly write unicode/utf-8 to it in
        # _fwrite(). As well, re-open the input file in utf-8 mode to
        # avoid doing manual conversion.
        kws['tcfl_config_urls'] = tcfl.config.urls

        # FIXME: initialize this in the core, so it shows in test_dump_kws*.py
        kws['targets'] = []
        for target_want_name, target in _tc.targets.iteritems():
            entry = {}
            entry['want_name'] = target_want_name
            entry['fullid'] = target.fullid
            entry['type'] = _tc.type_map.get(target.type, target.type)
            kws['targets'].append(entry)
        kws['tags'] = {}
        kws['log'] = self._log_iterator(code)
        for tag in _tc._tags:
            (value, origin) = _tc.tag_get(tag, None, None)
            kws['tags'][tag] = dict(value = value, origin = origin)

        # Write to report file
        # FIXME: consider compiling the template as we'll keep reusing it
        if self.text and (
                msg_tag == "PASS" and self.text_report_pass
                or msg_tag != "PASS"):
            with codecs.open(os.path.join(self.log_dir,
                                          "report-" + code + ".txt"), "w",
                             encoding = 'utf-8', errors = 'ignore') as fo:
                template = jinja2.Template(self.text_template)
                if template:
                    # FIXME: the log records will be too long to load
                    # in KWS -- read on how to do it
                    for text in template.generate(**kws):
                        fo.write(text)
        if self.junit:
            if self.junit_reproduction != None:
                template = jinja2.Template(self.junit_reproduction)
            elif self.reproduction != None:
                template = jinja2.Template(self.reproduction)
            else:
                template = None
            if template:
                reproduction = template.render(
                    tcfl_config_urls = tcfl.config.urls, **kws)
            else:
                reproduction = ""

            self._mkreport_junit(_tc, kws, header, output,
                                 tag_info, reproduction)


    def _finalize_junit_domain(self, _tc, domain):
        # Find all the junit-*.pickle files dropped by _mkreport()
        # above and collect them into a testsuite, writing an XML in
        # the CWD called junit.xml.

        reports = []
        domain_path_glob = os.path.join(tcfl.tc.tc_c.tmpdir, "junit",
                                        domain, "*.pickle")
        for filename in glob.glob(domain_path_glob):
            with open(filename) as f:
                jtc = cPickle.load(f)
                reports.append(jtc)

        ts = junit_xml.TestSuite(
            self.junit_suite_name % _tc.kws,
            reports,
            # I'd like:
            # hostname = _tc.kws['target_group_info'],
            # but it can't, because each TC in the suite is run in a
            # different target group. Maybe at some point TestCase
            # will support hostname?
            hostname = None,
            id = _tc.kws['runid'],
            package = self.junit_suite_package % _tc.kws,
            timestamp = time.time(),
            properties = self.junit_suite_properties,	# Dictionary
        )
        del reports

        if domain == "default":
            junit_filename = "junit.xml"
        else:
            junit_filename = commonl.file_name_make_safe(
                "junit-%s.xml" % domain, extra_chars = "")
        with codecs.open(junit_filename, 'w',
                         encoding = 'utf-8', errors = 'ignore') as f:
            junit_xml.TestSuite.to_file(f, [ ts ], prettyprint = True)

    def _finalize_junit(self, _tc):
        # Find all the junit-*.pickle files dropped by _mkreport()
        # above and collect them into a testsuite, writing an XML in
        # the CWD called junit.xml.
        #
        # remember we put them in TMPDIR/DOMAIN/HASH.pickle and we
        # generate $PWD/junit-DOMAIN.xml (except for DOMAIN ==
        # default, where we call it junit.xml)

        path_glob = os.path.join(tcfl.tc.tc_c.tmpdir, "junit", "*")
        # the key is the trailing / so it lists the subdirectories...
        for dirname in glob.glob(path_glob + "/"):
            domain = os.path.basename(os.path.dirname(dirname))
            self._finalize_junit_domain(_tc, domain)

    def _finalize(self, _tc):
        if self.junit:
            return self._finalize_junit(_tc)
