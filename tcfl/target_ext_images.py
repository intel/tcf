#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Flash the target with JTAGs and other mechanism
------------------------------------------------

"""
import commonl
import hashlib
import json
import os
import string
import re
import time
import io
import contextlib
from pathlib import Path

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


    def read(self, image, file_name, image_offset = 0, read_bytes = None):
        """
        Reads data from the SPI
        """
        assert isinstance(image, str)
        assert isinstance(file_name, str)
        assert isinstance(image_offset, int)
        assert read_bytes == None or isinstance(read_bytes, int)

        assert image_offset >= 0, 'offset value should be positive'
        if read_bytes != None:
            assert read_bytes >= 0, 'bytes value should be positive'

        target = self.target
        target.report_info(f"{image}: reading image", dlevel = 1)

        with io.open(file_name, "wb+") as of, \
             contextlib.closing(self.target.ttbd_iface_call("images",
                                                            "flash",
                                                            method = "GET",
                                                            stream = True,
                                                            raw = True,
                                                            image=image,
                                                            image_offset=image_offset,
                                                            read_bytes=read_bytes)) as r:
            # http://docs.python-requests.org/en/master/user/quickstart/#response-content
            chunk_size = 4096
            total = 0
            for chunk in r.iter_content(chunk_size):
                of.write(chunk)
                total += len(chunk)	# not chunk_size, it might be less
            target.report_info(f"{image}: read image")
            target.report_info(f"{image}: image saved to {Path(file_name).resolve()}")
            return total

        return r['result']




    def flash(self, images, upload = True, timeout = None, soft = False,
              hash_target_name = True):
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

        :param int timeout: (optional) seconds to wait for the
          operation to complete; defaults to whatever the interface
          declares in property
          *interfaces.images.IMAGETYPE.estimated_duration*.

          This is very tool and file specific, a bigger file with a
          slow tool is going to take way longer than a bigfer file on
          a slow one.

        :param bool upload: (optional) the image names are local files
          that need to be uploaded first to the server (this function
          will take care of that).

        :param boot soft: (optional, default *False*) if *True*, it
          will only flash an image if the hash of the file is
          different to the hash of the last image recorded in that
          image type (or if there is no record of anything having been
          flashed).

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

        if timeout == None:
            timeout = 0
            for image_type, image in images.items():
                images_data = target.rt['interfaces']['images']
                image_data = images_data.get(image_type, None)
                if image_data == None:
                    raise tc.blocked_e("%s: image type '%s' not available"
                                       % (target.id, image_type),
                                       dict(target = target))
                timeout += image_data.get("estimated_duration", 60)
        else:
            assert isinstance(timeout, int)

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
                # the same name but different content / target, they don't
                # collide
                hd = commonl.hash_file_maybe_compressed(hashlib.sha512(), img_name)
                img_name_remote = \
                    hd[:10] \
                    + "-" + commonl.file_name_make_safe(os.path.abspath(img_name))
                if hash_target_name:
                    # put the target name first, otherwise we might
                    # alter the extension that the server relies on to
                    # autodecompress if need to
                    img_name_remote = target.id + "-" + img_name_remote
                last_sha512 = target.rt['interfaces']['images']\
                    [img_type].get('last_sha512', None)
                if soft and last_sha512 == hd:
                    # soft mode -- don't flash again if the last thing
                    # flashed has the same hash as what we want to flash
                    target.report_info(
                        "%s:%s: skipping (soft flash: SHA512 match %s)"
                        % (img_type, img_name, hd), dlevel = 1)
                    continue
                target.report_info("uploading: %s %s" %
                                   (img_type, img_name), dlevel = 3)
                target.store.upload(img_name_remote, img_name)
                _images[img_type] = img_name_remote
                target.report_info("uploaded: %s %s" %
                                   (img_type, img_name), dlevel = 2)
            target.report_info("uploaded: " + images_str, dlevel = 1)
        else:
            # no need to upload--means we are using files stored in
            # the server's FS already. But we need to check for soft
            # mode, so use the store interface to query for the remote
            # file's digest and compare against the last thing flashed.
            data = target.store.list(digest = "sha512",
                                     filenames = list(images.values()))
            _images = {}
            for img_type, img_name in images.items():
                last_sha512 = target.rt['interfaces']['images']\
                    [img_type].get('last_sha512', None)
                if soft and last_sha512 == data[img_name]:
                    # soft mode -- don't flash again if the last thing
                    # flashed has the same hash as what we want to flash
                    target.report_info(
                        "%s:%s: skipping (soft flash: SHA512 match %s)"
                        % (img_type, img_name, last_sha512), dlevel = 1)
                    continue
                _images[img_type] = img_name

        if _images:
            # We don't do retries here, we leave it to the server
            target.report_info("flashing: " + images_str, dlevel = 2)
            target.ttbd_iface_call("images", "flash", images = _images,
                                   timeout = timeout)
            target.report_info("flashed: " + images_str, dlevel = 1)
        else:
            target.report_info("flash: all images soft flashed", dlevel = 1)

    # match: [no-]upload [no-]soft IMGTYPE1:IMGFILE1 IMGTYPE2:IMGFILE2 ...
    _image_flash_regex = re.compile(
        r"((no-)?(soft|upload)\s+)*((\S+:)?\S+\s*)+")

    def flash_spec_parse(self, flash_image_s = None, env_prefix = "IMAGE_FLASH"):
        """Parse a images to flash specification in a string (that might be
        taken from the environment

        The string describing what to flash is in the form::

          [[no-]soft] [[no-]upload] IMAGE:NAME[ IMAGE:NAME[..]]]

        - *soft*: flash in soft mode (default *False) (see
          :meth:`target.images.flash
          <tcfl.target_ext_images.extension.flash>`) the image(s) will
          only be flashed if the image to be flashed is different than the
          last image that was flashed.

        - *upload*: flash in soft mode (default *True*) (see
          :meth:`target.images.flash
          <tcfl.target_ext_images.extension.flash>`). The file will be
          uploaded to the server first or it will be assumed it is already
          present in the server.

        - *IMAGETYPE:FILENAME* flash file *FILENAME* in flash destination
          *IMAGETYPE*; *IMAGETYPE* being any of the image
          destinations the target can flash; can be found with::

            $ tcf image-ls TARGETNAME

          or from the inventory::

            $ tcf get TARGETNAME -p interfaces.images

        The string specification will be taken, in this order from the
        following list

        - the *image_flash* parameter

        - environment *IMAGE_FLASH_<TYPE>*

        - environment *IMAGE_FLASH_<FULLID>*

        - environment *IMAGE_FLASH_<ID>*

        - environment *IMAGE_FLASH*

        With *TYPE*, *FULLID* and *ID* sanitized to any character outside
        of the ranges *[a-zA-Z0-9_]* replaced with an underscore (*_*).

        **Example**

        ::

          $ export IMAGE_FLASH_TYPE1="soft bios:path/to/bios.bin"
          $ tcf run test_SOMESCRIPT.py

        if *test_SOMESCRIPT.py* uses this template, every invocation of it
        on a machine of type TYPE1 will result on the file
        *path/to/bios.bin* being flashed on the *bios* location (however,
        because of *soft*, if it was already flashed before, it will be
        skipped).

        :return: a tuple of

          >>> ( DICT, UPLOAD, SOFT )

          - *DICT*: Dictionary is a dictionary of IMAGETYPE/file name to flash:

            >>> {
            >>>     IMGTYPE1: IMGFILE1,
            >>>     IMGTYPE2: IMGFILE2,
            >>>     ...
            >>> }

          - *UPLOAD*: boolean indicating if the user wants the files to be
            uploaded (*True*, default) or to assume they are already in
            the server (*False*).

          - *SOFT*: flash in soft mode (*True*) or not (*False*, default
            if not given).

        """
        target = self.target
        if not flash_image_s:

            # empty, load from environment
            target_id_safe = commonl.name_make_safe(
                target.id, string.ascii_letters + string.digits)
            target_fullid_safe = commonl.name_make_safe(
                target.fullid, string.ascii_letters + string.digits)
            target_type_safe = commonl.name_make_safe(
                target.type, string.ascii_letters + string.digits)

            source = None	# keep pylint happy
            sourcel = [
                # go from most specifcy to most generic
                # IMAGE_FLASH_SERVER_NAME
                # IMAGE_FLASH_NAME
                # IMAGE_FLASH_TYPE
                # IMAGE_FLASH
                f"{env_prefix}_{target_fullid_safe}",
                f"{env_prefix}_{target_id_safe}",
                f"{env_prefix}_{target_type_safe}",
                env_prefix,
            ]
            for source in sourcel:
                flash_image_s = os.environ.get(source, None)
                if flash_image_s != None:
                    break
            else:
                target.report_info(
                    "skipping image flashing (no function argument nor environment: %s)"
                    % " ".join(sourcel))
                return {}, False, False
        else:
            source = "function argument"

        # verify the format
        if not self._image_flash_regex.search(flash_image_s):
            raise tc.blocked_e(
                "image specification in %s does not conform to the form"
                " [[no-]soft] [[no-]upload] [IMAGE:]NAME[ [IMAGE:]NAME[..]]]" % source,
                dict(target = target))

        image_flash = {}
        soft = False
        upload = True
        for entry in flash_image_s.split(" "):
            if not entry:	# empty spaces...welp
                continue
            if entry == "soft":
                soft = True
                continue
            if entry == "no-soft":
                soft = False
                continue
            if entry == "upload":
                upload = True
                continue
            if entry == "no-upload":
                upload = False
                continue
            # see if we can assume this is in the form
            # [SOMEPATH/]FILENAME[.EXT]; if FILENAME matches a known
            # flashing destination, we take it
            if ":" in entry:
                name, value = entry.split(":", 1)
                image_flash[name] = value
            else:
                basename, _ext = os.path.splitext(os.path.basename(entry))
                # if the inventory publishes a
                # interfaces.images.basename, this means we have a
                # flasher where this can go
                image_typel = list(target.rt.get("interfaces", {}).get("images", {}))
                for image_type in image_typel:
                    if basename.startswith(image_type):
                        image_flash[image_type] = entry
                        break
                else:
                    raise RuntimeError(
                        "%s: can't auto-guess destination for this "
                        "file, please prefix IMAGETYPE: "
                        "(known are: %s)" % (entry, " ".join(image_typel)))

        return image_flash, upload, soft

def _cmdline_images_read(args):
    tc.tc_global = tc.tc_c("cmdline", "", "builtin")
    tc.report_driver_c.add(		# FIXME: hack console driver
        tc.report_console.driver(1, None))
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "images")
        target.images.read(args.image, args.filename, args.offset, args.bytes)

def _cmdline_images_list(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "images")
        print("\n".join(target.images.list()))

def _cmdline_images_flash(args):
    tc.tc_global = tc.tc_c("cmdline", "", "builtin")
    tc.report_driver_c.add(		# FIXME: hack console driver
        tc.report_console.driver(4, None))
    with msgid_c(""):
        target = tc.target_c.create_from_cmdline_args(args, iface = "images")
        images, _upload, _soft = target.images.flash_spec_parse(" ".join(args.images))
        target.images.flash(images, upload = args.upload, timeout = args.timeout,
                            soft = args.soft)


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
    ap.add_argument("images", metavar = "[TYPE:]FILENAME",
                    action = "store", default = None, nargs = '+',
                    help = "Each FILENAME is (maybe uploaded to the daemon)"
                    " and then set as an image of the given TYPE;"
                    " FILENAME is assumed to be present in the server's"
                    " storage area (unless -u is given);"
                    " TYPE can be omitted if the file name starts with"
                    " the name of an image (eg: ~/place/bios-433 would"
                    " be flashed into 'bios' if the target exposes the"
                    " 'bios' flash destination)")
    ap.add_argument("-u", "--upload",
                    action = "store_true", default = False,
                    help = "upload FILENAME first and then flash")
    ap.add_argument("-s", "--soft",
                    action = "store_true", default = False,
                    help = "soft flash (only flash if the file's"
                    " signature is different to the last one flashed)")
    ap.add_argument("-t", "--timeout",
                    action = "store", default = None, type = int,
                    help = "timeout in seconds [default taken from"
                    " what the server declares or 1m if none]")
    ap.set_defaults(func = _cmdline_images_flash)



    ap = arg_subparser.add_parser(
        "images-read",
        help = "Read image from the target")
    ap.add_argument("target", metavar = "TARGET", action = "store",
                    default = None, help = "Target's name")
    ap.add_argument("image", metavar = "TYPE",
                    action = "store", default = None,
                    help = "Image we are reading from")
    ap.add_argument("filename", metavar = "FILENAME",
                    action = "store", default = None,
                    help = "File to create and write to")
    ap.add_argument("-o", "--offset",
                    action = "store", default = 0, type = int,
                    help = "Base offset from 0 bytes to read from")
    ap.add_argument("-b", "--bytes",
                    action = "store", default = None, type = int,
                    help = "Bytes to read from the image"
                    " (Defaults to reading the whole image)")
    ap.set_defaults(func = _cmdline_images_read)
