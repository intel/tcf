#!/usr/bin/python3
"""
Script for gathering os specific requirements for setup files
"""

import argparse
import re
import sys

parser = argparse.ArgumentParser()
parser.add_argument("-c", "--config", required=False,
                    help="path to config files")
parser.add_argument("-d", "--distro", required=False)
parser.add_argument("-v", "--version", required=False)
parser.add_argument("--nodistro", required=False, action="store_true")
parser.add_argument("filenames", metavar="file", type=str, nargs="+",
                    help="requirements file(s)")

args = vars(parser.parse_args())

# Pattern for finding the distro name
pattern_distro = r"^ID=\"?(?P<distro>[a-z]+)\"?"
filenames = []
packages = []
no_distro_packages = []

distro = args["distro"]
version = args["version"]
# if distro not set, find the distro through /etc/os-release
if not distro:
    with open("/etc/os-release", "r") as f:
        while not distro:
            line = f.readline()
            result_distro = re.search(pattern_distro, line)
            if result_distro:
                distro = result_distro.group("distro")
                print("I: /etc/os-release: distro to be %s" % distro,
                      file = sys.stderr)
    if not distro:
        sys.exit("Cannot locate distro name, set manually with '-d'")

if version:
    # Pattern for version specific requirements
    pattern_version = distro + r":" + version \
                    + r"[a-zA-Z0-9\_\-,]*\=?(?P<package>[a-zA-Z0-9\_\-\+,]+)"
# Pattern for distro specific requirements
pattern = distro + r"[a-zA-Z0-9\_\-,]*\=?(?P<package>[a-zA-Z0-9\_\-\+,]+)"
# Pattern for general requirements
pattern_general = r"# package: (?P<package>[a-zA-Z0-9\_\-\+,]+)" \
                  + r"(?: [a-zA-Z0-9\_\-,]+|$)"
# Pattern for requirements without distro packages
pattern_nodistro = r"^(?P<package>[a-zA-Z0-9\_\-\=\.\+]+) *(\# package\: )?(?!" \
                   + distro + r"|\=)*"

# Parse the package requirements from the requirements file
try:
    for filename in args["filenames"]:
        with open(filename, 'r') as f:
            for line in f:
                if version:
                    result_version = re.search(pattern_version, line)
                    if result_version:
                        packages += result_version.group("package").split(",")
                        continue

                result = re.search(pattern, line)
                if result:
                    packages += result.group("package").split(",")
                    continue

                result_general = re.search(pattern_general, line)
                if result_general:
                    packages += result_general.group("package").split(",")
                    continue

                if re.search(pattern_nodistro, line):
                    no_distro_packages.append(line.split(" ")[0].strip())

except FileNotFoundError:
    print("E: No requirements file found: '%s'" % filename, file = sys.stderr)

# Remove duplicates and order alphabetically
packages = sorted(set(packages))

# If not manually installing requirements, set requirements in config file
if args["config"]:
    with open(args["config"] + ".in", "r") as f:
        data = f.read()

    data = data.replace("{{requirements}}", "\n    " + "\n    ".join(packages))

    with open(args["config"], "w") as f:
        f.write(data)
elif args["nodistro"]:
    print("\n".join(no_distro_packages))
else:
    print("\n".join(packages))
