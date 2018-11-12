#! /usr/bin/python3
# pylint: disable = missing-docstring
import __main__

def scan_example(tcs, _repo, cf):
    cf.log.info("DEBUG example scanner called")

tcf_config = __main__.linter_config_get('tcf')
# FIXME: uncomment next line to enable it
#tcf_config['scanners'].append(scan_example)
