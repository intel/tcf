#! /usr/bin/python3
# pylint: disable = missing-docstring
"""
Verifies a contribution to the Zephyr OS with TCF

"""
import glob
import logging
import os
import pprint
import subprocess
import tempfile

# Test cases to run
# KEY = filename that caused this
# VALUE = dictionary:
#  reason (for clarity in messages)
#  spec (for tcf run -t SPEC )
#  target (for tcf run TCS)
tcs = {}

# lint-all calls first the functions with the changed files (one by
# one), the filename in 'cf.name'. Then it calls with cf == None,
# meaning for all.

ZEPHYR_BASE = os.environ.get('ZEPHYR_BASE', None)
ZEPHYR_PATHS = os.environ.get('ZEPHYR_PATHS', "").split()
LINT_ALL_TCF_CMD = os.environ.get('LINT_ALL_TCF_CMD', 'tcf')

log = logging.getLogger("zephyr-tcfverify")

def lint_zephyr_tcfverify_collect_info(_repo, cf):
    # Run only when this function is called for a single changed file
    # (cf) to collect information
    if cf == None:
        return
    abspath = os.path.abspath(cf.name)
    # lame check
    if not ZEPHYR_BASE:
        log.info("%s: skipping ZEPHYR_BASE not exported", cf.name)
        return
    for base in [ ZEPHYR_BASE ] + ZEPHYR_PATHS:
        if base in abspath:
            log.info("%s: considering because there is a base path from "
                     "ZEPHYR_BASE or ZEPHYR_PATHS (%s) in file's path (%s)",
                     cf.name, base, abspath)
            break
    else:
        log.info("%s: skipping because there is not ZEPHYR_BASE (%s) in "
                 "file's path (%s)", cf.name, ZEPHYR_BASE, abspath)
        return

    basename = os.path.basename(cf.name)
    if basename in [ "testcase.ini", "testcase.yaml", "sample.yaml" ] \
       or (basename.endswith(".py") and basename.startswith("test")):
        tcs[cf.name] = dict(
            reason = "found modified TC file %s" % cf.name)
    # tests/samples/quark_boards/XYZ.json old JSON format for
    # describing samples
    if 'tests/samples/quark_boards' in cf.name and basename.endswith(".json"):
        tcs[cf.name] = dict(
            reason = "found modified JSON file %s" % cf.name,
            rest = cf.name)

    path_parts = os.path.relpath(cf.name, ZEPHYR_BASE).split("/")
    acc_parts = []
    # walk all the parts from ZEPHYR_BASE to the file and look for testcases
    for part in path_parts:
        acc_parts.append(part)
        check_path = os.path.join(*([ ZEPHYR_BASE ] + acc_parts))
        if os.path.exists(os.path.join(check_path, 'testcase.ini')) \
           or os.path.exists(os.path.join(check_path, 'testcase.yaml')) \
           or os.path.exists(os.path.join(check_path, 'sample.yaml')):
            tcs[cf.name] = dict(
                reason = "testcase/sample in path of modified file",
                test = os.path.relpath(check_path))

    # the file modifies an specific architecture?
    if cf.name.startswith('arch/'):
        # extract architecture name
        arch = cf.name.split('/')[1]
        # Verify this is really an arch name, not some file in 'arch/'
        if os.path.isdir(os.path.join(ZEPHYR_BASE, "arch", arch)):
            # Well, we are touching something in that arch, so we need
            # to run tests for it
            tcs[cf.name] = dict(
                reason = "tests/kernel has to run due to changes in arch/%s" \
                    % arch,
                spec = 'bsp == "%s"' % arch,
                test = "tests/kernel")

    # FIXME: do the same thing for boards/BOARDNAME/files and add
    # spec 'zephyr_board == BOARDNAME' as for arch

    if cf.name.startswith('subsys/'):
        subsys_dir = os.path.dirname(cf.name)
        tcs[cf.name] = dict(
            reason = "modified subsystem %s" % subsys_dir,
            test = 'tests/' + subsys_dir)
        # FIXME: need to do some work on subsys_dir, because the
        # change might be in subsys/SUBSYS/some1/some2/some3, but only
        # tests/subsys/SUBSYS/some1 will exist

    if cf.name.startswith('drivers/'):
        driver_dir = os.path.dirname(cf.name)
        tcs[cf.name] = dict(
            reason = "modified driver %s" % driver_dir,
            test = 'tests/' + driver_dir)




    # FIXME: do the same for kernel, lib, etc
    #
    # Note when modifying kernel/, we need to run testcases on all
    # arches and boards, so we also would need to add something to
    # counteract the case where there is a change in arch/x86/something
    # and kernel/something, so it runs not only on x86, but on all arches


