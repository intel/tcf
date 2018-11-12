#! /usr/bin/python3
# pylint: disable = missing-docstring
import re
import __main__

regex = re.compile(r".*\.ya?ml$")

def lint_yamllint_filter(repo, cf):
    if not cf or cf.binary or cf.deleted:
        return False
    if regex.search(cf.name) == None:
        repo.log.info("%s: skipping, not a YAML path", cf.name)
        return False
    return True

def lint_yamllint(repo, cf):
    __main__.generic_line_linter(
        repo, cf, [ 'yamllint', '-f', 'parsable', '-s', cf.name ])
