#! /usr/bin/env python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# FIXME/PENDING:
#
# - support version requirement in pip
#
# - support version top level field
#
# - support simple operators for distro version comparision (fedora:<29)
#
# - support multiple matches in top level
#   distro|METHODNAME|DISTRO[:[OPERATOR?]VERSION]: eg:
#   fedora:<29|centos:<7|rhel:<7
#
# - redact passwords in URLs when logging with something like
#   https://relaxdiego.com/2014/07/logging-in-python.html (for all
#   $PASSWORD or so things, redact them)
#
# - support setting default method data? eg to set PIP URLs
"""
Handle package requirements covering multiple systems and OSes

Given a top level list of packages needed, this script tries to
install them using a native OS framework first (eg: DNF, APT) and then
falling back to other things like 'pip --user'.

No need to call as superuser! Will try to sudo by default

"""
__epilog__ = """\
Allows covering cases such when a PIP package (eg: paramiko) in RHEL
is called python3-paramiko but in Fedora 29 is called python-paramiko.

The list is specified as one or more multiple yaml files (callde
NAME.nreqs.yaml) which be as simple as::

 package1:
 package2:
 package3:

Running *install* on this will try to install *package1*, *package2*
and *package3* with the system's package manager (eg: DNF or APT) and
fallback to other methods, such as *pip* when that doesn't work.

If some package needs a rename for distro packages, you can do::

  package2: python3-package2

which is the same as::

  package2:
    distro:
      name: python3-package2

(*distro* here meaning, in which ever distribution this is being
installed in, when using the package manager, call it
python3-package2)

If you need specific renames for a given distro::

 package2:
   fedora:29:
     name: python-package2
   distro:
     name: python3-package2

This would, on Fedora 29, try to install *python-package2* before
falling back to pip as *package2*; on other distros, it would try to
install *python3-package2* before falling back to pip.

You can also force names for specific methods:

  package2:
    dnf:
       name: python3-package2
    apt:
       name: python-package2

Hackish yaml schema description::

 REQUIREMENTNAME:

 REQUIREMENTNAME: DISTROPACKAGENAME

 REQUIREMENTNAME:
   description|reason: "DESCRIPTION"        # O: needed for this and that
   license: SPDX-LICENSE-HEADER             # O: licensing info
   distro|METHODNAME|DISTRO[:[OPERATOR?]VERSION]:
     name: "NAME"                           # O: package name in disto (defaults to REQUIREMENT)
     exclusive: true|false                  # O: install exclusively with this method
     method: "NAME"                         # O: use a given method (data,dnf, apt, pip) instead of guessing based on distro
     license: "SPDX-LICENSE-HEADER"         # O: overrides top
     description|reason: "DESCRIPTION"      # O: overrides top
    pip:                                    # plus these ones for pop
     version: "[OPERATOR]VERSION"           # O: version requirement (eg: for pip)
     index: "URL"                           # O: URL of file to download, forces method to url
     indexes:
      - "URL"                               # O: URL of file to download, forces method to url
      - "URL"                               # O: URL of file to download, forces method to url
      - "URL"                               # O: URL of file to download, forces method to url
     skip: true|false                       # O: skip in this distro (default: false)
   skip_platform: linux
   skip_platform:
    - macos
    - win32s                     # platform names - win32, linux, macos
   require_platform: linux
   require_platform:
    - macos
    - win32                      # platform names - win32, linux, macos


Platforms: win32, macos, linux, ... (as python's sys.platform)
METHODNAMES: dnf, apt, data, pip (more if other drivers have been instantiated)
DISTRO: fedora, rhel, centos, ubuntu, debian (other drivers can create more)

URLs: can contain $NAME or ${NAME} to get from the environment (for
password/usernames)
"""

import argparse
import collections
import ctypes
import hashlib
import json
import logging
import os
import pprint
import re
import subprocess
import sys
import yaml

