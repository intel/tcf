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

import bisect
import contextlib
import json
import hashlib
import io

import pprint
import tabulate

import commonl
import tcfl
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


    def dnload(self, remote, local, offset = None, append = False):
        """
        Download a remote file from the store to the local system

        :param str remote: name of the file to download in the server
        :param str local: local file name
        :param int offset: (optional; default *None*) offset of data
          to read (if negative, offset from the end).
        :param bool append: (optional; default *False*) append to
          existing file--normally used with offset matching its
          length.
        :returns int: the amount of bytes downloaded
        """
        if append:
            mode = "ab+"
        else:
            mode = "wb+"
        with io.open(local, mode) as of, \
             contextlib.closing(self.target.ttbd_iface_call(
                 "store", "file", method = "GET", stream = True, raw = True,
                 file_path = remote, offset = offset)) as r:
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


    def list2(self, filenames = None, path = None, digest = None):
        """
        List available files and their digital signatures

        v2 of the call, returns more data

        :param list(str) filenames: (optional; default all) filenames
          to list. This is used when we only want to get the digital
          signature of an specific file that might or might not be
          there.

        :param str path: (optional; default's to user storage) path to
          list; only allowed paths (per server configuration) can be
          listed.

          To get the list of allowed paths other than the default
          user's storage path, specify path */*.

        :param str digest: (optional; default *none*) digest to
          use. Valid values so far are *md5*, *sha256* and *sha512*.

        :return: dictionary keyed by filename of dictionary with data
          for each entry:

          - *type*: a string describing the type of the entry:

            - *directory* (a directory which might contain other entries)

            - *file* (a file which contains data)

            - *unknown* (other)

          - *size*: (only for *type* being *file*) integer describing ghre
            size (in bytes) of the file

          - *aliases*: if the entry is a link or an alias for another, a
            string describing the name the entry being aliased

          - *digest*: (only for *type* being *file* and for *digest* being a
            valid, non *zero* digest) string describing the digest of the
            data.

      """
        commonl.assert_none_or_list_of_strings(filenames, "filenames", "filename")
        try:
            return self.target.ttbd_iface_call(
                "store", "list2", path = path, digest = digest,
                filenames = filenames, method = "GET")
        except tcfl.exception as e:
            if 'list2: unsupported' not in repr(e):
                raise
            r = self.target.ttbd_iface_call(
                "store", "list", path = path, digest = digest,
                filenames = filenames, method = "GET")
            if 'result' in r:
                r = r['result']	# COMPAT
            # no xlate this to the v2 format, which is a dict of dicts
            # we can't do much, since the v1 format is very succint
            entries = {}
            for entry, data in r.items():
                if data == 'directory':
                    entries[entry] = { "type": "directory" }
                elif data != "0":
                    # we have a non-default digest
                    entries[entry] = { "type": "file", "digest": data }
                else:
                    entries[entry] = { "type": "file" }
            return entries


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
        if tmpname not in l:
            raise tc.failed_e(
                "after uploading %s, it is not listed" % tmpname,
                dict(l = l))
        target.report_pass("listed afer uploading one")

        tmpname2 = commonl.mkid(str(id(target))) + ".2"
        target.store.upload(tmpname2, __file__)
        target.report_pass("uploaded second file %s" % tmpname2)
        l = target.store.list()
        if tmpname2 not in l:
            raise tc.failed_e(
                "after uploading another file %s, it is not listed" % tmpname)
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
        target.report_pass("all files removed report empty list")
