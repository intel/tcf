#! /usr/bin/python2
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
import hashlib
import io

import pprint

from . import commonl
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


    def list(self, filenames = None):
        """
        List available files and their MD5 sums
        """
        commonl.assert_none_or_list_of_strings(filenames, "filenames", "filename")
        r = self.target.ttbd_iface_call("store", "list",
                                        filenames = filenames, method = "GET")
        return r['result']


    def _healthcheck(self):
        target = self.target
        l = target.store.list()
        print("OK: can do initial list, got", pprint.pformat(l))
        for name, _md5 in list(l.items()):
            target.store.delete(name)
            print("OK: deleted existing %s" % name)
    
        tmpname = commonl.mkid(str(id(target))) + ".1"
        target.store.upload(tmpname, __file__)
        print("OK: uploaded 1", tmpname)
        l = target.store.list()
        assert len(l) == 1, \
            "after uploading one file, %d are listed, expected 1; got %s" \
            % (len(l), pprint.pformat(l))
        assert list(l.keys())[0] == tmpname, \
            "after uploading file, name differs, expected %s; got %s" \
            % (tmpname, pprint.pformat(l))
        print("OK: 1 listed")

        tmpname2 = commonl.mkid(str(id(target))) + ".2"
        target.store.upload(tmpname2, __file__)
        print("OK: uploaded 2", tmpname2)
        l = target.store.list()
        assert len(l) == 2, \
            "after uploading another file, %d are listed, expected 2; got %s" \
            % (len(l), pprint.pformat(l))
        assert tmpname2 in list(l.keys()), \
            "after uploading file, can't find %s; got %s" \
            % (tmpname2, pprint.pformat(l))
        print("OK: 2 listed")

        target.store.delete(tmpname)
        l = target.store.list()
        assert tmpname not in list(l.keys()), \
            "after removing %s, still can find it in listing; got %s" \
            % (tmpname, pprint.pformat(l))
        print("OK: removed", tmpname)

        target.store.delete(tmpname2)
        l = target.store.list()
        assert tmpname2 not in list(l.keys()), \
            "after removing %s, still can find it in listing; got %s" \
            % (tmpname2, pprint.pformat(l))
        assert len(l) == 0, \
            "after removing all, list is not empty; got %s" \
            % pprint.pformat(l)
        print("OK: removed", tmpname2, "list is empty")
        
def _cmdline_store_upload(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "store")
        target.store.upload(args.remote_filename, args.local_filename)

def _cmdline_store_dnload(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "store")
        target.store.dnload(args.remote_filename, args.local_filename)

def _cmdline_store_delete(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "store")
        target.store.delete(args.remote_filename)

def _cmdline_store_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "store")
        for file_name, file_hash in target.store.list().items():
            print(file_hash, file_name)


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
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.set_defaults(func = _cmdline_store_list)