class method_abc:

    description = None

    # this is a class variable
    distro_to_method = dict()
    # eg: pip, cpan, etc
    generic_methods = dict()
    methods_by_name = collections.defaultdict(set)

    # append space, so we compose a command...bleh
    sudo = "sudo "
    
    def __init__(self, name, distros = None, exclusive = False):
        """
        :param bool exclusive: (optional) fallback setting to decide
          if a package that declares this method exclusively with it
          instead of trying others first.
        """
        assert isinstance(name, str)
        assert isinstance(exclusive, bool)
        self.name = name
        self.exclusive = exclusive
        self.origin = "FIXME"
        if name in self.methods_by_name:
            raise RuntimeError(
                f"{name}: method already registered by"
                f" {self.methods_by_name[name].origin}")
        self.methods_by_name[name] = self

        if distros == None:
            method_abc.generic_methods[self.name] = self
        else:
            for distro in distros:
                # all versions
                # FIXME support centos >= version -- so that centos:7 does
                # yum, centos>=8 does DNF
                method_abc.distro_to_method[distro] = self


    @classmethod
    def get_method_for_distro(cls):
        global distro
        global distro_version

        for _distro, _method in cls.distro_to_method.items():
            if _distro == distro:
                return _method.name
        raise RuntimeError(
            f"there is no known distro install method for distro {distro}")

    def install(self, package, package_alternate, package_data, method_details):
        # return
        # False: didn't install, try something else
        # True: installed
        #
        # raise exception for a "stop right now" problem
        raise NotImplementedError


class method_apt_c(method_abc):

    # FIXME: how to add extra repos?

    description = "Install packages with APT"

    def __init__(self):
        method_abc.__init__(self, "apt", [ 'debian', 'ubuntu' ])

    def install(self, package, package_alternate, package_data, method_details):
        apt_command = os.environ.get("APT_COMMAND", "apt")
        cmdline = f"{self.sudo}{apt_command} install -y".split()
        # Force default locale, so we can parse messages
        os.environ["LC_ALL"] = "C"
        os.environ["LC_LANG"] = "C"
        try:
            output = subprocess.check_output(
                cmdline + [ package_alternate ],
                stdin = subprocess.DEVNULL, stderr = subprocess.STDOUT)
            output = output.decode('utf-8', errors = 'backslashreplace').replace('\n', '\n  ')
            logging.info(
                f"{package} [apt/{package_alternate}]: installed\n  {output}")
            return True
        except subprocess.CalledProcessError as e:
            output = e.stdout.decode('utf-8', errors = 'backslashreplace')
            if "are you root?" in output:
                # can't install, try something else -- it is possible
                # the user doesn't have privs, but can then fallback
                # to pip --user, for example
                logging.error(
                    f"{package} [apt/{package_alternate}]: no permission to"
                    f" install (need superuser, add --sudo?)")
                return False
            # APT prints one message, microapt another
            if "Unable to locate package" in output:
                # package does not exist, try something else
                logging.error(
                    f"{package} [apt/{package_alternate}]: not available from APT (missing repo?)")
                return False
            # welp, what's this? no idea
            logging.error(
                f"{package} [apt/{package_alternate}]: command failed '{cmdline}':"
                f" {output}")
            raise RuntimeError(
                f"{package} [apt/{package_alternate}]: command failed '{cmdline}':"
                f" {output}")



class method_dnf_c(method_abc):

    # FIXME: how to add extra repos?

    description = "Install packages with DNF"

    def __init__(self):
        method_abc.__init__(self, "dnf", [ 'fedora', 'centos', 'rhel' ])

    def install(self, package, package_alternate, package_data, method_details):
        dnf_command = os.environ.get("DNF_COMMAND", "dnf")
        cmdline = f"{self.sudo}{dnf_command} install -y".split()
        # Force default locale, so we can parse messages
        os.environ["LC_ALL"] = "C"
        os.environ["LC_LANG"] = "C"
        try:
            output = subprocess.check_output(
                cmdline + [ package_alternate ],
                stdin = subprocess.DEVNULL, stderr = subprocess.STDOUT)
            output = output.decode('utf-8', errors = 'backslashreplace').replace('\n', '\n  ')
            logging.info(
                f"{package} [dnf/{package_alternate}]: installed\n  {output}")
            return True
        except subprocess.CalledProcessError as e:
            output = e.stdout.decode('utf-8', errors = 'backslashreplace')
            if "This command has to be run with superuser privileges" in output:
                # can't install, try something else -- it is possible
                # the user doesn't have privs, but can then fallback
                # to pip --user, for example
                logging.error(
                    f"{package} [dnf/{package_alternate}]: no permission to"
                    f" install (need superuser, add --sudo?)")
                return False
            # DNF prints one message, microdnf another
            if "Error: Unable to find a match" in output \
               or "error: No package matches" in output:
                # package does not exist, try something else
                logging.error(
                    f"{package} [dnf/{package_alternate}]: not available from DNF (missing repo?)")
                return False
            # welp, what's this? no idea
            logging.error(
                f"{package} [dnf/{package_alternate}]: command failed '{cmdline}':"
                f" {output}")
            raise RuntimeError(
                f"{package} [dnf/{package_alternate}]: command failed '{cmdline}':"
                f" {output}")



