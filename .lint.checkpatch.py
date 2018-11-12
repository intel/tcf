#! /usr/bin/python3
import os
import re
import subprocess

# Run checkpatch for the lint-all tool; output:
#
# stdout: lines in the form FILE:LINENUMBER:message
# return: NUMBER-OF-ERRORS, WARNINGS, BLOCKAGES

regex_c = re.compile(r".*\.(c|C|cpp|CPP|h|HH|hxx|cxx)$")

lint_checkpatch_name = "checkpatch"

def lint_checkpatch(repo, cf):
    if cf:
        return

    for filename in repo.filenames:
        if regex_c.match(filename):
            break
    else:
        # No C or H files
        repo.log.info("not running, as there are no C/C++ files")
        return

    # Deployment specific -- dep on what the environment is saying
    # FIXME: what if ZEPHYR_BASE is generally defined in the
    # environment but we want to checkpatch with other settings?
    if 'ZEPHYR_BASE' in os.environ:
        # The typedefs flag has to be given here vs the config file so we
        # have access to the path to the Zephyr kernel tree
        flags_deployment = "--typedefsfile=" \
            "$ZEPHYR_BASE/scripts/checkpatch/typedefsfile"
        cmd = "$ZEPHYR_BASE/scripts/checkpatch.pl"
    else:
        flags_deployment = ""
        cmd = "checkpatch.pl"
        repo.warning("Using generic checkpatch (ZEPHYR_BASE undefined)")
        return

    checkpatch_flags = "--patch --showfile " \
                       "--no-summary --terse " \
                       + flags_deployment

    try:
        if repo.is_dirty(untracked_files = False):
            cmd = "set -o pipefail; " \
                  "git -C '%s' diff HEAD" \
                  "  | %s %s - 2>&1" \
                  % (repo.working_tree_dir, cmd, checkpatch_flags)
        else:
            cmd = "set -o pipefail; " \
                  "git -C '%s' format-patch --stdout HEAD~1 " \
                  "  | %s %s - 2>&1" \
                  % (repo.working_tree_dir, cmd, checkpatch_flags)
        # yeah, this is ugly...some versions of Ubuntu use not
        # bash as a default shell and we need pipefail--I bet
        # there is a better way to do it, but I am sleepy now
        cmdline = [ 'bash', '-c', cmd ]
        repo.log.debug("running %s", cmdline)
        output = subprocess.check_output(
            cmdline, stderr = subprocess.STDOUT, universal_newlines = True)
    except FileNotFoundError:
        repo.blockage("Can't find checkpatch? for Zephyr, export ZEPHYR_BASE")
        return
    except subprocess.CalledProcessError as e:
        output = e.output

    warnings = 0
    errors = 0
    if output:
        repo.message("E: checkpatch reports errors or warnings")
        regex = re.compile(":(?P<line_number>[0-9]+): (?P<kind>(ERROR|WARNING|CHECK)):")
        line_cnt = 0
        # checkpatch will always print the path relative to the origin
        # of the repository, so we complement so the output is
        # consistent
        if repo.relpath == ".":
            reldir = ""
        else:
            reldir = repo.relpath + "/"
        for line in output.splitlines():
            line_cnt += 1
            line = line.strip()
            m = regex.search(line)
            if not m:
                continue
            line_number = int(m.groupdict()['line_number'])
            kind = m.groupdict()['kind']
            if kind == 'WARNING' or kind == 'CHECK':
                repo.warning(reldir, line_number = line)
            elif kind == 'ERROR':
                repo.error(reldir, line_number = line)
            else:
                assert True, "Unknown kind: %s" % kind
