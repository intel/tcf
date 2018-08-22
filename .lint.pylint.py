#! /usr/bin/python3
"""
Runs Python's lint under lint-all
"""
import logging
import os
import shutil
import re
import __main__

def lint_50_pylint(repo, cf):	# pylint: disable = too-many-branches
    if not cf or cf.binary or cf.deleted:
        return
    log = logging.getLogger("pylint")
    if not cf.name.endswith(".py"):
        log.info("%s: skipping, not a Python file", cf.name)
        return

    cmdline = [ 'pylint' ]
    with open(cf.name, 'r') as f:
        firstline = f.readline()
        if 'python3' in firstline:
            if shutil.which('python3-pylint'):
                cmdline = [ 'python3-pylint' ]
            elif shutil.which('pylint-3'):
                cmdline = [ 'pylint-3' ]
            elif shutil.which('pylint3'):
                cmdline = [ 'pylint3' ]
            else:
                repo.blockage("Can't find any Python 3 pylint?")
                return
        elif 'python2' in firstline:
            if shutil.which('python2-pylint'):
                cmdline = [ 'python2-pylint' ]
            elif shutil.which('pylint-2'):
                cmdline = [ 'pylint-2' ]
            elif shutil.which('pylint2'):
                cmdline = [ 'pylint2' ]
        else:
            cmdline = [ 'pylint' ]
    rcfile = os.path.join(repo.working_tree_dir, '.pylintrc')
    if os.path.exists(rcfile):
        cmdline.append('--rcfile=' + rcfile)
    cmdline += [
        '--reports=n',
        '--msg-template={path}:{line}: [{msg_id}({symbol}), {obj}] {msg}',
        cf.name
    ]

    __main__.generic_line_linter(
        repo, cf, cmdline, log,
        regex_error = re.compile(r":(?P<line_number>[0-9]+): \[E[0-9]+\("),
        regex_warning = re.compile(
            r":(?P<line_number>[0-9]+): \[[WCR][0-9]+\(")
    )
