#! /usr/bin/python3
"""
Implement TCF specificy lints
"""
import logging
import re


log = logging.getLogger("tcfpylint")

def lint_py_check_per_line(_repo, cf):
    """
    Run multiple line-by-line checks
    """
    if not cf or cf.binary or cf.deleted:
        return
    if not cf.name.endswith(".py"):
        log.info('%s: skipping, not a python file', cf.name)
        return

    with open(cf.name, "r") as f:
        line_cnt = 0
        regex_import = re.compile(r"\s*from\s+.*\s+import\s+.*")
        warnings = 0
        for line in f:
            line_cnt += 1
            line = line.strip()
            if not line_cnt in cf.lines or _repo.wide:
                continue	# Not a line modified, skip it

            # Check that imports are not done with *from HERE import
            # THAT* because it makes code very confusing when we can't
            # see where functions are coming from
            m = regex_import.match(line)
            if m:
                _repo.warning("""\
%s:%d: python style error: use 'import MODULE' vs 'from MODULE import SYMBOLs'
    see https://securewiki.ith.intel.com/display/timo/Coding+Style+and+procedures#CodingStyleandprocedures-Importingcode"""
                      % (cf.name, line_cnt))
                warnings += 1

            # We like spacing around equal signs and operators in
            # general, the C way. The python way sucks. ARG OPERATOR
            # ARG beats ARGOPERATORARG. Ewks.

            # Likewise, [X] is an index, [ X ] is a list. Heaven's
            # sake. For consistency, dictionaries are { K: V }; it's
            # really had to check on those and a patch to pylint would
            # be needed for that.


            regex_bad_eqop = re.compile(r"\S(=|==|!=|\+=|-=|\*=|/=|\|=|&=|^=)\S")
            regex_config = re.compile("CONFIG_[^=]+=")
            # Catches things like blabla('--someswitch=', whatever) or
            # blabla("--something=that")
            regex_string = re.compile(r"=dd[^\s'\"]*['\"]")

            # Got a probable bad usage?
            m = regex_bad_eqop.search(line)
            if m:
                # Maybe a config assignment (this is actually shell code)
                if regex_config.search(line) or regex_string.search(line):
                    continue
                # Maybe rst code, ignore it
                if '===' in line:
                    continue
                _repo.warning("""\
%s:%d: python style error: always leave spaces around operators
    ('a = b' vs 'a=b')\
""" % (cf.name, line_cnt))
