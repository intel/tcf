#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Driver to run Clear Linux BBT test suite
#
# See documentation for class tc_clear_bbt_c below for info.
#
# FIXME:
#
# - how do we specify dependencies in .ts? (target requirements) as in
#   it has to run in a machine this type with this much RAM, etc
#
#   something we can feed to @tcfl.tc.target()'s spec
#
# - we require the whole git tree for bbt.git to be available
#
# - we can't tell a .t for Clear apart from any other .t
#
# - everything ran as root, need metadata to decide what to run as
#   root, what as some normal user

import logging
import os
import re
import subprocess

import commonl
import tcfl
import tcfl.pos

logger = logging.getLogger("tcfl.tc_clear_bbt")

def tap_parse_output(output):
    """
    Parse `TAP
    <https://testanything.org/tap-version-13-specification.html>`_
    into a dictionary

    :param str output: TAP formatted output
    :returns: dictionary keyed by test subject containing a dictionary
       of key/values:
       - lines: list of line numbers in the output where data wsa found
       - plan_count: test case number according to the TAP plan
       - result: result of the testcase (ok or not ok)
       - directive: if any directive was found, the text for it
       - output: output specific to this testcase
    """
    tap_version = re.compile("^TAP version (?P<tap_version>[0-9]+)$")
    tc_plan = re.compile(r"^(?P<plan_min>[0-9]+)\.\.(?P<plan_max>[0-9]+)$")
    tc_line = re.compile(r"^(?P<result>(ok |not ok ))(?P<plan_count>[0-9]+ )?"
                         r"(?P<subject>[^#]*)(#(?P<directive>.*))?$")
    tc_output = re.compile(r"^#(?P<data>.*)$")
    skip_regex = re.compile(r"skip(ped)?:?", re.IGNORECASE)
    todo_regex = re.compile(r"todo:?", re.IGNORECASE)

    # state
    _plan_min = None
    _plan_top = None
    plan_set_at = None
    tcs = {}
    tc_current = None

    linecnt = 0
    _plan_count = 1
    for line in output.split("\n"):
        linecnt += 1
        m = tc_plan.search(line)
        if m:
            if plan_set_at:
                raise RuntimeError(
                    "%d: setting range, but was already set at %d",
                    linecnt, plan_set_at)
            plan_set_at = linecnt
            plan_min = int(m.groupdict()['plan_min'])
            plan_max = int(m.groupdict()['plan_max'])
            continue
        m = tc_line.search(line)
        if m:
            d = m.groupdict()
            result = d['result']
            count = d['plan_count']
            if not count or count == "":
                count = _plan_count	# if no count, use our internal one
            subject = d['subject']
            if not subject or subject == "":
                subject = str(count)	# if no subject, use count
            subject = subject.strip()
            directive_s = d.get('directive', '')
            if directive_s == None:
                directive_s = ''
                # directive is "TODO [text]", "skip: [text]"
            directive_s = directive_s.strip()
            directive_sl = directive_s.split()
            if directive_sl:
                directive = directive_sl[0]
                if skip_regex.match(directive):
                    result = "skip"
                elif todo_regex.match(directive):
                    result = "todo"
            else:
                directive = ''
            tc_current = subject
            tcs[subject] = dict(
                lines = [ linecnt ],
                plan_count = count,
                result = result.strip(),
                directive = directive_s,
                output = "",
            )
            tc = tcs[subject]
            # oficially a new testcase in the plan
            _plan_count += 1
            continue
        m = tap_version.search(line)
        if m:
            d = m.groupdict()
            tap_version = int(d['tap_version'])
            if tap_version != 12:
                raise RuntimeError("%d: Can't process versions != 12", linecnt)
            continue
        m = tc_output.search(line)
        if m:
            d = m.groupdict()
            tc['output'] += d['data'] + "\n"
            tc['lines'].append(linecnt)
            continue
    return tcs


mapping = {
    'ok': 'PASS',
    'not ok': 'FAIL',
    'skip': 'SKIP',
    'todo': 'ERRR',
}