def lint_zephyr_tcfverify_run(_repo, cf):
    # Run only when this function is called for the whole tree (not
    # for a single file) -- we have collected individual file info in
    # the function above
    if cf:
        return
    if not ZEPHYR_BASE:
        log.info("TCF: skipping ZEPHYR_BASE not exported")
        return
    if not tcs:
        log.error("TCF: couldn't figure out what to run")
        return
    log.info("TCF verify change information:\n%s", pprint.pformat(tcs))

    errors = 0
    tcf_servers = os.environ.get('TCF_SERVERS', "").split()
    if tcf_servers == "":
        log.warning("TCF_SERVERS empty, won't run anything on targets")

    warning_list = []
    # make a tmpdir to place report files and logs; it being context,
    # it will be all deleted when we exit the context where it is defined
    with tempfile.TemporaryDirectory(prefix = "lint.tcfverify.run.",
                                     dir = os.getcwd()) as tmpdir:
        try:
            if os.path.isabs(_repo.relpath):
                cwd = '/'
            else:
                cwd = os.getcwd()

            if 'TCFCONFIG' in os.environ:
                tcf_config = [ os.environ['TCFCONFIG'] ]
            else:
                tcf_config = []
            # split whatever is given in TCF_CMDLINE_ARGS with spaces and
            # pass that as command line arguments
            if 'TCF_CMDLINE_ARGS' in os.environ:
                tcf_config += os.environ['TCF_CMDLINE_ARGS'].split()
            tcf_run_cmdline_args = \
                os.environ.get('TCF_RUN_CMDLINE_ARGS', '').split()

            cmdline = [ LINT_ALL_TCF_CMD ] \
                      + tcf_config \
                      + [
                          "--traces",
                          "run",
                          "--tmpdir", os.environ.get('TMPDIR', tmpdir)
                      ] \
                      + tcf_run_cmdline_args
            specs = []
            tests = []
            for change, data in tcs.items():
                reason = data.get("reason", "(BUG: no reason)")
                if 'spec' in data:
                    spec = "-t " + data["spec"] + " "
                    specs += [ "-t", data["spec"] ]
                    _repo.message("%s:0: TCF: adding target filter '%s' "
                                  "because %s" % (change, spec, reason))
                else:
                    spec = ""
                if 'test' in data:
                    test = data.get("test", "")
                    tests += [ data["test"] ]
                    _repo.message("%s:0: TCF: adding testcase '%s' because %s"
                                  % (change, test, reason))
                else:
                    test = ""
            cmdline += specs + tests
            log.debug("running %s", cmdline)
            _repo.message("Running @%s: %s" % (cwd, " ".join(cmdline)))
            proc = subprocess.Popen(
                cmdline, stderr = subprocess.STDOUT, stdout = subprocess.PIPE,
                universal_newlines = True, cwd = cwd)
            for line in proc.stdout:
                if 'No targets available' in line:
                    warning_list.append("No targets could be found? "
                                        "TCF configuration? "
                                        "Export TCF_SERVERS?")
                _repo.message("   " + line.strip())
            proc.wait()
        except subprocess.TimeoutExpired:
            proc.kill()
        except FileNotFoundError:
            _repo.blockage("Can't find tcf? [%s]", cmdline[0])
            return
        for report_filename in glob.glob(tmpdir + "/report-*"):
            _repo.error("TCF generated report %s" % report_filename)
            with open(report_filename) as fp:
                for line in fp:
                    _repo.message("   " + line.strip())
        if proc.returncode:
            _repo.message("TCF run reported errors")
        for warning in warning_list:
            _repo.warning("TCF: warning: %s" % warning)
