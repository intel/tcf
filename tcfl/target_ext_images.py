#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Flash the target with JTAGs and other mechanism
------------------------------------------------

"""

import hashlib
import json
import os
import time

import requests

import commonl
from . import tc
from . import ttb_client
from . import msgid_c

class extension(tc.target_extension_c):
    """\
    Extension to :py:class:`tcfl.tc.target_c` to run methods from the
    image management interface to TTBD targets.

    Use as:

    >>> target.images.set()

    Presence of the *images* attribute in a target indicates imaging
    is supported by it.

    """

    def __init__(self, target):
        if 'images' not in target.rt.get('interfaces', []):
            raise self.unneeded

    #: When a deployment fails, how many times can we retry before
    #: failing
    retries = 4
    #: When power cycling a target to retry a flashing operation, how
    #: much many seconds do we wait before powering on
    wait = 4

    def list(self):
        """
        Return a list of image types that can be flashed in this target
        """
        r = self.target.ttbd_iface_call("images", "list", method = "GET")
        return r['result']


    def flash(self, images, upload = True):
        """Flash images onto target

        >>> target.images.flash({
        >>>         "kernel-86": "/tmp/file.bin",
        >>>         "kernel-arc": "/tmp/file2.bin"
        >>>     }, upload = True)

        or:

        >>> target.images.flash({
        >>>         "vmlinuz": "/tmp/vmlinuz",
        >>>         "initrd": "/tmp/initrd"
        >>>     }, upload = True)

        If *upload* is set to true, this function will first upload
        the images to the server and then flash them.

        :param dict images: dictionary keyed by (str) image type of
          things to flash in the target. e.g.:

          The types if images supported are determined by the target's
          configuration and can be reported with :meth:`list` (or
          command line *tcf images-ls TARGETNAME*).

        :param bool upload: (optional) the image names are local files
          that need to be uploaded first to the server (this function
          will take care of that).

        """
        if isinstance(images, dict):
            for k, v in images.items():
                assert isinstance(k, str) \
                    and isinstance(v, str), \
                    "images has to be a dictionary IMAGETYPE:IMAGEFILE;" \
                    " all strings; %s, %s (%s, %s)" \
                    % (k, v, type(k), type(v))
        else:
            raise AssertionError(
                "images has to be a dictionary IMAGETYPE:IMAGEFILE; got %s" \
                % type(images))

        target = self.target
        images_str = " ".join("%s:%s" % (k, v) for k, v in images.items())

        # if we have to upload them, then we'll transform the names to
        # point to the names we got when uploading
        if upload:
            # Ok, we need to upload--the names in the dictionary point
            # to local filenames relative to the dir where we are
            # from, or absolute. Upload them to the server file space
            # for the user and give them a local name in there.
            _images = {}
            target.report_info("uploading: " + images_str, dlevel = 2)
            for img_type, img_name in images.items():
                # the remote name will be NAME-DIGEST, so if multiple
                # testcases for the same user are uploading files with
                # the same name but different context, they don't
                # collide
                digest = commonl.hash_file(hashlib.sha256(), img_name)
                img_name_remote = \
                    digest.hexdigest()[:10] \
                    + "-" + commonl.file_name_make_safe(os.path.abspath(img_name))
                target.store.upload(img_name_remote, img_name)
                _images[img_type] = img_name_remote
                target.report_info("uploaded: " + images_str, dlevel = 1)
        else:
            _images = images

        # We don't do retries here, we leave it to the server
        target.report_info("flashing: " + images_str, dlevel = 2)
        target.ttbd_iface_call("images", "flash", images = _images)
        target.report_info("flashed: " + images_str, dlevel = 1)


def _cmdline_images_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "images")
        print("\n".join(target.images.list()))

def _image_list_to_dict(image_list):
    images = {}
    for image in image_list:
        if not ":" in image:
            raise AssertionError(
                "images has to be specified in the format IMAGETYPE:IMAGEFILE;"
                " got (%s) %s" % (type(image), image))
        k, v = image.split(":", 1)
        images[k] = v
    return images

def _cmdline_images_flash(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "images")
        target.images.flash(_image_list_to_dict(args.images),
                            upload = args.upload)


def _cmdline_setup(arg_subparser):
    ap = arg_subparser.add_parser(
        "images-ls",
        help = "List supported image types")
    commonl.argparser_add_aka(arg_subparser, "images-ls", "images-list")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target name")
    ap.set_defaults(func = _cmdline_images_list)

    ap = arg_subparser.add_parser(
        "images-flash",
        help = "(maybe upload) and flash images in the target")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name or URL")
    ap.add_argument("images", metavar = "TYPE:FILENAME",
                    action = "store", default = None, nargs = '+',
                    help = "Each FILENAME is (maybe uploaded to the daemon)"
                    " and then set as an image of the given TYPE;"
                    " FILENAME is assumed to be present in the server's"
                    " storage area (unless -u is given)")
    ap.add_argument("-u", "--upload",
                    action = "store_true", default = False,
                    help = "upload FILENAME first and then flash")
    ap.set_defaults(func = _cmdline_images_flash)
