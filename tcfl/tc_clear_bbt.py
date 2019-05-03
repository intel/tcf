#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
"""
Driver to run Clear Linux BBT test suite

The main TCF testcase scanner walks files looking for automation
scripts / testcase scripts and will call
:meth:`tc_clear_bbt_c.is_testcase` for each ``*.t`` files on a
directory. The driver will generate one testcase per directory which
will execute all the ``.t`` in there and then execute all the ``.t``
in the any-bundle subdirectory.

The testcases created are instances of :class:`tc_clear_bbt_c`; this
class will allocate one interconnect/network and one
:ref:`*pos_capable* <pos_setup>` target. In said target it will
install Clear OS (from an image server in the interconnect) during the
*deploy* phase.

Once then installation is done, it will install any required bundles
and execute all the ``.t`` files in the directory followed by all the
``.t`` in the *any-bundle* top level directory.

The output of each ``.t`` execution is parsed with
:func:`tap_parse_output` to generate for each a subcase (an instance
of :class:`subcases <tc_taps_subcase_c_base>`) which will report the
individual result of that subcase execution.

**Setup steps**

To improve the deployment of the BBT tree, a copy can be kept in the
server's rsync image area for initial seeding; to setup, execute in
the server::

  $ mkdir -p /home/ttbd/images/misc
  $ git clone URL/bbt.git /home/ttbd/images/misc/bbt.git

"""
# FIXME:
#
# - specify which clear image version to install
#
# - how do we specify dependencies in .ts? (target requirements) as in
#   it has to run in a machine this type with this much RAM, etc
#
#   something we can feed to @tcfl.tc.target()'s spec
#
#   -> can be taken from clear.xml but a proper mapping has to be established
#
# - everything ran as root, need metadata to decide what to run as
#   root, what as some normal user
#
#   - labels -> tags
#
# - add suggested timeouts

