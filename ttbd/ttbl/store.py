#! /usr/bin/python
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
import hashlib
import os
import re

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

    def _validate_file_path(self, target, file_path, user_path):
        matches = self._bad_path.findall(file_path)
        if matches \
           or os.path.pardir in file_path:
            raise ValueError("%s: file path cannot contains components: "
                             "%s" % (file_path, " ".join(matches)))

        if target and file_path.startswith("capture/"):
            # file comes from the targt's capture space
            # remove any possible nastiness
            file_name = os.path.basename(file_path)
            file_path_final = os.path.join(target.state_dir, "capture", file_name)
        elif not os.path.isabs(file_path):
            # file comes from the user's storage
            file_path_normalized = os.path.normpath(file_path)
            file_path_final = os.path.join(user_path, file_path_normalized)
        else:
            # file from the system (mounted FS or similar);
            # double check it is allowed
            for path, path_translated in paths_allowed.items():
                if file_path.startswith(path):
                    file_path = file_path.replace(path, path_translated, 1)
                    file_path_final = os.path.normpath(file_path)
                    break
            else:
                # FIXME: use PermissionError in Python3
                raise RuntimeError(
                    "%s: tries to read from a location that is not allowed"
                    % file_path)

        return file_path_final

    @staticmethod
    def _validate_path(path):
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

    def get_list(self, target, _who, args, _files, user_path):
        filenames = self.arg_get(args, 'filenames', list,
                                 allow_missing = True, default = [ ])
        path = self.arg_get(args, 'path', basestring,
                            allow_missing = True, default = None)
        if path == None:
            path = user_path
        elif path == "/":
            pass	# special handling
        else:
            path = self._validate_path(path)
        digest = self.arg_get(args, 'digest', basestring,
                              allow_missing = True, default = "sha256")
        if digest not in self.valid_digests:
            raise RuntimeError("%s: digest not allowed (only %s)"
                               % digest, ", ".join(self.valid_digests))

        file_data = {}
        if path == "/":
            # we want the top level list of folders, handle it specially
            for path in paths_allowed:
                file_data[path] = "directory"
            file_data['result'] = dict(file_data)	# COMPAT
            return file_data

        def _list_filename(index_filename, filename):
            file_path = os.path.join(path, filename)
            try:
                if digest == "zero":
                    file_data[index_filename] = "0"
                else:
                    # note file path is normalized, so we shouldn't
                    # get multiple cahce entries for different paths
                    file_data[index_filename] = commonl.hash_file_cached(file_path, digest)
            except ( OSError, IOError ) as e:
                if e.errno != errno.ENOENT:
                    raise
                # the file does not exist, ignore it

        if filenames:
            for filename in filenames:
                if not isinstance(filename, basestring):
                    continue
                file_path = self._validate_file_path(None, filename, path)
                if os.path.isdir(file_path):
                    file_data[filename] = 'directory'
                else:
                    _list_filename(filename, file_path)
        else:
            for _path, dirnames, files in os.walk(path, topdown = True):
                for filename in files:
                    _list_filename(filename, filename)
                for dirname in dirnames:
                    file_data[dirname] = 'directory'
                # WE ONLY generate the list of the path, not for
                # subpaths -- by design we only do the first level
                # because otherwise we could be generating a lot of
                # load in the system if a user makes a mistake and
                # keeps asking for a recursive list.
                # FIXME: throttle this call
                break
        file_data['result'] = dict(file_data)	# COMPAT
        return file_data

    def post_file(self, target, _who, args, files, user_path):
        # we can only upload to the user's storage path, never to
        # paths_allowed -> hence why we alway prefix it.
        file_path = self.arg_get(args, 'file_path', basestring)
        if os.path.isabs(file_path):
            raise RuntimeError(
                "%s: trying to upload a file to an area that is not allowed"
                % file_path)
        file_object = files['file']
        file_path_final = self._validate_file_path(None, file_path, user_path)
        commonl.makedirs_p(user_path)
        file_object.save(file_path_final)
        target.log.debug("%s: saved" % file_path_final)
        return dict()

    def get_file(self, target, _who, args, _files, user_path):
        # we can get files from the user's path or from paths_allowed;
        # an absolute path is assumed to come from paths_allowed,
        # otherwise from the user's storage area.
        file_path = self.arg_get(args, 'file_path', basestring)
        offset = self.arg_get(args, 'offset', int,
                              allow_missing = True, default = 0)
        file_path_final = self._validate_file_path(target, file_path, user_path)
        # interface core has file streaming support builtin
        # already, it will take care of streaming the file to the
        # client
        try:
            generation = os.readlink(file_path_final + ".generation")
        except OSError:
            generation = 0
        return dict(
            stream_file = file_path_final,
            stream_generation = generation,
            stream_offset = offset,
        )

    def delete_file(self, target, _who, args, _files, user_path):
        file_path = self.arg_get(args, 'file_path', str)
        if os.path.isabs(file_path):
            raise RuntimeError(
                "%s: trying to delete a file from an area that is not allowed"
                % file_path)

        file_path_final = self._validate_file_path(target, file_path, user_path)
        commonl.rm_f(file_path_final)
        return dict()
