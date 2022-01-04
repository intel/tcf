#! /usr/bin/python3
#
# Copyright (c) 2017-20 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
"""
File storage interface
----------------------

Export an interface on each target that allows the user to:

- upload files to the servr
- download files from the server
- remove said files form the server
- list them

each user has a separate storage area, flat in structure (no
subdirectories) which can be use to place blobs which might be removed
by the server after a certain time based on policy. Note these storage
areas are common to all the targets for each user.

Examples:

- upload files to the server than then other tools will
  use to (eg: burn into a  Flash ROM).

"""
import errno
import glob
import hashlib
import os
import pathlib
import re
import stat

import commonl
import ttbl

#: List of paths in the systems where clients are allowed to read
#: files from
#:
#: Each entry is the path is the top level directory the user can
#: specify and the value is the mapping into the real file system path.
#:
#: In any :ref:`server configuration file <ttbd_configuration>`, add:
#:
#: >>> ttbl.store.paths_allowed['/images'] = '/home/SOMEUSER/images'
#:
#: Note it is not allowed to upload files to these locations, just to
#: list and download.
paths_allowed = {
}

class interface(ttbl.tt_interface):

    def __init__(self):
        ttbl.tt_interface.__init__(self)

    def _target_setup(self, target, iface_name):
        pass

    def _release_hook(self, target, _force):
        pass

    _bad_path = re.compile(r"(^\.\.$|^\.\./|/\.\./|/\.\.$)")

    # Paths allowed to access in TARGETSTATEDIR/PATH
    target_sub_paths = {
        # PATH1: False,          # read-only
        # PATH2: True,           # read-write
        # For the capture interface FIXME move to ttbl/capture.py
        "capture": False,
    }

    def _validate_file_path(self, target, file_path, user_path):
        matches = self._bad_path.findall(file_path)
        if matches \
           or os.path.pardir in file_path:
            raise ValueError("%s: file path cannot contains components: "
                             "%s" % (file_path, " ".join(matches)))

        if target:
            for subpath, rw in self.target_sub_paths.items():
                if file_path.startswith(subpath + "/"):
                    # file comes from the targt's designated state
                    # directory (capture, certificates) remove any
                    # possible nastiness
                    file_name = os.path.basename(file_path)
                    file_path_final = os.path.join(target.state_dir, subpath, file_name)
                    return file_path_final, rw

        # fall through
        if not os.path.isabs(file_path):
            # file comes from the user's storage
            file_path_normalized = os.path.normpath(file_path)
            file_path_final = os.path.join(user_path, file_path_normalized)
            return file_path_final, True

        # file from the system (mounted FS or similar);
        # double check it is allowed
        for path, path_translated in paths_allowed.items():
            if file_path.startswith(path):
                file_path = file_path.replace(path, path_translated, 1)
                file_path_final = os.path.normpath(file_path)
                return file_path_final, False	# FIXME: always read-only?

        # FIXME: use PermissionError in Python3
        raise RuntimeError(
            "%s: tries to read from a location that is not allowed"
            % file_path)

    def _validate_path(self, target, path):
        if target:
            for subpath, _rw in self.target_sub_paths.items():
                if path.startswith(subpath + "/") or path == subpath:
                    # file comes from the targt's designated state
                    # directory (capture, certificates) remove any
                    # possible nastiness
                    return os.path.join(target.state_dir, subpath)

        for valid_path, translated_path in paths_allowed.items():
            if path.startswith(valid_path):
                return path.replace(valid_path, translated_path, 1)
        raise RuntimeError("%s: path not allowed" % path)

    valid_digests = {
        "md5": "MD5",
        "sha256": "SHA256",
        "sha512": "SHA512",
        "zero": "no signature"
    }

    def _get_list(self, target, _who, args, _files, user_path, version):
        filenames = self.arg_get(args, 'filenames', list,
                                 allow_missing = True, default = [ ])
        path = self.arg_get(args, 'path', str,
                            allow_missing = True, default = None)
        if path == None:
            path = user_path
        elif path == "/":
            pass	# special handling
        else:
            path = self._validate_path(target, path)

        if version == 1:
            digest_default = "sha256"
        else:
            digest_default = "zero"
        digest = self.arg_get(args, 'digest', str,
                              allow_missing = True, default = digest_default)
        if digest not in self.valid_digests:
            raise RuntimeError("%s: digest not allowed (only %s)"
                               % digest, ", ".join(self.valid_digests))

        def _entry(path, digest):
            # return data about a path
            #
            # version 1
            # - default digest: sha256
            # - returns a string with digest or "directory"
            #
            # version 2
            # - default digest: zero (less load on the system)
            # - returns dict
            #     type: directory / file / link / unknown (others)
            #     size: (if type == "file") in bytes
            #     digest: (if file and not default digest) str
            #     aliases: if link, target of link
            if version == 1:
                s = os.stat(path)
                if stat.S_ISDIR(s.st_mode):
                    return "directory"
                if digest == "zero":
                    return "0"
                return commonl.hash_file_cached(path, digest)

            s = os.stat(path, follow_symlinks = False)
            d = {}
            if stat.S_ISDIR(s.st_mode):
                d['type'] = "directory"
            elif stat.S_ISLNK(s.st_mode):
                real_path = str(pathlib.Path(path).resolve())
                d = _entry(real_path, digest)
                # we don't want to publish the whole path, only the first
                # link. Why? Because we can assume the user who is opening the
                # path has control over the path itself, but if this is
                # pointing to internals of the system, then the user might
                # have no more control. So we resolve to get the data, but we
                # only publish the first link.
                d['aliases'] = os.readlink(path)
            elif stat.S_ISREG(s.st_mode):
                d['type'] = "file"
                d['size'] = s.st_size
                if digest and digest != "zero":
                    # note file path is normalized, so we shouldn't
                    # get multiple cache entries for different paths
                    d['digest'] = commonl.hash_file_cached(path, digest)
            else:
                d['type'] = "unknown"
            return d


        file_data = {}
        if path == "/":
            # we want the top level list of folders, handle it specially
            for path in paths_allowed:
                file_data[path] = _entry(paths_allowed[path], digest)
            return file_data

        def _list_filename(index_filename, filename):
            file_path = os.path.join(path, filename)
            try:
                file_data[index_filename] = _entry(file_path, digest)
            except ( OSError, IOError ) as e:
                if e.errno != errno.ENOENT:
                    raise
                # the file does not exist, ignore it

        if filenames:
            for filename in filenames:
                if not isinstance(filename, str):
                    continue
                file_path, _rw = self._validate_file_path(target, filename, path)
                _list_filename(filename, file_path)
        else:
            # we only list what is in that path, no going down, so use
            # glob, kinda simpler
            for name in glob.glob(path + "/*"):
                index_filename = os.path.basename(name)
                _list_filename(index_filename, index_filename)
        return file_data


    def get_list(self, target, _who, args, _files, user_path):
        r = self._get_list(target, _who, args, _files, user_path,
                           version = 1)
        r['result'] = dict(r)	# COMPAT
        return r


    def get_list2(self, target, _who, args, _files, user_path):
        r = self._get_list(target, _who, args, _files, user_path,
                           version = 2)
        return r


    def post_file(self, target, _who, args, files, user_path):
        # we can only upload to the user's storage path, never to
        # paths_allowed -> hence why we alway prefix it.
        file_path = self.arg_get(args, 'file_path', str)
        file_path_final, rw = self._validate_file_path(target, file_path, user_path)
        if not rw:
            raise PermissionError(f"{file_path}: is a read only location")
        file_object = files['file']
        file_object.save(file_path_final)
        commonl.makedirs_p(user_path)
        target.log.debug("%s: saved" % file_path_final)
        return dict()

    def get_file(self, target, _who, args, _files, user_path):
        # we can get files from the user's path or from paths_allowed;
        # an absolute path is assumed to come from paths_allowed,
        # otherwise from the user's storage area.
        file_path = self.arg_get(args, 'file_path', str)
        offset = self.arg_get(args, 'offset', int,
                              allow_missing = True, default = 0)
        file_path_final, _ = self._validate_file_path(target, file_path, user_path)
        # interface core has file streaming support builtin
        # already, it will take care of streaming the file to the
        # client
        try:
            generation = os.readlink(file_path_final + ".generation")
        except OSError:
            generation = 0
        # ttbd will parse this response in _target_interface() to
        # return a raw file according to these parameters.
        return dict(
            stream_file = file_path_final,
            stream_generation = generation,
            stream_offset = offset,
        )

    def delete_file(self, target, _who, args, _files, user_path):
        file_path = self.arg_get(args, 'file_path', str)
        file_path_final, rw = self._validate_file_path(target, file_path, user_path)
        if not rw:
            raise PermissionError(f"{file_path}: is a read only location")
        commonl.rm_f(file_path_final)
        return dict()