class tc_taps_subcase_c_base(tcfl.tc.tc_c):
    """
    Report each subcase result of running a list of TAP testcases

    Given an entry of data from the output of
    :func:`tap_parse_output`, create a fake testcase that is just used
    to report results of the subcase.

    This is used by :class:`tc_clear_bbt_c` to report each TAP subcase
    individually for reporting control.
    """
    def __init__(self, name, tc_file_path, origin,
                 parent, data):
        assert isinstance(name, basestring)
        assert isinstance(tc_file_path, basestring)
        assert isinstance(origin, basestring)
        assert isinstance(parent, tcfl.tc.tc_c)
        assert isinstance(data, dict)

        tcfl.tc.tc_c.__init__(self, name, tc_file_path, origin)
        self.parent = parent
        # create a result object with the data we parsed from the output
        result = mapping[data['result']]
        if result == 'PASS':
            self.result = tcfl.tc.result_c(1, 0, 0, 0, 0)
        elif result == 'ERRR':
            self.result = tcfl.tc.result_c(0, 1, 0, 0, 0)
        elif result == 'FAIL':
            self.result = tcfl.tc.result_c(0, 0, 1, 0, 0)
        elif result == 'BLCK':
            self.result = tcfl.tc.result_c(0, 0, 0, 1, 0)
        elif result == 'SKIP':
            self.result = tcfl.tc.result_c(0, 0, 0, 0, 1)
        else:
            raise AssertionError('bad mapping from %s to %s, unknown result'
                                 % (data['result'], result))
        self.data = data
        self.kw_set('tc_name_short', name)

    def configure_50(self):	# pylint: disable = missing-docstring
	# we don't need to manipulate the targets, so don't assign;
        # will be faster -- do it like this so we can use the same
        # class testcases that require a target and those that don't.
        for target in self.targets.values():
            target.acquire = False
        self.report_pass("NOTE: This is a subtestcase of %(tc_name)s "
                         "(%(runid)s:%(tc_hash)s); refer to it for full "
                         "information" % self.parent.kws, dlevel = 1)

    def eval_50(self):		# pylint: disable = missing-docstring
        self.result.report(self, "subcase execution",
                           attachments = dict(output = self.data['output']))
        return self.result

    @staticmethod
    def clean():		# pylint: disable = missing-docstring
        # Nothing to do, but do it anyway so the accounting doesn't
        # complain that nothing was found to run
        pass


