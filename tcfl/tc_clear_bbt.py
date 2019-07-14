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

import datetime
import logging
import glob
import threading
import os
import re
import subprocess
import time

import commonl
import tcfl
import tcfl.pos
import tcfl.tl

logger = logging.getLogger("tcfl.tc_clear_bbt")

def tap_parse_output(output):
    """
    Parse `TAP
    <https://testanything.org/tap-version-13-specification.html>`_
    into a dictionary

    :param str output: TAP formatted output
    :returns: dictionary keyed by test subject containing a dictionary
       of key/values:
       - lines: list of line numbers in the output where data was found
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
    tc = None
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
            if tap_version < 12:
                raise RuntimeError("%d: Can't process versions < 12", linecnt)
            continue
        m = tc_output.search(line)
        if m:
            d = m.groupdict()
            if tc:
                tc['output'] += d['data'] + "\n"
                tc['lines'].append(linecnt)
            else:
                raise tcfl.tc.blocked_e(
                    "Can't parse output; corrupted? didn't find a header",
                    dict(output = output, line = linecnt))
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
    def __init__(self, name, tc_file_path, origin, parent):
        assert isinstance(name, basestring)
        assert isinstance(tc_file_path, basestring)
        assert isinstance(origin, basestring)
        assert isinstance(parent, tcfl.tc.tc_c)

        tcfl.tc.tc_c.__init__(self, name, tc_file_path, origin)
        self.tc_file_path = tc_file_path
        self.parent = parent
        self.kw_set('tc_name_short', name)
        self.result = None
        self.data = dict()

    def update(self, result, data):
        assert isinstance(data, dict)
        # create a result object with the data we parsed from the output
        self.result = result
        self.data = data

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
        if self.result == None:
            self.result = self.parent.result
            self.result.report(
                self, "subcase didn't run; parent didn't complete execution?",
                dlevel = 2, attachments = self.data)
        else:
            self.result.report(
                self, "subcase reported '%s'" % self.data['result'],
                dlevel = 2, attachments = self.data)
        return self.result

    @staticmethod
    def clean():		# pylint: disable = missing-docstring
        # Nothing to do, but do it anyway so the accounting doesn't
        # complain that nothing was found to run
        pass

#: Ignore t files
#:
#: List of individual .t files to ignore, since we can't filter
#: those on the command line; this can be done  in a config file:
#:
#: >>> tcfl.tc_clear_bbt.ignore_ts = [
#: >>>     'bundles/XYZ/somefile.t',
#: >>>     'bundles/ABC/someother.t',
#: >>>     '.*/any#somefile.sometestcase",
#: >>> ]
#:
#: or from the command line, byt setting the BBT_IGNORE_TS
#: environment variable::
#:
#:   $ export BBT_IGNORE_TS="bundles/XYZ/somefile.t #bundles/ABC/someother.t .*/any#somefile.sometestcase"
#:   $ tcf run bbt.git/bundles/XYZ bbt.git/bundles/ABC
#:
#: Note all entries will be compiled as Python regular expressions
#: that have to match from the beginning. A whole .t file can be
#: excluded with:
#:
#: >>>     'bundles/XYZ/somefile.t'
#:
#: where as a particular testcase in said file:
#:
#: >>>     'bundles/XYZ/somefile.subcasename'
#:
#: note those subcases still will be executed (there is no way for the
#: *bats* tool to be told to ignore) but their results will be ignored.
ignore_ts = os.environ.get("BBT_IGNORE_TS", "").split()

# read / write only under the mutex -- the mutex is used just to read
# it and the first person that sees it None, will re.compile() each
# entry to ignore_ts_regex, then release the mutex. So it is
# guaranteed that if you take the mutex, read it and not None, it'll
# be a valid list you can use without the mutex.
# Note we don't care if we re under a multiprocess (vs multithread)
# environment, as long as we have a single copy
ignore_ts_mutex = threading.Lock()
ignore_ts_regex = None

# This is now a hack because we don't have a good way to tell which
# bundles take longer or not from the bundle itself, so for no we'll
# hardcode it FIXME
bundle_run_timeouts = {
    'kvm-host': 480,
    # size
    'os-clr-on-clr': 640,
    'perl-basic': 480,
    'telemetrics': 480,
    # time?
    'xfce4-desktop': 480,
    'bat-xfce4-desktop-gui.t': 480,

    # Needs way more time, more if the machine is slow ... way, about
    # 16 min, 4k subcases this FIXME has to be split so it can be
    # parallelized
    'bat-perl-extras-perl-use.t': 1500,
    'bat-os-testsuite-phoronix.t': 600,
    'bat-mixer.t': 480,
}

#: Commands to execute before running bats on each .t file (key by .t
#: file name or bundle-under-test name).
#:
#: Note these will be executed in the bundle directory and templated
#: with ``STR % testcase.kws``.
bundle_run_pre_sh = {
    'bat-perl-basic-perl-use.t': [
        "export PERL_CANARY_STABILITY_NOPROMPT=1",
    ]
}

# FIXME: This has to be put in the tl.swupd_bundle_add helper too and
# be configurable
bundle_add_timeouts = {
    'desktop': 480,
    'desktop-autostart': 480,
    'os-clr-on-clr': 1000,		# this is seriously big
    'os-testsuite-phoronix': 1000,
    'os-testsuite-phoronix-server': 1000,
    'os-testsuite-phoronix-desktop': 1000,	# very big
}


def _bundle_add_timeout(tc, bundle_name, test_name):
    timeout = 240
    if bundle_name in bundle_add_timeouts:
        timeout = bundle_add_timeouts[bundle_name]
        tc.report_info("adjusting timeout to %d per "
                       "configuration tcfl.tc_clear_bbt.bundle_add_timeouts"
                       % timeout)
    if test_name in bundle_add_timeouts:
        timeout = bundle_add_timeouts[test_name]
        tc.report_info("adjusting timeout to %d per "
                       "configuration tcfl.tc_clear_bbt.bundle_add_timeouts"
                       % timeout)
    return timeout

def _bundle_run_timeout(tc, bundle_name, test_name):
    timeout = 240
    if bundle_name in bundle_run_timeouts:
        timeout = bundle_run_timeouts[bundle_name]
        tc.report_info("adjusting timeout to %d per "
                       "configuration tcfl.tc_clear_bbt.bundle_run_timeouts"
                       % timeout)
    if test_name in bundle_run_timeouts:
        timeout = bundle_run_timeouts[test_name]
        tc.report_info("adjusting timeout to %d per "
                       "configuration tcfl.tc_clear_bbt.bundle_run_timeouts"
                       % timeout)
    return timeout


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
        self.t_files = [ os.path.basename(t_file_path) ]
        self.deploy_done = False
        self.subtc_list = []
        self.subtcs = {}
        self.test_bundle_name = os.path.basename(path)

    #: Shall we capture a boot video if possible?
    capture_boot_video_source = "screen_stream"

    def configure_00_set_relpath_set(self, target):
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

        if self.capture_boot_video_source + ":" \
           not in target.kws.get('capture', ""):
            self.capture_boot_video_source = False

    # Because of unfortunate implementation decissions that have to be
    # revisited, we need to initialize the list of
    # sub-testcases here.
    #
    # Why? because once we create an instance of this testcase,
    # instead of creating a new one for each target it has to run on
    # in tcfl.tc.tc_c._run_on_targets(), we deepcopy() it in
    # _clone(). So the constructor is never called again -- yeah, that
    # has to change.
    def configure_10(self):	# pylint: disable = missing-docstring
        for key, name, tc_file_path, origin in self.subtc_list:
            # note how we parent it to self, not subtcs's
            # parent--because that'll be someone else. @self is the
            # current running TC that this parents these guys
            self.subtcs[key] = tc_taps_subcase_c_base(name, tc_file_path,
                                                      origin, self)
            self.post_tc_append(self.subtcs[key])
        if self.subtcs:
            self.report_pass("NOTE: this testcase will unfold subcases: %s" %
                             " ".join(self.subtcs.keys()), dlevel = 1)
        else:
            self.report_pass("NOTE: this testcase does not provide subcases",
                             dlevel = 1)

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
    #: >>> tcfl.tc_clear_bbt.tc_clear_bbt_c.mapping['skip'] \
    #: >>>      = tcfl.tc.result_c(1, 0, 0, 0, 0)	# pass
    #:
    #: or for an specific testcase:
    #:
    #: >>> tcobject.mapping['skip'] = 'BLCK'
    #:
    mapping = {
        'ok': tcfl.tc.result_c(1, 0, 0, 0, 0),
        'not ok': tcfl.tc.result_c(0, 0, 1, 0, 0),
        'skip': tcfl.tc.result_c(0, 0, 0, 0, 1),
        'todo': tcfl.tc.result_c(0, 1, 0, 0, 0),
    }

    #:
    #: Disable efibootmgr and clr-boot-manager
    #:
    boot_mgr_disable = os.environ.get("BBT_BOOT_MGR_DISABLE", False)

    #: if environ SWUPD_FIX_TIME is defined, set the target's time to
    #: the client's time
    fix_time = os.environ.get("SWUPD_FIX_TIME", None)
    
    def _deploy_bbt(self, _ic, target, _kws):
        # note self.bbt_tree and self.rel_path_in_target are set by
        # configure_00_set_relpath_set(); this way if we call withtout
        # deploying, we still have them

        target.shell.run("mkdir -p /mnt/persistent.tcf.d/bbt.git\n"
                         "# now copying the BBT tree from the client")

        # try rsyncing a seed bbt.git repo from -- this speeds up
        # first time transmisisons as the repo is quite close in the
        # server; further rsync from the local version in the client
        target.report_info("POS: rsyncing bbt.git from %(rsync_server)s "
                           "to /mnt/persistent.tcf.git/bbt.git" % _kws,
                           dlevel = -1)
        target.shell.run("time rsync -cHaAX --exclude '.git/*' --numeric-ids"
                         " %(rsync_server)s/misc/bbt.git"
                         " /mnt/persistent.tcf.d/"
                         " || echo FAILED-%(tc_hash)s"
                         % _kws)
        target.report_info("POS: rsynced bbt.git from %(rsync_server)s "
                           "to /mnt/persistent.tcf.d/bbt.git" % _kws)

        target.pos.rsync(self.bbt_tree, dst = '/opt/', path_append = "",
                         rsync_extra = "--exclude '.git/*'")
        # BBT checks will complain about the metadata file, so wipe it
        target.shell.run("rm -f /mnt/.tcf.metadata.yaml")
        if self.boot_mgr_disable:
            # FIXME: move this to configuration, check the binary
            # exits before disabling it, move this whole thing to the
            # deployment function
            bins_disable = [
                "/usr/bin/efibootmgr",
                "/usr/bin/clr-boot-manager",
            ]
            target.shell.run(r"""
