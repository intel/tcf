#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# test with
#
# Not yet working ok with bundles/os-clr-on-clr, but the thing is not even printing anything, can't tell?
#
# BBT_IGNORE_TS=bbt.git/bundles/os-core-update/bat-clr-boot-manager.t bundles/os-core-update/bat-clr-boot-manager.t
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
of :class:`subcases <tcfl.tc.subtc_c>`) which will report the
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
import tcfl.tc
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
    plan_max = 0
    tc = None
    for line in output.split("\n"):
        linecnt += 1
        m = tc_plan.search(line)
        if m:
            if plan_set_at and _plan_count > plan_max:
                # only complain if we have not completed it, otherwise
                # consider it spurious and ignore
                continue
            if plan_set_at:
                raise tcfl.tc.blocked_e(
                    "%d: setting range, but was already set at %d"
                    % (linecnt, plan_set_at),
                    dict(output = output, line = line))
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

#: Ignore t files
#:
#: List of individual .t files to ignore, since we can't filter
#: those on the command line; this can be done  in a :ref:`config file
#: <tcf_client_configuration>`:
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
#
# Note we don't care if we re under a multiprocess (vs multithread)
# environment, as long as we have a single copy
#
# GLOBAL!!!?? yes, because this is set from the environment's
# BBT_IGNORE_TS, so it works for all testcases 
ignore_ts_mutex = threading.Lock()
ignore_ts_regex = None