@tcfl.tc.interconnect('ipv4_addr')
@tcfl.tc.target('pos_capable', mode = 'any')
class tc_clear_bbt_c(tcfl.tc.tc_c):
    """Driver to load Clear Linux BBT test cases

    A BBT test case is specified in `bats
    <https://github.com/sstephenson/bats>_` format in a ``FILENAME.t``

    This driver gets called by the core testcase scanning system
    through the entry point :meth:`is_testcase`--in quite a simplistic
    way, if it detects the file is  ``FILENAME.t``, it decides it is
    valid and creates a class instance off the file path.

    The class instance serves as a testcase script that will:

    - in the deployment phase (deploy method):

      1. Request a Clear Linux image to be installed in the target
         system using the provisioning OS.

      2. Deploy the BBT tree to the target's ``/opt/bbt.git`` so
         testcases have all the dependencies they need to run
         (at this point we assume the git tree is available).

    - on the start phase:

      1. power cycle the target machine to boot and login into Clear

      2. install the *software-testing* bundle and any others
         specified in an optional 'requirements' file. Maybe use a
         mirror for *swupd*.

    - on the evaluation phase:

      1. run *bats* on the ``FILENAME.t`` which we have copied to
         ``/opt/bbt.git``.

      2. :func:`parse the output <tap_parse_output>` into subcases to
         report their results individually using
         :class:`tc_taps_subcase_c_base`

    """

    def __init__(self, t_file_path):
        tcfl.tc.tc_c.__init__(self, commonl.name_make_safe(t_file_path),
                              t_file_path, t_file_path)
        # t_file_path goes to self.kws['thisfile'], name to self.name
        # and self.kws['tc_name']
        self.image = None
        self.rel_path_in_target = None

    def _deploy_bbt(self, _ic, target, _kws):
        # we need to move the whole BBT tree to the target to run it,
        # because what we need from it
        # However, if we can't find the top level (eg: because it ain't
        # a git tree...) well, too bad FIXME allow specifying it
        # somehow else.
        bbt_tree = subprocess.check_output(
            [
                'git', 'rev-parse', '--flags', '--show-toplevel',
                # this way it works if we are calling from inside bbt.git
                # or from outside
                os.path.basename(self.kws['thisfile']),
            ],
            stderr = subprocess.STDOUT,
            cwd = os.path.dirname(self.kws['thisfile'])
        ).strip()
        # later we'll need to change to the path where the .t is to
        # run bats on it (otherwise it seems to fail, FIXME: why?). So
        # we get the relative path and save it, as in the target we'll
        # have the BBT tree in /opt
        # realpath -> undo symlinks, otherwise relpath() might get confused
        self.rel_path_in_target = os.path.relpath(
            os.path.realpath(self.kws['thisfile']),
            os.path.realpath(bbt_tree))

        tcfl.pos.target_rsync(target, bbt_tree.strip(), dst = '/opt/bbt.git',
                              persistent_name = 'bbt.git')


    def deploy(self, ic, target):
        # ensure network, DHCP, TFTP, etc are up and deploy
        ic.power.on()
        ic.report_pass("powered on")
        self.image = tcfl.pos.deploy_image(ic, target, "clear",
                                           extra_deploy_fns = [
                                               self._deploy_bbt,
                                           ])
        target.report_info("Deployed %s" % self.image)

    def start(self, ic, target):
        # fire up the target, wait for a login prompt
        target.power.cycle()
        target.shell.linux_shell_prompt_regex = re.compile('root@.*# ')
        target.shell.up(user = 'root')
        target.report_pass("Booted %s" % self.image)

        # Install bundles we need
        #
        # If there is a  'requirements' file alongside our .t file,
        # take it in. It has a bundle per line.
        bundles = [
            # always needs this, that installs 'bats'
            'software-testing'
        ]
        requirements_fname = os.path.join(self.kws['srcdir'], 'requirements')
        if os.path.exists(requirements_fname):
            bundles += open(requirements_fname).read().split()

        # If the network exposes a distro mirror, use it -- this is
        # kind of a hack for now, because we assume that if there is a
        # mirror, we don't have to use a proxy (if any) for getting to
        # it.
        # FIXME
        distro_mirror = ic.kws.get('distro_mirror', None)
        if distro_mirror:
            target.shell.run(
                "swupd mirror -s %s/pub/mirrors/clearlinux/update/"
                % distro_mirror)
        else:
            # if there is no distro mirror, use proxies -- HACK
            if 'http_proxy' in ic.kws:
                target.shell.run("export http_proxy=%s"
                                 % ic.kws.get('http_proxy'))
                target.shell.run("export HTTP_PROXY=%s"
                                 % ic.kws.get('http_proxy'))
            if 'https_proxy' in ic.kws:
                target.shell.run("export https_proxy=%s"
                                 % ic.kws.get('https_proxy'))
                target.shell.run("export HTTPS_PROXY=%s"
                                 % ic.kws.get('https_proxy'))

        # Install them bundles
        #
        # installing can take too much time, so we do one bundle at a
        # time so the system knows we are using the target.
        self.tls.expecter.timeout = 240
        for bundle in bundles:
            target.shell.run("time swupd bundle-add %s" % bundle)

    def eval(self, ic, target):

        # Now always make the proxy available if there is
        if 'http_proxy' in ic.kws:
            target.shell.run("export http_proxy=%s" % ic.kws.get('http_proxy'))
            target.shell.run("export HTTP_PROXY=%s" % ic.kws.get('http_proxy'))
        if 'https_proxy' in ic.kws:
            target.shell.run("export https_proxy=%s"
                             % ic.kws.get('https_proxy'))
            target.shell.run("export HTTPS_PROXY=%s"
                             % ic.kws.get('https_proxy'))

        target.shell.run("cd /opt/bbt.git/%s"
                         % os.path.dirname(self.rel_path_in_target))
        output = target.shell.run(
            "bats --tap /opt/bbt.git/%(thisfile)s"
            " || echo FAI''LED-%(tc_hash)s" % self.kws,
            output = True)
        if 'bats: command not found' in output:
            raise tcfl.tc.blocked_e("'bats' tool not installed in the target",
                                    dict(target = target, output = output))
        # top level result
        if 'FAILED-%(tc_hash)s' % self.kws in output:
            result = tcfl.tc.result_c(0, 1, 0, 0, 0)
        else:
            result = tcfl.tc.result_c(1, 0, 0, 0, 0)

        # seems we had execution, so let's parse the output and make subcases
        tcs = tap_parse_output(output)
        for name, data in tcs.iteritems():
            _name = commonl.name_make_safe(name)
            subcase = tc_taps_subcase_c_base(self.name + "." + _name,
                                             self.kws['thisfile'], self.origin,
                                             self, data)
            self.post_tc_append(subcase)
            result += subcase.result
        return result

    @staticmethod
    def clean():
        # Nothing to do, but do it anyway so the accounting doesn't
        # complain that nothing was found to run
        pass


    #
    # Testcase driver hookup
    #

    filename_regex = re.compile(r"^.*\.t$")

    @classmethod
    def is_testcase(cls, path):
        if not cls.filename_regex.match(os.path.basename(path)):
            return []
        tc = cls(path)
        return [ tc ]
