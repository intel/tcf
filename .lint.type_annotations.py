#! /usr/bin/python3
"""
Misc common lint checks
"""
import re

lint_type_annotation_py38_name = \
    "avoid using set|type|list[type] for py3.8 compat"

def lint_type_annotation_py38_filter(_repo, cf):
    if not cf or cf.binary or cf.deleted:
        return False
    return True

def lint_type_annotation_py38(_repo, cf):
    with open(cf.name, "r", errors = 'replace') as f:
        line_cnt = 1
        regex = re.compile(r"(:\s*(list|set|tuple)\[[^\[].+])")
        for line in f.readlines():
            line = str.rstrip(line, "\n")
            m = regex.search(line)
            if m:
                if line_cnt in cf.lines or _repo.wide:
                    _repo.error(
                        f"{cf.name}:{line_cnt}: E: avoid using annotation"
                        f" '{m.groups()[0]}' for python 3.8 compatibility")
            line_cnt += 1
