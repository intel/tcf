#! /usr/bin/python3
"""
Misc common lint checks
"""
import contextlib
import logging
import os
import pty
import re
import subprocess

def lint_run_gitlint(repo, cf):
    """
    Run gitlint on the commit message
    """
    log = logging.getLogger("gitlint")
    if cf != None:	# We only operate on the whole repository
        return
    # If we are checking on the working tree (not HEAD), then there
    # will be no commit message (FIXME: fix to enable pre-commit hook)
    if repo.is_dirty(untracked_files = False):
        log.warning("Skipping gitlint, repo is dirty so there is "
                    "no commit message")
        return

    #
    # Verify commit message
    #
    # Dear person who wrote gitlint: making it behave differently and take
    # stuff on stdin when non-interactive without silentily ignoring
    # --commits? Not cool. Wasted my Friday. And a Tuesday. Love.

    # to workaround that we give a PTY that we won't use.

    try:
        master, slave = pty.openpty()
        @contextlib.contextmanager
        def _fdclosing(fd):
            yield
            os.close(fd)
        with _fdclosing(master), _fdclosing(slave):
            cmdline = [
                'gitlint',
                '--target',
                repo.working_tree_dir
            ]
            log.debug("Running %s", " ".join(cmdline))
            output = subprocess.check_output(cmdline,
                                             stdin = slave,
                                             stderr = subprocess.STDOUT,
                                             universal_newlines = True)
    except FileNotFoundError:
        repo.blockage("Can't find gitlint?")
        return
    except subprocess.CalledProcessError as e:
        output = e.output

    if output:
        repo.message("""\
E: your commit message needs fixing, see https://securewiki.ith.intel.com/display/timo/Coding+Style+and+procedures#CodingStyleandprocedures-Submittingcode
   Use gitlint to verify it locally before submitting.
   See https://jorisroovers.github.io/gitlint/rules/ for explanations
   on what gitlint is complaining about.
""")
        for line in output.splitlines():
            repo.error("   " + line)


def lint_ws_at_eol(_repo, cf):
    """
    Warn if we find that any line of text the commit modified
    finish with whitespace.
    """
    if not cf or cf.binary or cf.deleted:
        return
    with open(cf.name, "r") as f:
        # Heaven's sake, indexes start at zero ZERO ZERO
        # https://i.imgur.com/zAjk1xs.jpg ... but most
        # tools report line numbers as index 1, so we do it like them
        line_cnt = 1
        regex = re.compile(r".*\s+$")
        for line in f.readlines():
            line = str.rstrip(line, "\n")
            if regex.match(line):
                if line_cnt in cf.lines or _repo.wide:
                    _repo.warning("%s:%d: W: whitespace at end of line"
                                  % (cf.name, line_cnt))
            line_cnt += 1