#: How long to wait for the BBT run to take?
#:
#: Each test case might take longer or shorter to run, but there is no
#: good way to tell. Thus we hardcode some by bundle name or by .t
#: name.
#:
#: More settings can be added from configuration by adding to any
#: :ref:`TCF configuration file <tcf_client_configuration>` entries
#: such as:
#:
#: >>> tcfl.tc_clear_bbt.bundle_run_timeouts['NAME'] = 456
#: >>> tcfl.tc_clear_bbt.bundle_run_timeouts['NAME2'] = 3000
#: >>> tcfl.tc_clear_bbt.bundle_run_timeouts['NAME3'] = 12
#: >>> ...
#:
bundle_run_timeouts = {
    # Keep this list alphabetically sorted!
    'bat-desktop-kde-apps-gui.t': 800,
    'bat-desktop-kde-gui.t': 800,
    'bat-mixer.t': 3000,
    'bat-os-testsuite-phoronix.t': 600,
    'bat-os-utils-gui-dev-pkgconfig-compile.t': 400,
    'bat-perl-extras-perl-use_parallel.t': 20000,	# wth...
    'bat-R-extras-R-library_parallel.t': 480,
    'bat-xfce4-desktop-bin-help.t': 800,
    'bat-xfce4-desktop-gui.t': 800,
    'kvm-host': 480,
    'os-clr-on-clr': 640,
    'perl-basic': 480,
    'bat-perl-basic-perl-use_parallel.t': 1800,
    'perl-extras': 12000,    # 4k subcases, needs to be split to parallelize
    'quick-perms.t': 3000,
    'telemetrics': 480,
    'xfce4-desktop': 800,
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

# bundle_add_timeouts -> moved to tcfl.tl.py

#: Map bundle path names
#:
#: Ugly case here; this is a bad hack to work around another one.
#:
#: In some testcases, the *.t* file is an actuall shell script that
#: does some setup and then executes a real *.t* file, which has been
#: detected with different name while we scanned for subcases.
#:
#: So this allows us to map what we detect (the regex) to what bats is
#: then reported when running that hack (the replacement).
#:
#: Confusing.
#:
bundle_path_map = [
    # each entry is a regex that is matched and what is replaced with
    # re.sub()
    ( re.compile("^(.*bundles/os-clr-on-clr)/t"), r"\g<1>" )
]

#: Sometime this works in conjunction with :data:`bundle_path_map`
#: above, when a .t file is actually calling another one (maybe in
#: another directory, then you need an entry in
#: :data:`bundle_path_map`) to rename the directory to match the entry
#: of this one.
#:
#: .. admonition:: Example
#:
#:    In the hardcoded example, *bat-dev-tooling.t* is just doing
#:    something to prep and then exec'ing bats to run
#:    *t/build-package.t*.
#:
#:    So we need to map the directory *t* out and also rename the
#:    entry from *build-package.t/something* that would be found from
#:    scanning the output to what is expected from scanning the
#:    testcases in disk.
bundle_t_map = {
    'bat-dev-tooling.t.autospec_nano': 'build-package.autospec_nano',
}

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
         :class:`tcfl.tc.subtc_c`

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
        self.test_bundle_name = os.path.basename(path)
        self.bats_parallel = False

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
        target.report_pass("booted %s" % self.image)

        # allow remote access while running the testcase, in case we
        # need to poke around to monitor
        tcfl.tl.linux_ssh_root_nopwd(target)
        target.shell.run("systemctl restart sshd")
        target.shell.run(		# wait for sshd to fully restart
            # this assumes BASH
            "while ! exec 3<>/dev/tcp/localhost/22; do"
            " sleep 1s; done", timeout = 15)
        target.console.select_preferred()

        # Why this? because a lot of the test output can be confused
        # with a prompt and the prompt regex then trips on it and
        # everything gets out of sync
        target.shell.shell_prompt_regex = re.compile("BBT-PS1-PROMPT% ")
        target.shell.run(
            'export PS1="BBT-PS1-PROMPT% " # do a very simple prompt, ' \
            'difficult to confuse with test output')

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
        tcfl.tl.swupd_bundle_add(ic, target, bundles)

        # once the os-test-suite thing has been installed, then we can
        # test if bats supports parallelism
        output = target.shell.run(
            "bats --help | fgrep -q -- '--jobs' || echo N''O # supports -j?",
            output = True, trim = True)
        if 'NO' not in output:
            self.bats_parallel = True
            # Yeah, we could use `getconf _NPROCESSORS_ONLN`, but this
            # works, since we want to know how many processing units we
            # can give bats.
            target.shell.run("CPUS=$(grep -c ^processor /proc/cpuinfo)")

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
            for name, subtc in self.subtc.iteritems():
                if name.startswith(t_file):
                    subtc.result = tcfl.tc.result_c(0, 0, 0, 0, 1)
                    subtc.data = dict(result = "skipped")
                    subtc.update(
                        tcfl.tc.result_c(0, 0, 0, 0, 1),
                        "skipped due to configuration"
                        " (tcfl.tc_clear_bbt.ignore_ts or"
                        " BBT_IGNORE_TS environment)",
                        "")
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
            if self.bats_parallel and 'use_parallel' in t_file:
                # note we set CUPS in the target in start()
                parallel = "-j $CPUS"
            else:
                parallel = ""
            run_timeout = _bundle_run_timeout(self, self.test_bundle_name, t_file)
            output = target.shell.run(
                "bats --tap %s %s || echo FAILED''-%s"
                % (t_file, parallel, self.kws['tc_hash']),
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
                _name = commonl.name_make_safe(name.strip())
                tc_name = t_file + "." + _name
                if tc_name in bundle_t_map:
                    _tc_name = bundle_t_map[tc_name]
                    self.report_info("subtestcase name %s mapped to %s "
                                     "per configuration "
                                     "tcfl.tc_clear_bbt.bundle_t_map"
                                     % (tc_name, _tc_name))
                else:
                    _tc_name = tc_name
                subtc = self.subtc[_tc_name]
                if self._ts_ignore(subtc.name):
                    _result = tcfl.tc.result_c(0, 0, 0, 0, 1)
                    summary = "result skipped due to configuration " \
                        "(tcfl.tc_clear_bbt.ignore_ts or " \
                        "BBT_IGNORE_TS environment)"
                    log = data['output']
                else:
                    # translate the taps result to a TCF result, record it
                    _result = self.mapping[data['result']]
                    log = data['output']
                    summary = log.split('\n', 1)[0]
                subtc.update(_result, summary, log, )
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

    # the initial ['"] has to be part of the name, as otherwise it
    # mite strip parts that bats (the program) does consider...
    _regex_t_subcases = re.compile(
        r"^\s*@test\s+(?P<name>['\"].+['\"])\s+{.*", re.MULTILINE)

    def _scan_t_subcases(self, path, prefix):
        # we just create here the list of parameters we'll use to
        # create the subtestcase on every execution of the testcase
        # itself (done in configure_10 when the TC is executed). Read
        # that for reasons...
        with open(path) as tf:
            subcases = re.findall(self._regex_t_subcases, tf.read())
        for name in subcases:
            # here we need to be careful to treat the scanned name
            # exactly the same way the bats tool will do it, otherwise
            # when we scan them from the bats output, they won't match
            name = name.strip()
            # strip the simple or double quotes from the name
            # -> "Starting somethings --id=\"blah\""
            # <- Starting somethings --id=\"blah\"
            name = name[1:-1]
            # ok, now somethings might have been escaped with \...we
            # can ignore it, since we are not affected by it...
            # -> Starting somethings --id=\"blah\"
            # <- Starting somethings --id="blah"
            name = name.replace("\\", "")
            # strip here, as BATS will do too
            _name = commonl.name_make_safe(name.strip())
            logging.debug("%s contains subcase %s", path, _name)
            t_file_name = os.path.basename(path)
            # note we'll key on the .t file basename and the subtest name
            # inside the .t file, otherwise if two different .t files
            # in the dir have same subtest names, they'd override.
            # In _eval_one() we'll refer to this dict
            subcase_name = t_file_name + "." + _name
            self.subtc[subcase_name] = tcfl.tc.subtc_c(
                # testcase full name / unique ID
                prefix + t_file_name.replace(".t", "") + "." + _name,
                self.kws['thisfile'], self.origin,
                # parent
                self)

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
        srcdir_real_path = os.path.realpath(srcdir)
        for regex, replacement in bundle_path_map:
            match = regex.match(srcdir_real_path)
            if match:
                _srcdir = re.sub(regex, replacement, srcdir_real_path)
                logging.info("path '%s' mapped to '%s' per config "
                             "tcfl.tc_clear_bbt.bundle_path_map",
                             srcdir_real_path, _srcdir)
                break
        else:
            _srcdir = srcdir_real_path
        if _srcdir in cls.paths:
            # there is a testcase for this directory already, append
            # the .t
            tc = cls.paths[_srcdir]
            tc.t_files.append(os.path.basename(path))
            tc._scan_t_subcases(path, srcdir + "##")
            tc.report_info("%s will be run by %s" % (path, _srcdir),
                           dlevel = 3)
        else:
            # there is no testcase for this directory, go create it;
            # set the full filename as origin.
            tc = cls(srcdir, path)
            tc._scan_t_subcases(path, srcdir + "##")
            cls.paths[_srcdir] = tc

            # now, we will also run anything in the any-bundle
            # directory -- per directory, so we add it now, as we
            # won't be able to do it later FIXME this might make it
            # not work when we just point to a .t
            # any_bundle's are at ../../any-bundle from the
            # per-bundle directories where the .ts are.
            any_bundle_path = os.path.join(_srcdir, "..", "..", "any-bundle",
                                           "*.t")
            for any_t_file_path in glob.glob(any_bundle_path):
                tc._scan_t_subcases(any_t_file_path, srcdir + "##any-bundle/")

        return [ tc ]