class method_pip_c(method_abc):

    description = "Install packages with Python's PIP"

    def __init__(self):
        method_abc.__init__(self, "pip")	# empty means "generic"

    def install(self, package, package_alternate, package_data, method_details):
        cmdline = [ "pip", "install" ]
        admin = False
        if hasattr(os, "geteuid"):	# most Unix platforms
            admin = os.geteuid() == 0
        elif hasattr(ctypes, "windll"):	# windowsy
            admin = ctypes.windll.shell32.IsUserAnAdmin()
        else:
            logging.warning("non-Unix platform? can't tell if sysadmin"
                            "--running with --user")
        # To deps or --no-deps, this is the question.
        # We can't tell ahead of time if we are able to install
        # dependencies as distro packages (which we prefer), and we
        # can't force the installation order (since the info could
        # come from multiple files). If we did --no-deps, it'd be
        # clustermess on packages we know are only available on
        # pip/whichever, which would require the user to unravel the
        # depednenciy rathole.
        #
        # FIXME: an approach might be to do some sort of ordering in
        # which we install in this order:
        #
        # - general packages
        # - packages which are exclusive to some method (without
        #   --no-deps)
        #
        # this balances the need, since the user can ensure the main
        # distro packages are installed before doing a pip something
        # that has distro-dependencies. Might not solve all, but gets
        # close.

        if not admin:
            cmdline.append("--user")

        _indexes = []
        _index = method_details.get('index', None)
        if _index != None:
            _indexes.append(_index)
        # FIXME: verify this is a list of valid URLs
        _indexes += method_details.get('indexes', [])
        indexes = []
        first_index = True
        for index in _indexes:
            if not isinstance(index, str):
                raise ValueError(
                    f"{package}/pip: invalid indexes entry; expect an index URL or a list of them\n")
            # expand $VAR, ${VAR}
            index_url_expanded = os.path.expandvars(index)
            # FIXME: validate is a valid URL
            # FIXME: check if a password is being given, add it to the
            # redact list
            if first_index:
                cmdline += [ "--index-url", index_url_expanded ]
                first_index = False
            else:
                cmdline += [ "--extra-index-url", index_url_expanded ]

        # Force default locale, so we can parse messages
        os.environ["LC_ALL"] = "C"
        os.environ["LC_LANG"] = "C"
        try:
            output = subprocess.check_output(
                cmdline + [ package_alternate ],
                stdin =  subprocess.DEVNULL, stderr = subprocess.STDOUT)
            output = output.decode('utf-8', errors = 'backslashreplace').replace('\n', '\n  ')
            logging.info(
                f"{package} [pip/{package_alternate}]: installed\n  {output}")
            return True
        except subprocess.CalledProcessError as e:
            output = e.stdout.decode('utf-8', errors = 'backslashreplace')
            if "ERROR: No matching distribution found for " in output:
                # package does not exist, try something else
                logging.error(
                    f"{package} [pip/{package_alternate}]: not available from PIP (missing repo?)")
                return False
            # welp, what's this? no idea
            logging.error(
                f"{package} [pip/{package_alternate}]: command failed '{cmdline}':"
                f" {output}")
            raise RuntimeError(
                f"{package} [pip/{package_alternate}]: command failed '{cmdline}':"
                f" {output}")



class method_data_c(method_abc):

    description = "Download data files"

    def __init__(self):
        method_abc.__init__(self, "data", exclusive = True)


    def install(self, package, package_alternate, package_data, method_details):
        url = method_details.get(
            'URL', method_details.get('name', None))
        destination = method_details.get('destination', None)
        if url == None:
            logging.error(
                f"{package} [data/{package_alternate}]: skipping;"
                " no URL in method data")
            return False
        # --location: follow 301 redirects
        cmdline = f"curl --location".split()
        if destination:
            cmdline += [ '--output', destination ]
        else:
            cmdline += [ '--remote-name' ]
        # Force default locale, so we can parse messages
        os.environ["LC_ALL"] = "C"
        os.environ["LC_LANG"] = "C"
        try:
            output = subprocess.check_output(
                cmdline + [ url ],
                stdin =  subprocess.DEVNULL, stderr = subprocess.STDOUT)
            output = output.decode('utf-8', errors = 'backslashreplace').replace('\n', '\n  ')
            logging.info(
                f"{package} [data/{package_alternate}]: installed\n  {output}")
            return True
        except subprocess.CalledProcessError as e:
            output = e.stdout.decode('utf-8', errors = 'backslashreplace')
            # welp, what's this? no idea
            logging.error(
                f"{package} [pip/{package_alternate}]: command failed '{cmdline}':"
                f" {output}")
            raise RuntimeError(
                f"{package} [pip/{package_alternate}]: command failed '{cmdline}':"
                f" {output}")