cat > /mnt/usr/bin/tcf-disabled <<EOF
#! /bin/sh
# stub for a binary disabled by TCF for the system's good
echo "\$(basename \$0): DISABLED by TCF's tc_clear_bbt.py" 1>&2
echo "\$(basename \$0): called by" 1>&2
ps axf  1>&2
exit 1	# FAIL, on purpose--you are not allowed to run this
EOF
""")
            # tired of chasing ghosts who keep changing the EFI
            # bootorder, let's try this
            target.shell.run("chmod a+x /mnt/usr/bin/tcf-disabled")
            for binary in bins_disable:
                target.shell.run(
                    "/usr/bin/mv --force /mnt/%s /mnt/%s.disabled"
                    % (binary, binary))
                target.shell.run(
                    "/usr/bin/ln -sf"
                    " /usr/bin/tcf-disabled"
                    " /mnt/%s" % binary)


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
        # if we have video capture, get it to see if we are crashing
        # before booting
        if self.capture_boot_video_source:
            capturing = True
            target.capture.start(self.capture_boot_video_source)
        else:
            capturing = False
        target.pos.boot_normal()
        try:
            target.shell.up(user = 'root')
            if capturing:
                target.capture.stop(self.capture_boot_video_source)
        except:
            if capturing:
                # done booting, get the boot sequence movie, in case we
                # could record it
                target.capture.get(self.capture_boot_video_source,
                                   self.report_file_prefix + "boot.avi")
            raise
        target.report_pass("Booted %s" % self.image)

        # Why this? because a lot of the test output can be confused
        # with a prompt and the prompt regex then trips on it and
        # everything gets out of sync
        target.shell.shell_prompt_regex = re.compile("BBT-PS1-PROMPT% ")
        target.shell.run(
            'export PS1="BBT-PS1-PROMPT% " # do a very simple prompt, ' \
            'difficult to confuse with test output')

        if self.fix_time:
            target.shell.run(
                "date -us '%s' && hwclock -wu"
                % str(datetime.datetime.utcnow()))
        
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
        for bundle in bundles:
            if self.swupd_debug:
                debug = "--debug"
            else:
                debug = ""
            count = 0
            top = 10
            add_timeout = _bundle_add_timeout(self, self.test_bundle_name, bundle)
            for count in range(1, top + 1):
                # We use -p so the format is the POSIX standard as
                # defined in
                # https://pubs.opengroup.org/onlinepubs/009695399/utilities/time.html
                # STDERR section
                output = target.shell.run(
                    "time -p swupd bundle-add %s %s || echo FAILED''-%s"
                    % (debug, bundle, self.kws['tc_hash']),
                    output = True, timeout = add_timeout)
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
            self.targets_active(target)

    def _ts_ignore(self, subtcname):
        global ignore_ts_regex
        with ignore_ts_mutex:
            if ignore_ts_regex == None:
                # ops, list not compiled, let's do it under the mutex
                # so none steps on us
                ignore_ts_regex = []
                count = 0
                for spec in ignore_ts:
                    try:
                        ignore_ts_regex.append(re.compile(spec))
                    except:
                        self.log.error("#%d: can't compile '%s' as a regex"
                                       % (count, spec))
                        raise
                    count += 1
        for spec in ignore_ts_regex:
            if spec.match(subtcname):
                return True
        return False

    def _eval_one(self, target, t_file, prefix):
        result = tcfl.tc.result_c(0, 0, 0, 0, 0)
        rel_file_path = os.path.join(prefix, t_file)
        if self._ts_ignore(rel_file_path):
            target.report_skip(
                "%s: skipped due to configuration "
                "(tcfl.tc_clear_bbt.ignore_ts or BBT_IGNORE_TS environment)"
                % rel_file_path)
            for name, subtc in self.subtcs.iteritems():
                if name.startswith(t_file):
                    subtc.result = tcfl.tc.result_c(0, 0, 0, 0, 1)
                    subtc.data = dict(result = "skipped")
            result.skipped += 1
        else:
            self.report_info("running %s%s" % (prefix, t_file))
            self.kw_set("t_file", t_file)

            # patch any execution hot fixes
            pre_sh_l = []
            if self.test_bundle_name in bundle_run_pre_sh:
                self.report_info("adding configured pre_sh steps from "
                                 "tcfl.tc_clear_bbt.bundle_run_pre_sh[%s]"
                                 % self.test_bundle_name)
                pre_sh_l += bundle_run_pre_sh[self.test_bundle_name]
            if t_file in bundle_run_pre_sh:
                self.report_info("adding configured pre_sh steps from "
                                 "tcfl.tc_clear_bbt.bundle_run_pre_sh[%s]"
                                 % t_file)
                pre_sh_l += bundle_run_pre_sh[t_file]
            for pre_sh in pre_sh_l:
                target.shell.run(pre_sh % self.kws)

            # Run the t_file
            # remember we cd'ed into the directory, the way these
            # BBTs are written, it is expected
            run_timeout = _bundle_run_timeout(self, self.test_bundle_name, t_file)
            output = target.shell.run(
                "bats --tap %s || echo FAILED''-%s"
                % (t_file, self.kws['tc_hash']),
                output = True, timeout = run_timeout)
            # top level result
            if 'bats: command not found' in output:
                self.report_error(
                    "'bats' tool not installed in the target",
                    dict(target = target, output = output))
                result.errors += 1
            elif 'FAILED-%(tc_hash)s' % self.kws in output:
                result.failed += 1
            else:
                result.passed += 1

            # seems we had execution, so let's parse the output and
            # make subcases of the .t -- if anything fails, catch and
            # convert to a TCF exception so it only affects *this*
            # testcase in the result accounting--note
            # report_from_exception() will report exceptio data so we
            # can debug if it is an infra or TC problem.
            try:
                tcs = tap_parse_output(output)
            except Exception as e:
                tcs = dict()
                result += tcfl.tc.result_c.report_from_exception(self, e)
            for name, data in tcs.iteritems():
                # get the subtc; see _scan_t_subcases() were we keyed
                # them in
                _name = commonl.name_make_safe(name.strip()).rstrip("_")
                tc_name = t_file + "." + _name
                subtc = self.subtcs[tc_name]
                if self._ts_ignore(subtc.name):
                    data['result'] += \
                        "result skipped due to configuration " \
                        "(tcfl.tc_clear_bbt.ignore_ts or " \
                        "BBT_IGNORE_TS environment)"
                    subtc.update(tcfl.tc.result_c(0, 0, 0, 0, 1), data)
                else:
                    # translate the taps result to a TCF result, record it
                    subtc.update(self.mapping[data['result']], data)
                result += subtc.result
        return result

    def eval(self, ic, target):

        tcfl.tl.sh_export_proxy(ic, target)
        # testcases assume they are running from the same
        # directory where the .t is.
        target.shell.run("cd /opt/bbt.git/%s" % self.rel_path_in_target)
        result = tcfl.tc.result_c(0, 0, 0, 0, 0)
        # Now run all the .t in the directory, we discovered them when
        self.report_info("will run t_files %s" % " ".join(self.t_files),
                         dlevel = 1)

        srcdir = os.path.join(self.kws['srcdir'])
        for t_file in sorted(self.t_files):
            result += self._eval_one(target, t_file, srcdir + "/")

        # we scan for 'any' bundle testcases in the local FS, which we
        # know we have copied to the remote:
        target.shell.run("cd /opt/bbt.git/any-bundle")
        for any_t_file_path in glob.glob(os.path.join(
                os.path.dirname(self.kws['thisfile']),
                "..", "..", "any-bundle", "*.t")):
            any_t_file = os.path.basename(any_t_file_path)
            result += self._eval_one(target, any_t_file, srcdir + "/any#")

        return result

    def teardown_50(self):
        tcfl.tl.console_dump_on_failure(self)

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

    _regex_t_subcases = re.compile(
        r"^\s*@test\s+['\"](?P<name>.+)['\"]\s+{.*", re.MULTILINE)

    def _scan_t_subcases(self, path, prefix):
        # we just create here the list of parameters we'll use to
        # create the subtestcase on every execution of the testcase
        # itself (done in configure_10 when the TC is executed). Read
        # that for reasons...
        with open(path) as tf:
            subcases = re.findall(self._regex_t_subcases, tf.read())
        for name in subcases:
            # make sure to remove leading/trailing whitespace and then
            # trailing _--this allows it to match what the bats tool
            # scans, which we'll need to match in the output of
            # tap_parse_output() in _eval_one()
            _name = commonl.name_make_safe(name.strip()).rstrip("_")
            t_file_name = os.path.basename(path)
            self.subtc_list.append((
                # note we'll key on the .t file basename and the subtest name
                # inside the .t file, otherwise if two different .t files
                # in the dir have same subtest names, they'd override.
                # In _eval_one() we'll refer to this dict
                # We keep this, even if is basically the same because
                # it will easily make configure_10 later print a
                # shorter list for reference in reports...
                t_file_name + "." + _name,
                # testcase full name / unique ID
                prefix + t_file_name.replace(".t", "") + "." + _name,
                self.kws['thisfile'], self.origin
            ))

    @classmethod
    def is_testcase(cls, path, _from_path):
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
        srcdir = os.path.dirname(path)
        if srcdir in cls.paths:
            # there is a testcase for this directory already, append
            # the .t
            tc = cls.paths[srcdir]
            tc.t_files.append(os.path.basename(path))
            tc._scan_t_subcases(path, srcdir + "/")
            tc.report_info("%s will be run by %s" % (file_name, srcdir),
                           dlevel = 3)
        else:
            # there is no testcase for this directory, go create it;
            # set the full filename as origin.
            tc = cls(srcdir, path)
            tc._scan_t_subcases(path, srcdir + "/")
            cls.paths[srcdir] = tc

            # now, we will also run anything in the any-bundle
            # directory -- per directory, so we add it now, as we
            # won't be able to do it later FIXME this might make it
            # not work when we just point to a .t
            # any_bundle's are at ../../any-bundle from the
            # per-bundle directories where the .ts are.
            any_bundle_path = os.path.join(srcdir, "..", "..", "any-bundle",
                                           "*.t")
            for any_t_file_path in glob.glob(any_bundle_path):
                tc._scan_t_subcases(any_t_file_path, srcdir + "/any#")

        return [ tc ]