import logging
import glob
import os
import re
import subprocess
import time

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
        result = parent.mapping[data['result']]
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
        self.result.report(self, "subcase execution", dlevel = 2,
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

         Assumes the BBT tree has an specific layout::

           DIR/SUBDIR/SUBSUBDIR[/...]/NAME/*.t
           any-bundles/*.t

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

    def __init__(self, path, t_file_path):
        tcfl.tc.tc_c.__init__(self, path,
                              # these two count as the ones that started this
                              t_file_path, t_file_path)
        # t_file_path goes to self.kws['thisfile'], name to self.name
        # and self.kws['tc_name']
        self.rel_path_in_target = None
        self.t_files = [ t_file_path ]
        self.deploy_done = False

    def configure_10_set_relpath_set(self):
        # calculate these here in case we skip deployment
        self.bbt_tree = subprocess.check_output(
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
            os.path.realpath(self.kws['srcdir']),
            os.path.realpath(self.bbt_tree))

    #: Specification of image to install
    #:
    #: default to whatever is configured on the environment (if any)
    #: for quick setup; otherwise it can be configured in a TCF
    #: configuration file by adding:
    #:
    #: >>> tcfl.tc_clear_bbt.tc_clear_bbt_c.image = "clear::24800"
    #:
    image = os.environ.get("IMAGE", "clear")

    #: swupd mirror to use
    #:
    #: >>> tcfl.tc_clear_bbt.tc_clear_bbt_c.swupd_url = \
    #: >>>      "http://someupdateserver.com/update/"
    #:
    #:
    #: Note this can use keywords exported by the interconnect, eg:
    #:
    #: >>> tcfl.tc_clear_bbt.tc_clear_bbt_c.swupd_url = \
    #: >>>      "http://%(MYFIELD)s/update/"
    #:
    #: where::
    #:
    #:   $ tcf list -vv nwa | grep MYFIELD
    #:     MYFIELD: someupdateserver.com
    swupd_url = os.environ.get("SWUPD_URL", None)
    
    image_tree = os.environ.get("IMAGE_TREE", None)

    #: Do we add debug output to swupd?
    swupd_debug = bool(os.environ.get("SWUPD_DEBUG", False))

    #: Mapping from TAPS output to TCF conditions
    #:
    #: This can be adjusted globally for all testcases or per testcase:
    #:
    #: >>> tcfl.tc_clear_bbt.tc_clear_bbt_c.mapping['skip'] = 'BLCK'
    #:
    #: or for an specific testcase:
    #:
    #: >>> tcobject.mapping['skip'] = 'BLCK'
    #:
    mapping = {
        'ok': 'PASS',
        'not ok': 'FAIL',
        'skip': 'SKIP',
        'todo': 'ERRR',
    }

    def _deploy_bbt(self, _ic, target, _kws):
        # note self.bbt_tree and self.rel_path_in_target are set by
        # configure_00_set_relpath_set(); this way if we call withtout
        # deploying, we still have them

        target.shell.run("mkdir -p /mnt/persistent.tcf.d/bbt.git")
        # try rsyncing a seed bbt.git repo from -- this speeds up
        # first time transmisisons as the repo is quite close in the
        # server; further rsync from the local version in the client
        target.report_info("POS: rsyncing bbt.git from %(rsync_server)s "
                           "to /mnt/persistent.tcf.git/bbt.git" % _kws,
                           dlevel = -1)
        target.shell.run("time rsync -aAX --numeric-ids"
                         " %(rsync_server)s/misc/bbt.git/."
                         " /mnt/persistent.tcf.d/bbt.git/."
                         " || echo FAILED-%(tc_hash)s"
                         % _kws)
        target.report_info("POS: rsynced bbt.git from %(rsync_server)s "
                           "to /mnt/persistent.tcf.d/bbt.git" % _kws)

        target.pos.rsync(self.bbt_tree, dst = '/opt/bbt.git',
                         persistent_name = 'bbt.git')


#    @tcfl.tc.concurrently()
    def deploy(self, ic, target):
        # ensure network, DHCP, TFTP, etc are up and deploy
        ic.power.on()
        if self.image_tree:
            target.deploy_tree_src = self.image_tree
        self.image = target.pos.deploy_image(
            ic, self.image, extra_deploy_fns = [
                # first deploy our local tree, if any--note this will
                # wipe out anything existing
                tcfl.pos.deploy_tree,
                # then layer the BBT on top
                self._deploy_bbt,
            ])
        target.report_info("Deployed %s" % self.image)
        self.deploy_done = True

# FIXME:
#    @tcfl.tc.concurrently()
#    def deploy_keep_active(self, ic, target):
#        t0 = time.time()
#        while not self.deploy_done:
#            self.targets_active()
#            time.sleep(5)
#            t = time.time()
#            self.report_info("DEBUG keeping targets active after %f"
#                             % (t - t0), level = 0)
#            t0 = t

    def start(self, ic, target):
        ic.power.on()
        # fire up the target, wait for a login prompt
        target.power.cycle()
        target.shell.linux_shell_prompt_regex = re.compile('root@.*# ')
        target.shell.up(user = 'root')
        target.report_pass("Booted %s" % self.image)

        target.shell.run(
            "test -f /etc/ca-certs/trusted/regenerate"
            " && rm -rf /run/lock/clrtrust.lock"
            " && clrtrust -v generate"
            " && rm -f /etc/ca-certs/trusted/regenerate")
        
        # Install bundles we need
        #
        # If there is a  'requirements' file alongside our .t file,
        # take it in. It has a bundle per line.
        bundles = [
            # always needs this, that installs 'bats'
            'os-testsuite'
        ]
        requirements_fname = os.path.join(self.kws['srcdir'], 'requirements')
        if os.path.exists(requirements_fname):
            bundles += open(requirements_fname).read().split()
        self.report_info("Bundle requirements: %s" % " ".join(bundles),
                         dlevel = 1)
        
        # if there is no distro mirror, use proxies -- HACK
        tcfl.tl.sh_export_proxy(ic, target)

        distro_mirror = ic.kws.get('distro_mirror', None)
        if self.swupd_url:
            swupd_url = self.swupd_url % ic.kws
            target.shell.run("swupd mirror -s %s" % swupd_url)
        elif distro_mirror:
            # If the network exposes a distro mirror, use it -- this is
            # kind of a hack for now, because we assume that if there is a
            # mirror, we don't have to use a proxy (if any) for getting to
            # it.
            # FIXME
            target.shell.run(
                "swupd mirror -s %s/pub/mirrors/clearlinux/update/"
                % distro_mirror)

        # Install them bundles
        #
        # installing can take too much time, so we do one bundle at a
        # time so the system knows we are using the target.
        #
        # As well, swupd doesn't seem to be able to recover well from
        # network glitches--so we do a loop where we retry a few times;
        # we record how many tries we did and the time it took as KPIs
        self.tls.expecter.timeout = 240
        for bundle in bundles:
            if self.swupd_debug:
                debug = "--debug"
            else:
                debug = ""
            count = 0
            top = 10
            for count in range(1, top + 1):
                # We use -p so the format is the POSIX standard as
                # defined in
                # https://pubs.opengroup.org/onlinepubs/009695399/utilities/time.html
                # STDERR section
                output = target.shell.run(
                    "time -p swupd bundle-add %s %s || echo FAILED''-%s"
                    % (debug, bundle, self.kws['tc_hash']), output = True)
                if not 'FAILED-%(tc_hash)s' % self.kws in output:
                    # we assume it worked
                    break
                target.shell.run("sleep 5s # failed %d/%d? retrying in 5s"
                                 % (count, top))
            else:
                target.report_data("BBT bundle-add retries",
                                   bundle, count)
                raise tcfl.tc.error_e("bundle-add failed too many times")
            # see above on time -p
            kpi_regex = re.compile(r"^real[ \t]+(?P<seconds>[\.0-9]+)$",
                                   re.MULTILINE)
            m = kpi_regex.search(output)
            if not m:
                raise tcfl.tc.error_e(
                    "Can't find regex %s in output" % kpi_regex.pattern,
                    dict(output = output))
            # maybe domain shall include the top level image type
            # (clear:lts, clear:desktop...)
            target.report_data("BBT bundle-add retries",
                               bundle, int(count))
            target.report_data("BBT bundle-add duration (seconds)",
                               bundle, float(m.groupdict()['seconds']))

    def _eval_one(self, target, t_file, prefix = ""):
        result = tcfl.tc.result_c(0, 0, 0, 0, 0)
        self.report_info("running %s%s" % (prefix, t_file))
        self.kw_set("t_file", t_file)
        output = target.shell.run(
            # remember we cd'ed into the directory
            "bats --tap %s || echo FAILED''-%s"
            % (t_file, self.kws['tc_hash']),
            output = True)
        if 'bats: command not found' in output:
            raise tcfl.tc.blocked_e(
                "'bats' tool not installed in the target",
                dict(target = target, output = output))
        # top level result
        if 'FAILED-%(tc_hash)s' % self.kws in output:
            result.failed += 1
        else:
            result.passed += 1

        # seems we had execution, so let's parse the output and
        # make subcases
        tcs = tap_parse_output(output)
        for name, data in tcs.iteritems():
            _name = commonl.name_make_safe(name)
            t_file_name = t_file.replace(".t", "")
            subcase = tc_taps_subcase_c_base(
                prefix + t_file_name + "." + _name,
                self.kws['thisfile'], self.origin,
                self, data)
            self.post_tc_append(subcase)
            result += subcase.result
        return result

    def eval(self, ic, target):

        tcfl.tl.sh_export_proxy(ic, target)
        # most testcases assume they are running from the same
        # directory where the .t is.
        target.shell.run("cd /opt/bbt.git/%s" % self.rel_path_in_target)
        result = tcfl.tc.result_c(0, 0, 0, 0, 0)
        # Now run all the .t in the directory, we discovered them when
        self.report_info("will run t_files %s" % " ".join(self.t_files),
                         dlevel = 1)

        for t_file in sorted(self.t_files):
            result += self._eval_one(target, t_file)

        # we scan for 'any' bundle testcases in the local FS, which we
        # know we have copied to the remote:
        target.shell.run("cd /opt/bbt.git/any-bundle")
        for any_t_file_path in glob.glob(os.path.join(
                os.path.dirname(self.kws['thisfile']),
                "..", "..", "any-bundle", "*.t")):
            any_t_file = os.path.basename(any_t_file_path)
            result += self._eval_one(
                target, any_t_file,
                prefix = self.rel_path_in_target + "/any#")

        return result

    @staticmethod
    def clean():
        # Nothing to do, but do it anyway so the accounting doesn't
        # complain that nothing was found to run
        pass


    #
    # Testcase driver hookup
    #

    #: (bool) ignores stress testcases
    ignore_stress = True

    paths = {}
    filename_regex = re.compile(r"^.*\.t$")

    @classmethod
    def is_testcase(cls, path):
        # the any-bundle directory of bbt.git is only to run after
        # other testcases--lame case to avoid it. IFFF you run from
        # inside it, it won't catch it, but so what...
        if path.startswith("any-bundle/") or "/any-bundle/" in path:
            return []
        # Catch .t's
        if not cls.filename_regex.match(os.path.basename(path)):
            return []
        file_name = os.path.basename(path)
        # Ignore stress tests for the time being
        if cls.ignore_stress and file_name.startswith("stress-"):
            logging.warning("ignoring stress testcase %s", path)
            return []
        # Now split in path/filename.
        # The TCF core cannot scan directories, just files. Because in
        # this case we want to create a testcase per-directory, we do
        # so. However, we save it in cls.paths (a class-variable). If
        # there is an entry for said path, then we append it to
        # it. Otherwise we create a new one.
        # As a result, we only create a testcase per directory that
        # has entries for each .t file in the directory.
        dir_name = os.path.dirname(path)
        if dir_name in cls.paths:
            # there is a testcase for this directory already, append
            # the .t
            tc = cls.paths[dir_name]
            tc.t_files.append(path)
            tc.report_info("%s will be run by %s" % (file_name, dir_name),
                           dlevel = 3)
        else:
            # there is no testcase for this directory, go create it;
            # set the full filename as origin.
            tc = cls(dir_name, path)
            cls.paths[dir_name] = tc
        return [ tc ]
