#! /usr/bin/python3
# pylint: disable = missing-docstring
"""\
Verifies a commit with TCF

Based on the commit content, determine which testcases have to be fed
to TCF.

The lint-all core will call lint_tcfverify_filter() first for each
file and we'll use that to add information to the *tcs* dictionary and
then return false for each file (we don't do file-level linting).

Then the filter is called for the whole tree (cf == None), then if
there is anything at the *tcs* dictionary, it'll return true, which
will tell the lint-all core to call the linting function
:function:`lint_tcfverify` for the whole tree--which just invokes TCF
with the parameters specified in the *tcs* dictionary.

To decice what we have to run, we pass each changed file through a
list of scanners; example in here is the Zephyr scanner only, but more
scanners can be added in other .lint.tcfXYZ.py scripts that will be
loaded by lint-all after loading this one (they need to sort after so
they are loaded after, otherwise it will fail)

FIXME:
- move to a single TCF call per dictionary entry, to avoid growing too
  big by mistake

"""
import collections
import glob
import logging
import os
import pprint
import subprocess
import tempfile

# Scanners
# look at .lint.tcfXXXX.py for example scanners
tcf_scanners = []

# Export the config to all of lint-all (with LINTER_config) for other
# modules to access so the can, for example, append scanners
tcf_config = {
    "scanners": tcf_scanners
}

# Test cases to run
# KEY = filename that caused this
# VALUE = dictionary:
#  reason (for clarity in messages)
#  spec (for tcf run -t SPEC )
#  target (for tcf run TCS)
tcs = collections.defaultdict(list)

# lint-all calls first the functions with the changed files (one by
# one), the filename in 'cf.name'. Then it calls with cf == None,
# meaning for all.
LINT_ALL_TCF_CMD = os.environ.get('LINT_ALL_TCF_CMD', 'tcf')

def lint_tcf_filter(_repo, cf):
    if not cf and tcs:
        # If called to check on the whole tree and when called before
        # for each file we have collected tcs, then we know we have to run
        return True

    # Run only for text files
    if not cf or cf.binary or cf.deleted:
        return False

    for scanner_fn in tcf_scanners:
        scanner_fn(tcs, _repo, cf)

def lint_tcf(repo, cf):
    # Run only when this function is called for the whole tree (not
    # for a single file) -- we have collected individual file info in
    # the function above to @tcs
    if cf:
        return
    if not tcs:
        repo.warning("TCF: couldn't figure out what to run")
        return
    repo.log.info("TCF verify change information:\n%s", pprint.pformat(tcs))

    warning_list = []
    # make a tmpdir to place report files and logs; it being context,
    # it will be all deleted when we exit the context where it is defined
    with tempfile.TemporaryDirectory(prefix = "lint.tcf.run.",
                                     dir = os.getcwd()) as tmpdir:
        try:
            if os.path.isabs(repo.relpath):
                cwd = '/'
            else:
                cwd = os.getcwd()

            # TCFCONFIG is deprecated
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
            for change, data_list in tcs.items():
                for data in data_list:
                    reason = data.get("reason", "(BUG: no reason)")

                    if 'spec' in data:
                        target_spec = "-t " + data["spec"] + " "
                        # We don't want to re-add it
                        if not target_spec in specs:
                            specs += [ target_spec ]
                            repo.log.warning("TCF: adding target filter '%s' "
                                             "because %s"
                                             % (target_spec, reason))
                        else:
                            repo.log.warning(
                                "TCF: not adding target filter '%s' "
                                "because %s because we already it"
                                % (target_spec, reason))

                    test = data.get("test", "")
                    if test != "":
                        # We don't want to re-add it
                        if not test in tests:
                            tests += [ data["test"] ]
                            repo.log.warning(
                                "TCF: adding testcase '%s' because %s"
                                % (test, reason))
                        else:
                            repo.log.warning(
                                "TCF: not adding testcase '%s' because %s as "
                                "we already have it" % (test, reason))

            cmdline += specs + tests
            repo.log.info("Running @%s: %s" % (cwd, " ".join(cmdline)))
            proc = subprocess.Popen(
                cmdline, stderr = subprocess.STDOUT, stdout = subprocess.PIPE,
                universal_newlines = True, cwd = cwd)
            for line in proc.stdout:
                if 'No targets available' in line:
                    warning_list.append("No targets could be found? "
                                        "TCF configured? export TCF_CMDLINE "
                                        "to point to it?")
                repo.message("   " + line.strip())
            proc.wait()
        except subprocess.TimeoutExpired:
            proc.kill()
        except FileNotFoundError:
            repo.blockage("Can't find tcf binary called '%s'" % cmdline[0])
            return
        for report_filename in glob.glob(tmpdir + "/report-*"):
            repo.error("TCF generated report %s" % report_filename)
            with open(report_filename,
                      encoding = 'utf-8', errors = 'replace') as fp:
                for line in fp:
                    repo.message("   " + line.strip())
        if proc.returncode:
            repo.message("TCF run reported errors")
        for warning in warning_list:
            repo.warning("TCF: warning: %s" % warning)
