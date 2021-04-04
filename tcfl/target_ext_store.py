#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Copy files from and to the server's user storage area
-----------------------------------------------------

"""

import contextlib
import json
import hashlib
import io

import pprint
import tabulate

import commonl
from . import tc
from . import msgid_c

class extension(tc.target_extension_c):
    """\
    Extension to :py:class:`tcfl.tc.target_c` to run methods to manage
    the files in the user's storage area in the server.

    Use as:

    >>> files = target.store.list()
    >>> target.store.upload(REMOTE, LOCAL)
    >>> target.store.dnload(REMOTE, LOCAL)
    >>> target.store.delete(REMOTE)

    Note these files are, for example:

    - images for the server to flash into targets (usually handled with
      the :class:`images <tcfl.target_ext_images.extension>`)

    - copying specific log files from the server (eg: downloading TCP
      dump captures form *tcpdump* as done by the
      :class:`conf_00_lib.vlan_pci` network element).

    - the storage area is commong to *all* targets of the server for
      each user, thus multiple test cases running in parallel can
      access it at the same time. Use the testcase's hash to safely
      namespace:

      >>> tc_hash = self.kws['tc_hash']
      >>> target.store.upload(tc_hash + "-NAME", LOCAL)

    Presence of the *store* attribute in a target indicates this
    interface is supported.

    """
    def upload(self, remote, local, force = False):
        """
        Upload a local file to the store

        :param str remote: name in the server
        :param str local: local file name

        :param bool force: (default *False*) if the file already
          exists and has the same digest, do not re-upload it.
        """
        fl = self.list([ remote ])
        if force == False and remote in fl:
            remote_hash = fl[remote]
            h = hashlib.sha256()
            commonl.hash_file(h, local)
            if remote_hash == h.hexdigest():
                # remote hash is the same, no need to upload
                return

        with io.open(local, "rb") as inf:
            self.target.ttbd_iface_call("store", "file", method = "POST",
                                        file_path = remote,
                                        files = { 'file': inf })


    def dnload(self, remote, local):
        """
        Download a remote file from the store to the local system

        :param str remote: name of the file to download in the server
        :param str local: local file name
        :returns int: the amount of bytes downloaded
        """
        with io.open(local, "wb+") as of, \
             contextlib.closing(self.target.ttbd_iface_call(
                 "store", "file", method = "GET", stream = True, raw = True,
                 file_path = remote)) as r:
            # http://docs.python-requests.org/en/master/user/quickstart/#response-content
            chunk_size = 4096
            total = 0
            for chunk in r.iter_content(chunk_size):
                of.write(chunk)
                total += len(chunk)	# not chunk_size, it might be less
            return total


    def delete(self, remote):
        """
        Delete a remote file

        :param str remote: name of the file to remove from the server
        """
        self.target.ttbd_iface_call("store", "file", method = "DELETE",
                                    file_path = remote)


    def list(self, filenames = None, path = None, digest = None):
        """
        List available files and their digital signatures

        :param list(str) filenames: (optional; default all) filenames
          to list. This is used when we only want to get the digital
          signature of an specific file that might or might not be
          there.

        :param str path: (optional; default's to user storage) path to
          list; only allowed paths (per server configuration) can be
          listed.

          To get the list of allowed paths other than the default
          user's storage path, specify path */*.

        :param str digest: (optional; default sha256) digest to
          use. Valid values so far are *md5*, *sha256* and *sha512*.

        :return: dictionary keyed by filename of file digital signatures. An
          special entry *subdirectories* contains a list of
          subdirectories in the path.
        """
        commonl.assert_none_or_list_of_strings(filenames, "filenames", "filename")
        r = self.target.ttbd_iface_call(
            "store", "list", path = path, digest = digest,
            filenames = filenames, method = "GET")
        if 'result' in r:
            return r['result']	# COMPAT
        return r


    def _healthcheck(self):
        target = self.target
        l0 = target.store.list()
        target.report_pass("got existing list of files", dict(l0 = l0))

        tmpname = commonl.mkid(str(id(target))) + ".1"
        target.store.upload(tmpname, __file__)
        target.report_pass("uploaded file %s" % tmpname)
        l = target.store.list()
        # remove elements we knew existed (there might be other
        # processes in parallel using this )
        l = list(set(l) - set(l0))
        if len(l) != 1:
            raise tc.failed_e(
                "after uploading one file, %d are listed; expected 1" % len(l),
                dict(l = l))
        if l[0] != tmpname:
            raise tc.failed_e(
                "after uploading file, name differs, expected %s" % tmpname,
                dict(l = l))
        target.report_pass("listed afer uploading one")

        tmpname2 = commonl.mkid(str(id(target))) + ".2"
        target.store.upload(tmpname2, __file__)
        target.report_pass("uploaded second file %s" % tmpname2)
        l = target.store.list()
        l = list(set(l) - set(l0))
        if len(l) != 2:
            raise tc.failed_e(
                "after uploading another file, %d are listed, expected 2" % len(l),
                dict(l = l))
        if tmpname2 not in l:
            raise tc.failed_e(
                "after uploading file, can't find %s" % tmpname2,
                dict(l = l))
        target.report_pass("listed after uploading second file", dict(l = l))

        target.store.delete(tmpname)
        l = target.store.list()
        if tmpname in l:
            raise tc.failed_e(
                "after removing %s, still can find it in listing" % tmpname,
                dict(l = l))
        target.report_pass("removed %s" % tmpname)

        target.store.delete(tmpname2)
        l = target.store.list()
        if tmpname2 in l:
            raise tc.failed_e(
                "after removing %s, still can find it in listing" % tmpname2,
                dict(l = l))
        l = list(set(l) - set(l0))
        if l:
            raise tc.failed_e(
                "after removing all, list is not empty", dict(l = l))
        target.report_pass("all files removed report empty list")

def _cmdline_store_upload(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "store",
                                                      extensions_only = "store")
        target.store.upload(args.remote_filename, args.local_filename)

def _cmdline_store_dnload(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "store",
                                                      extensions_only = "store")
        target.store.dnload(args.remote_filename, args.local_filename)

def _cmdline_store_delete(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "store",
                                                      extensions_only = "store")
        target.store.delete(args.remote_filename)

def _cmdline_store_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(
            args, extensions_only = "store", iface = "store")
        if not args.filename:
            args.filename = None
        data = target.store.list(path = args.path, filenames = args.filename,
                                 digest = args.digest)

        if args.verbosity == 0:
            for file_name, file_hash in data.items():
                print(file_hash, file_name)
        elif args.verbosity == 1:
            headers = [
                "File name",
                "Hash " + (args.digest if args.digest else "(default)"),
            ]
            print(tabulate.tabulate(data.items(), headers = headers))
        elif args.verbosity == 2:
            commonl.data_dump_recursive(data)
        elif args.verbosity == 3:
            pprint.pprint(data)
        elif args.verbosity >= 4:
            print(json.dumps(data, skipkeys = True, indent = 4))


def _cmdline_setup(arg_subparsers):

    ap = arg_subparsers.add_parser("store-upload",
                                   help = "Upload a local file to the server")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.add_argument("remote_filename", action = "store",
                    help = "Path to remote file file (defaults to same as " \
                    "local). Note the file will be stored in a user"\
                    " specific area")
    ap.add_argument("local_filename", action = "store",
                    help = "Path to local file to upload")
    ap.set_defaults(func = _cmdline_store_upload)

    ap = arg_subparsers.add_parser("store-dnload",
                                   help = "Download a file from the server")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.add_argument("remote_filename", action = "store",
                    help = "Path to remote file name in user's store")
    ap.add_argument("local_filename", action = "store",
                    help = "Path to where to store the file locally")
    ap.set_defaults(func = _cmdline_store_dnload)

    ap = arg_subparsers.add_parser("store-rm",
                                   help = "Delete a file from the server")
    commonl.argparser_add_aka(arg_subparsers, "store-rm", "store-del")
    commonl.argparser_add_aka(arg_subparsers, "store-rm", "store-delete")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.add_argument("remote_filename", action = "store",
                    help = "Path to remote file to delete")
    ap.set_defaults(func = _cmdline_store_delete)

    ap = arg_subparsers.add_parser("store-ls",
                                   help = "List files stored in the server")
    ap.add_argument(
        "-v", dest = "verbosity", action = "count", default = 0,
        help = "Increase verbosity of information to display "
        "(-v is a table , "
        "-vv hierarchical, -vvv Python format, -vvvv JSON format)")
    ap.add_argument(
        "-q", dest = "quietosity", action = "count", default = 0,
        help = "Decrease verbosity of information to display "
        "(none is a table, -q list of shortname, url and username, "
        "-qq the hostnames, -qqq the shortnames"
        "; all one per line")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.add_argument("--path", metavar = "PATH", action = "store",
                    default = None, help = "Path to list")
    ap.add_argument("--digest", action = "store",
                    default = None, help = "Digest to use"
                    " (zero, md5, sha256 [default], sha512)")
    ap.add_argument("filename", nargs = "*", action = "store",
                    default = [], help = "Files to list (defaults to all)")
    ap.set_defaults(func = _cmdline_store_list)
