#! /usr/bin/python3
# pylint: disable = missing-docstring
import logging
import re
import __main__

def lint_shellcheck(repo, cf):
    if not cf or cf.binary or cf.deleted:
        return
    regex = re.compile(r".*\.(ba)?sh$")
    log = logging.getLogger('shellcheck')
    if regex.search(cf.name) == None:
        log.info("%s: ignoring, not a shell path", cf.name)
        return

    __main__.generic_line_linter(
        repo, cf,
        [ 'shellcheck', "-Cnever", "-a", "-x", '-fgcc', cf.name ],
        log,
        regex_error = re.compile(r":(?P<line_number>[0-9]+):[0-9]+: "
                                 r"(error): .*$"),
        regex_warning = re.compile(r":(?P<line_number>[0-9]+):[0-9]+: "
                                   r"(?:error): .*$")
    )