class method_default_c(method_abc):

    description = "FIXME default distro"

    def __init__(self):
        method_abc.__init__(self, [ "default" ])


def _distro_version_get(distro, version):
    data = {}
    if distro:
        data['ID'] = distro
    if version:
        data['VERSION_ID'] = version

    # pull in the rest of the data -- Linux only, for now
    if sys.platform == "linux":
        with open("/etc/os-release") as f:
            for line in f:
                line = line.strip()
                if not '=' in line:
                    continue
                key, val = line.split('=', 1)
                # some distros put values with quotes at beg/end...some don't,
                # in anycase, we don't need'em
                val = val.strip('"')
                data.setdefault(key, val)
                logging.log(8, f"/etc/os-release: sets {key}={val}")
    else:
        raise RuntimeError(
            f"Can't figure out distro or version for"
            f" platform {sys.platform}")

    return data['ID'], data['VERSION_ID']


def _distro_match(req, req_distro, req_distro_version):
    if req_distro != distro:
        logging.debug(f"{req}: {req_distro}:"
                      f" ignored because req distro {req_distro} "
                      f" doesn't match target system's distro {distro}")
        return False
    if req_distro_version != None and req_distro_version != distro_version:
        logging.info(f"{req}: {req_distro}:{req_distro_version}:"
                     f" ignored because req distro version {req_distro_version} "
                     f" doesn't match target system version {distro_version}")
        return False
    return True


def _skip_platform_check(req, req_distro_spec, skips):

    # this is a list of distros to ignore
    ## skip: SOMEDISTRO
    ## skip:
    ##   - DISTRO1
    ##   - DISTRO2
    ##   - DISTRO3[:VERSION]
    if isinstance(skips, str):
        skips = [ skips ]
    else:
        assert isinstance(skips, (list, set)), \
            f"ERROR: {req}/{req_distro_spec}: expected list of distros to exclude;" \
            f" got {type(skips)}: {skips}"
        assert all(isinstance(i, str) for i in skips)
    # FIXME: add :VERSION support
    r = sys.platform in skips
    if r:
        logging.warning(
            f"{req}: skipping because current platform"
            f" '{sys.platform}' matches 'skip_platform'"
              f" list: {' '.join(skips)}")
    return r


