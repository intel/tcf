"""
Script for gathering os specific requirements for setup files
"""
#!/usr/bin/python
# TODO: Add support for distro versions

import argparse
import glob
import re

parser = argparse.ArgumentParser()
parser.add_argument("-a", "--all", action='store_true',
                    help="install all dependencies not just required")
parser.add_argument("-m", "--manual", action='store_true',
                    help="manual requirements installation")
parser.add_argument("-f", "--file", default="setup.cfg",
                    help="path to .cfg file")
parser.add_argument("-d", "--distro", default="fedora")

args = vars(parser.parse_args())
path, _, _ = args["file"].rpartition('/')
if not path:
    path = "."

distro = args["distro"]
# Pattern for distro specific requirements
pattern = distro + r"[a-zA-Z0-9\_\-,]*\:?(?P<package>[a-zA-Z0-9\_\-,]+)"
# Pattern for general requirements
pattern_general = r"[a-zA-Z0-9\_\- ]+# (?P<package>[a-zA-Z0-9\_\-,]+)(?:\||$)"
filenames = []
packages = []

# If all is selected, include all requirements files
if args["all"]:
    filenames = glob.glob(path + '/requirements*.txt')
else:
    filenames += [path + '/requirements.txt']

# Parse the package requirements from the requirements file
try:
    for filename in filenames:
        with open(filename, 'r') as f:
            for line in f:
                result = re.search(pattern, line)
                if result:
                    packages += result.group("package").split(",")
                else:
                    result_general = re.search(pattern_general, line)
                    if result_general:
                        packages += result_general.group("package").split(",")
except FileNotFoundError:
    print("No reqirements file found: '%s'" % filename)

# Remove duplicates and order alphabetically
packages = sorted(set(packages))

# If not manually installing requirements, set requirements in config file
if not args["manual"]:
    with open(args['file'] + '.in', 'r') as f:
        data = f.read()

    data = data.replace('{{requirements}}', '\n    '+'\n    '.join(packages))

    with open(args['file'], 'w') as f:
        f.write(data)
