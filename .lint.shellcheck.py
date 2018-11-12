#! /usr/bin/python3
# pylint: disable = missing-docstring
import re
import __main__

regex = re.compile(r".*\.(ba)?sh$")

def lint_shellcheck_filter(_repo, cf):
    if not cf or cf.binary or cf.deleted:
        return False
    if regex.search(cf.name) == None:
        _repo.log.info("%s: ignoring, not a shell path", cf.name)
        return False
    return True

def lint_shellcheck(repo, cf):
    __main__.generic_line_linter(
        repo, cf,
        [ 'shellcheck', "-Cnever", "-a", "-x", '-fgcc', cf.name ],
        regex_error = re.compile(r":(?P<line_number>[0-9]+):[0-9]+: "
                                 r"(error): .*$"),
        regex_warning = re.compile(r":(?P<line_number>[0-9]+):[0-9]+: "
                                   r"(?:error): .*$")
    )