def _reqs_grok(packages, req_method_details, filename, y):
    global distro
    global distro_version
    global distro_method
    logging.debug(f"{filename}: parsing {json.dumps(y, indent = 4, skipkeys = True)}")

    for req, req_data in y.items():
        logging.debug(f"new requirement: {req}, data {req_data}")
        skip_platform = False
        require_platform = False
        skip_distro = False

        if req_data == None:
            # this is the most simple of the requirement specifications
            #
            ## PACKAGNAME:
            #
            # is shorthand for:
            #
            # "I just need this package with the default
            # distro/version system or whatever can get it installed"
            #
            # try dnf/apt, then pip, then this, then that
            logging.debug(f"{req}: associating to distro '{distro}' (empty reference)")
            req_data = { distro: {} }
        elif isinstance(req_data, str):
            # Translate shorthand
            #
            ## PACKAGENAME: DISTROPACKAGENAME
            #
            # To:
            #
            ## PACKAGENAME:
            ##   distro:
            ##     name: DISTROPACKAGENAME
            req_data = {
                "distro": {
                    "name": req_data
                }
            }

        req_alternate = None
        # need at least a basic definition
        method_name = None
        method_data = {}
        description = None
        spdx_license = None
        for req_distro_spec, req_distro_data in req_data.items():

            logging.log(9, f"{req}/{req_distro_spec}:"
                        f" req_distro_data {req_distro_data}")
            if req_distro_spec == "skip_platform":
                # the "skip" distro is just to tell us in which
                # platforms we do not want to install
                if _skip_platform_check(req, req_distro_spec, req_distro_data):
                    # FIXME: wipe from reqs and stop further
                    # processing -- or do not commit the info to req
                    skip_platform = True
                    logging.info(f"{req}/{req_distro_spec}: will skip due to platform check")
                    break
                # no need to keep processing, since this req_distro
                # does not specify a distro
                continue

            if req_distro_spec == "require_platform":
                if not _skip_platform_check(req, req_distro_spec, req_distro_data):
                    # FIXME: wipe from reqs and stop further
                    # processing -- or do not commit the info to req
                    skip_platform = True
                    logging.info(
                        f"{req}/{req_distro_spec}:"
                        " will skip, not meeting required platform check")
                    break
                # no need to keep processing, since this req_distro
                # does not specify a distro
                continue

            if req_distro_spec == "license":
                spdx_license = req_distro_data
                logging.debug(f"{req}: top-level setting license to: {spdx_license}")
                continue

            if req_distro_spec in ( "description", "reason" ):
                logging.debug(f"{req}: top-level setting description to: {description}")
                description = req_distro_data
                continue

            # This might be a distro/package method specification
            # Split distro|DISTRONAME[:VERSION]|METHODNAME
            if req_distro_spec == "distro":
                req_distro, req_distro_version = distro, distro_version
                logging.debug(f"{req}/{req_distro_spec}:"
                              f" setting to distro version {req_distro_version}")
            elif ':' in req_distro_spec:
                # DISTRONAME[:VERSION]
                req_distro, req_distro_version = req_distro_spec.split(":", 1)
                logging.debug(f"{req}/{req_distro_spec}:"
                              f" applies to distro version {req_distro_version}")
            else:
                req_distro = req_distro_spec
                logging.debug(f"{req}/{req_distro_spec}:"
                              " applies to all distro versions")
                req_distro_version = None

            if req_distro not in method_abc.generic_methods \
               and req_distro not in method_abc.distro_to_method \
               and req_distro not in method_abc.methods_by_name:
                logging.error(
                    f"{req}: unknown distro or method"
                    f" '{req_distro}'; expected:"
                    f" {', '.join(method_abc.generic_methods.keys())}"
                    f" {', '.join(method_abc.distro_to_method.keys())}")

            ## PACKAGE:
            ##   distro|DISTRO[:VERSION]|METHOD: NAME
            #
            # is shorthand for:
            #
            ## PACKAGE:
            ##   distro:
            ##     name: NAME
            if isinstance(req_distro_data, str):
                method_data = { "name": req_distro_data }
            elif req_distro_data == None:
                method_data = {}
            else:
                assert isinstance(req_distro_data, dict)
                method_data = dict(req_distro_data)
            logging.debug(f"{req}/{req_distro_spec}: method_data {method_data}")

            if req_distro in method_abc.generic_methods:
                method_name = req_distro
                logging.info(f"{req}: RECORD generic method '{req_distro}'"
                             f" -> {method_data}")
                # if this "distro" is naming a generic method, just
                # record it
                if method_data:
                    # if we have some specific method data, record it,
                    # otherwise all defaults
                    req_method_details[req_distro][req] = method_data
                # this is a generic method
                continue

            if req_distro_spec in method_abc.methods_by_name:
                # This is a method name:
                ## PACKAGE:
                ##   METHODNAME:
                ##     ...
                method_name = req_distro
            elif req_distro in method_abc.distro_to_method.keys():
                # This is a distro match name:
                ## PACKAGE:
                ##   DISTRO[:VERSION]:
                ##     ...
                # valid distro
                if not _distro_match(req, req_distro, req_distro_version):
                    # this requirement subspec doesn't apply to this distro
                    continue
                # Is this specifying how to install in some distro?

                # FIXME: consider versions when getting method_name
                method_name = method_abc.distro_to_method[req_distro].name
            else:
                raise RuntimeError(
                    f"BUG? specification {req_distro_spec} not understood"
                    f"as a distribution ({','.join(methods_abc.distro_to_method.keys())})"
                    f" or install method ({','.join(methods_abc.methods_by_name.keys())})")

            # We have an installation method name, either specified as
            # a top level or derived from a distro specification or
            # defaults

            # Parse method details
            #
            ## DISTRO:
            ##   skip[: True|yes]
            skip_distro = bool(method_data.get('skip', False))
            if skip_distro:
                logging.info(f"{req}: boolean skip field"
                             f" for distro {distro}:{distro_version}")
                method_data = None
                continue
            if req_distro_version:
                # record distro_version if we have it, because
                # this means it is a more specific match
                method_data['distro_version'] = distro_version
            # FIXME: call method driver to parse info into method?
            # (eg: pip can do version filters and URLs to index,
            # dnf/apt can't)
            # Overrides from method data?
            req_alternate = method_data.get('name', req)
            if 'description' in method_data:
                description = method_data['description']
                logging.info(
                    f"{req} [{method_name}/{req_alternate}]:"
                    f" {req_distro_spec}: overriding description to:"
                    f" {description}")
            if 'license' in method_data:
                spdx_license = method_data['license']
                logging.info(
                    f"{req} [{method_name}/{req_alternate}]:"
                    f" {req_distro_spec}: overriding license to:"
                    f" {spdx_license}")


            # if we have some specific method data, record it,
            # otherwise all defaults
            if not method_data:
                logging.debug(
                    f"{req} [{method_name}/{req_alternate}]:"
                    f" -> install on '{distro}' with default methods")
                continue

            # If there are no entries, create it
            existing_method_data = req_method_details[method_name].get(req, None)
            if not existing_method_data:
                logging.info(
                    f"{req}: RECORD [{method_name}/{req_alternate}] -> {method_data}")
                req_method_details[method_name][req] = method_data
                continue

            # existing entry? only update if it has no version
            # info and we do; in case of conflict, keep existing
            _existing_distro_version = existing_method_data.get('distro_version', None)
            _distro_version = method_data.get('distro_version', None)
            if _existing_distro_version and _distro_version:
                logging.warning(
                    f"{req} [{req_distro_spec}]: skipping; got more specific"
                    f" entry for {distro}:{_existing_distro_version}")
                continue
            if _existing_distro_version and not _distro_version:
                # don't override
                logging.warning(
                    f"{req} [{req_distro_spec}]: skipping; got more specific"
                    f" entry for {distro}:{_existing_distro_version}")
                continue
            # ok, this is more version-specifc than what we have, so
            # record it
            logging.info(
                f"{req}: RECORD [{distro_method}/{req_alternate}]:"
                f" (distro version {distro_version} override)"
                f" will install first with method {distro_method} {method_data}")
            req_method_details[distro_method][req] = method_data
            continue


        if skip_platform:
            # well, it was determined this has to be skipped
            logging.info(f"{req}: skipped because of require/skip_platform tag")
            continue

        # At this point we have req, req_alternate and method_data
        if skip_distro:
            logging.info(f"{req}: skipped because of distro/skip tag")
            continue
        packages.setdefault(req, {})
        if description:
            packages[req]['description'] = description
        if spdx_license:
            packages[req]['license'] = spdx_license
        if method_name == None:
            # no method? default to the distro's default
            method_name = method_abc.distro_to_method[distro].name
        # do we have to install exclusively with any method? if so,
        # mark it -- this applies mostly to 'data' methods, where we
        # just download some file
        exclusive = method_data.get(
            'exclusive',
            method_abc.methods_by_name[method_name].exclusive)
        if exclusive:
            logging.info(
                f"{req}: RECORD package will be exclusively installed with"
                f" method '{method_name}'")
            packages[req]['method'] = method_name
        else:
            logging.info(
                f"{req}: RECORD package will be installed with any available method")

