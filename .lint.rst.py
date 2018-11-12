#! /usr/bin/python3
# pylint: disable = missing-docstring
import re
import restructuredtext_lint
import __main__

regex = re.compile(r".*\.rst$")

def lint_rst_filter(repo, cf):
    if not cf or cf.binary or cf.deleted:
        return False
    if regex.search(cf.name) == None:
        repo.log.info("%s: skipping, not a REST file", cf.name)
        return False
    return True

def lint_rst(repo, cf):
    msgs = restructuredtext_lint.lint_file(cf.name)
    for msg in msgs:
        if msg.line == None:
            line = 0
        else:
            line = msg.line
        if msg.level >= 3:
            cf.error("%s:%d: %s: %s" % (cf.name, line, msg.type, msg.message),
                     line)
        else:
            cf.warning("%s:%d: %s: %s" % (cf.name, line, msg.type, msg.message),
                       line)
