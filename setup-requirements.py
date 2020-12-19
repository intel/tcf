#!/usr/bin/python
"""
Script for gathering os specific requirements for setup files
"""
# TODO: Add support for distro versions
# TODO: Add ability to list python packages with no distro package

import argparse
import glob
import re
import sys

parser = argparse.ArgumentParser()
parser.add_argument("-a", "--all", action='store_true',
                    help="install all dependencies not just required")
parser.add_argument("-c", "--config", action='store_true',
                    help="config requirements parsing")
parser.add_argument("-p", "--path", default="./",
                    help="path to requirements file")
parser.add_argument("-d", "--distro", required=False)
parser.add_argument("-v", "--version", required=False)

args = vars(parser.parse_args())
path = args["path"]

# Pattern for finding the distro name
pattern_distro = r"^ID=\"?(?P<distro>[a-z]+)\"?"
filenames = []
packages = []

distro = args["distro"]
# if distro not set, find the distro through /etc/os-release
if not distro:
    with open("/etc/os-release", "r") as f:
        while not distro:
            line = f.readline()
            result_distro = re.search(pattern_distro, line)
            if result_distro:
                distro = result_distro.group("distro")
    if not distro:
        sys.exit("Cannot locate distro name, set manually with '-d'")

# If all is selected, include all requirements files in folder
if args["all"]:
    filenames = glob.glob(path + '/requirements*.txt')
else:
    filenames += [path + '/requirements.txt']

# Pattern for distro specific requirements
pattern = distro + r"[a-zA-Z0-9\_\-,]*\:?(?P<package>[a-zA-Z0-9\_\-,]+)"
# Pattern for general requirements
pattern_general = r"^[a-zA-Z0-9\_\- \t]*" + \
                  r"# (?P<package>[a-zA-Z0-9\_\-,]+)(?:\||$)"

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
    print("No requirements file found: '%s'" % filename)

# Remove duplicates and order alphabetically
packages = sorted(set(packages))

# If not manually installing requirements, set requirements in config file
if args["config"]:
    with open(path + "setup.cfg.in", "r") as f:
        data = f.read()

    data = data.replace("{{requirements}}", "\n    " + "\n    ".join(packages))

    with open(path + "setup.cfg", "w") as f:
        f.write(data)
else:
    print(" ".join(packages))