_filename_regex = re.compile("^.*\.nreqs\.yaml$")

def _parse_file(filename, packages, method_details):
    # regular filename
    basename = os.path.basename(filename)
    m = _filename_regex.search(basename)
    if not m:
        logging.info(f"{filename}: ignoring, doesn't match NAME.nreqs.yaml")
        return
    logging.warning(f"{filename}: parsing")
    try:
        with open(filename) as f:
            y = yaml.safe_load(f)
            # FIXME: validate YAML
            _reqs_grok(packages, method_details, filename, y)
    except Exception as e:
        logging.exception(f"{filename}: can't process: {e}")
        # FIXME: ack -k?

def _parse_files(args):
    #
    # Load all the requirements into the reqs array
    #
    # reqs[METHOD] = [set of packages to install]
    method_details = collections.defaultdict(collections.defaultdict)
    packages = dict()
    for path in args.filenames:
        logging.debug(f"{path}: considering parsing")
        if os.path.isfile(path):
            _parse_file(path, packages, method_details)
        elif os.path.isdir(path):
            for file_path, _dirnames, filenames in os.walk(path):
                logging.log(5, "%s: scanning directory", path)
                for filename in filenames:
                    filename = os.path.join(file_path, filename)
                    _parse_file(filename, packages, method_details)
        else:
            logging.warning(f"{path}: invalid input file")
    return packages, method_details


def _command_hash(args):
    packages, method_details = _parse_files(args)
    # FIXME: preprocess packages and method_details and remove fields
    # that should not affect the dependency trees:
    # - description
    # - license
    s = json.dumps(packages, indent = 4, skipkeys = True) \
        + json.dumps(method_details, indent = 4, skipkeys = True)
    m = hashlib.sha512(s.encode('utf-8'))
    # add any files passed with -e
    for filename in args.extra_file:
        with open(filename, 'rb') as f:
            logging.warning(f"hash: adding contents of {filename}")
            m.update(f.read())
    for salt in args.salt:
        m.update(salt.encode('utf-8'))
    print(m.hexdigest()[:16])


def _command_json(args):
    packages, method_details = _parse_files(args)
    toplevel = {
        "packages": packages,
        "method_details": method_details,
    }
    json.dump(toplevel, sys.stdout, indent = 4, skipkeys = True)


def _command_install(args):
    logging.warning(f"installing for: {distro} v{distro_version},"
                    f" default install with {distro_method}")
    if args.sudo:
        method_abc.sudo = "sudo "
    else:
        method_abc.sudo = ""
    packages, method_details = _parse_files(args)
    methods = [ method_abc.methods_by_name[distro_method] ] \
        + list(method_abc.generic_methods.values())
    for package, package_data in packages.items():
        logging.warning(f"{package}: installing")
        logging.info(f"{package}: package data {package_data}")
        methods_tried = []

        for method in methods:
            try:
                # FIXME: acknowledge exclusive -> if
                # package_data['method'] != method, skip
                _method_details = method_details.get(method.name, {}).get(package, {})
                package_alternate = _method_details.get('name', package)
                logging.warning(
                    f"{package} [{method.name}/{package_alternate}]:"
                    " trying to install")
                logging.info(
                    f"{package} [{method.name}/{package_alternate}]:"
                    f" method details {_method_details}")
                if method.install(
                        package, package_alternate, package_data,
                        _method_details):
                    logging.warning(f"{package}: installed with {method.name}")
                    break
                logging.warning(
                    f"{package} [{method.name}/{package_alternate}]:"
                    f" did not install")
            except Exception as e:
                logging.exception(
                    f"BUG! {package} installation raised: {e}")
            methods_tried.append(method.name)
        else:
            if args.keep_going:
                logging.warning(
                    f"{package}: can't install (tried: {', '.join(methods_tried)});"
                    " continuing because -k was given")
                continue
            logging.error(
                f"{package}: can't install (tried: {', '.join(methods_tried)})")
            logging.error("exiting on error condition"
                          " (you can use -k, see --help)")
            sys.exit(1)
        # if keep_going is True, we ignore errors
    logging.error("Success")
    sys.exit(0)


def logging_verbosity_inc(level):
    if level == 0:
        return
    if level > logging.DEBUG:
        delta = 10
    else:
        delta = 1
    return level - delta

class _action_increase_level(argparse.Action):
    def __init__(self, option_strings, dest, default = None, required = False,
                 nargs = None, **kwargs):
        argparse.Action.__init__(
            self, option_strings, dest, nargs = 0, required = required,
            **kwargs)
    def __call__(self, parser, namespace, values, option_string = None):
        # Python levels are 50, 40, 30, 20, 10 ... (debug) 9 8 7 6 5 ... :)
        if namespace.verbose == None:
            namespace.verbose = logging.ERROR
        namespace.verbose = logging_verbosity_inc(namespace.verbose)



#
# Main
#

parser = argparse.ArgumentParser(
    description = __doc__,
    epilog = __epilog__,
    formatter_class = argparse.RawDescriptionHelpFormatter)

# FIXME: parse config files to extend?
#parser.add_argument(
#    "-c", "--config", required=False,
#    help="path to config files")

parser.add_argument(
    "-v", "--verbose", action = _action_increase_level,
    help = "Increase verbosity")
parser.add_argument(
    "-k", "--keep-going", action = "store_true", default = False,
    help = "Keep going on error")
parser.add_argument(
    "-d", "--distro", required = False,
    help = "distro to install on"
    " (default: guessed from /etc/os-release or equivalent")
parser.add_argument(
    "-V", "--distro-version", required = False,
    help = "distro version to install on"
    " (default: guessed from /etc/os-release or equivalent")
parser.add_argument(
    "-i", "--ignore-method", metavar = "NAME",
    type = str, action = "append", default = [],
    help = "add drivers to ignore when loading")

# ugh, can't self guess these because when arg parsing is done, the
# drivers are not loaded yet -> FIXME: be a "list knonw
# methods" option, so it can load all drivers and report'em
valid_distro_methods = [ 'apt', 'dnf' ]
parser.add_argument(
    "-m", "--distro-method", required = False,
    help = "method this distro uses to install"
    " (default: guessed based on distro);"
    f" valid values: apt, dnf")
parser.add_argument(
    "--nodistro", required = False, action = "store_true",
    help = "Do not try to install with the distributions'"
    " default install system")
parser.add_argument(
    "--traces", required = False, action = "store_true")

command_subparser = parser.add_subparsers(help = "commands")

ap = command_subparser.add_parser(
    "hash",
    help = "Generate a unique hash of the requirement information")
ap.add_argument(
    "filenames", metavar = "PATH|FILE.nreqs.yaml", type = str, nargs = "+",
    help = "requirements file(s) or paths contianing them [*.nreqs.yaml]")
ap.add_argument(
    "-e", "--extra-file", metavar = "FILE",
    type = str, action = "append", default = [],
    help = "add other files to use for generating the hash")
ap.add_argument(
    "-s", "--salt", metavar = "VALUE",
    type = str, action = "append", default = [],
    help = "add extra values for salting the hash")
ap.set_defaults(func = _command_hash)

ap = command_subparser.add_parser(
    "json",
    help = "Generate a JSON dump of the package information")
ap.add_argument(
    "filenames", metavar = "PATH|FILE.nreqs.yaml", type = str, nargs = "+",
    help = "requirements file(s) or paths contianing them [*.nreqs.yaml]")
ap.set_defaults(func = _command_json)

ap = command_subparser.add_parser(
    "install",
    help = "Install packages")
ap.add_argument(
    "-s", "--sudo", 
    action = "store_true", default = True, dest = "sudo",
    help = "Run dnf/apt (system level package managers) under sudo [%(default)s]")
ap.add_argument(
    "-u", "--no-sudo", 
    action = "store_false", default = True, dest = "sudo",
    help = "Do not run dnf/apt (system level package managers)"
    " under sudo [%(default)s]")
ap.add_argument(
    "filenames", metavar = "PATH|FILE.nreqs.yaml", type = str, nargs = "+",
    help = "requirements file(s) or paths contianing them [*.nreqs.yaml]")
ap.set_defaults(func = _command_install)

# Short level names for logging, clearer
logging.addLevelName(50, "C")
logging.addLevelName(40, "E")
logging.addLevelName(30, "W")
logging.addLevelName(20, "I")
logging.addLevelName(10, "D")
logging.addLevelName(9, "D2")
logging.addLevelName(8, "D3")
logging.addLevelName(7, "D4")
logging.addLevelName(6, "D5")

args = parser.parse_args()
logging.basicConfig(format = "%(levelname)s: %(message)s",
                    level = args.verbose)

# Instantiate installation method drivers, they self-register
#
#method_yum_c()
method_dnf_c()
method_apt_c()
method_pip_c()
method_data_c()

for method in list(method_abc.generic_methods):
    if method in args.ignore_method:
        logging.info(f"removing method {method}")
        del method_abc.generic_methods[method]

# determine in which distro we are running, except for overrides
distro, distro_version = _distro_version_get(args.distro, args.distro_version)
if args.distro_method:
    distro_method = args.distro_method
else:
    distro_method = method_abc.get_method_for_distro()


try:
    logging.debug(f"running {args.func}")
    retval = args.func(args)
    logging.debug(f"ran {args.func}")
    sys.exit(0)
except AttributeError as e:
    if 'func' in str(e):
        # dumb hack -- if there is no command specified to run, this
        # will exception like this
        #
        ## AttributeError: 'Namespace' object has no attribute 'func'
        #
        # ... and caught
        logging.error("no command specified (see --help)")
        sys.exit(1)
    raise
    # fallthrough
except Exception as e:
    if args.traces:
        logging.exception(e)
    else:
        rep = str(e)
        if rep:
            logging.error(rep)
        else:
            logging.error(
                "%s exception raised with no description "
                "(run with `--traces` for more info)"
                % type(e).__name__)
        sys.exit(1)
