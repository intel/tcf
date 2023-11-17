#! /usr/bin/python3
#
# Copyright (c) 2017-23 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Command line interface UI to flash JTAGS, EEPROMs, firmwares...
---------------------------------------------------------------

The following UI commands are available (use ``--help`` on each to
learn more about them):

- list destinations that can be flashed::

    $ tcf images-ls TARGETSPEC

- flash files onto destinations::

    $ tcf images-flash TARGETSPEC [DEST:FILE [DEST:FILE [...]]

- write partial data into a destination::

    $ tcf images-write TARGETSPEC DEST OFFSET:DATA

"""
import concurrent.futures
import argparse
import collections
import hashlib
import logging
import os
import re
import sys
import time
import traceback

import commonl
import tcfl
import tcfl.ui_cli

logger = logging.getLogger("ui_cli_images")



def _images_list(target):
    return target.images.list()

def _cmdline_images_ls(cli_args: argparse.Namespace):

    r = tcfl.targets.run_fn_on_each_targetspec(
        _images_list, cli_args.target,
        targets_all = cli_args.all,
        iface = "images", extensions_only = [ 'images' ])

    verbosity = cli_args.verbosity - cli_args.quietosity
    # r now is a dict keyed by target_name and tuples of images an
    # maybe an exception, which we don't cavre for

    if not r:
        logger.error(
            f"No targets match the specification (might be disabled, try -a):"
            f" {' '.join(cli_args.target)}")
        return 0

    d = {}
    targetid = None
    for targetid, ( images, _e, _tb ) in r.items():
        if images:
            d[targetid] = images

    # note the hack, targetid falls through from the only for loop
    # execution when len(d) == 1
    if verbosity == 0:
        if len(d) == 1:
            # there is only one, print a simple liust
            print(" ".join(d[targetid]))
        else:
            for targetid, v in d.items():
                print(f"{targetid}: " + " ".join(v))
    elif verbosity == 1:
        if len(d) == 1:
            # there is only one, print a simple liust
            print("\n".join(d[targetid]))
        else:
            for targetid, v in d.items():
                for dest in v:
                    print(f"{targetid}: {dest}")
    elif verbosity == 2:
        import commonl
        commonl.data_dump_recursive(d)
    elif verbosity == 3:
        import pprint
        pprint.pprint(d, indent = True)
    elif verbosity > 3:
        import json
        json.dump(d, sys.stdout, indent = 4)
        print()
    sys.stdout.flush()



def _images_flash_parse(target, image_spec):
    # parse the image specification with the specifics of the target;
    # the image specification might include fields from the inventory,
    # hence why we have to do it target-specific.
    return target.images.flash_spec_parse(image_spec)


def _images_flash_upload(server_name, _server,
                         uploads_by_server, targets_by_server):

    # upload a list of files to a server given in uploads_by_server

    uploads = uploads_by_server.get(server_name, set())
    if not uploads:	# this server needs nothing uploaded to it
        return {}

    # Ok, we need to upload--the names in the dictionary point
    # to local filenames relative to the dir where we are
    # from, or absolute. Upload them to the server file space
    # for the user

    logger.info("uploading to %s: %s", server_name, " ".join(uploads))
    # we need a target to upload to; it doesn't matter, all the
    # targets share the same local space in the server
    target = tcfl.tc.target_c.create(
                    targets_by_server[server_name],
                    iface = "store", extensions_only = [ "store" ],
                    target_discovery_agent = tcfl.targets.discovery_agent)

    # mapping of local name to remote name, we'll need it to flash
    uploaded_names = {}

    for img_name in uploads:
        # When uploading the file, use a different remote file name
        #
        # The remote name will be DIGEST-NAME, so if multiple
        # testcases for the same user are uploading files with the
        # same name but different content / target, they don't collide
        # We also give them a local name in there that encodes the
        # local path to help differentiate the same user uploading the
        # same file from different locations (eg: /tmp/bios and
        # /tmp/test1/bios)
        hd = commonl.hash_file_maybe_compressed(hashlib.sha512(), img_name)
        img_name_remote = \
            hd[:10] \
            + "-" + commonl.file_name_make_safe(os.path.abspath(img_name))
        uploaded_names[img_name] = img_name_remote
        logger.debug("uploading to %s: %s", server_name, img_name)
        target.store.upload(img_name_remote, img_name)
        logger.info("uploaded to %s: %s", server_name, img_name)
    logger.warning("uploaded to %s: %s", server_name, " ".join(uploads))

    # return the mapping of locanames -> uploaded names, we'll need it
    # when telling the targets what to flash
    return uploaded_names


def _images_flash(target, image_spec_per_target, uploaded_names, timeout):
    # flash the parsed/resolved images in @image_spec_per_target for
    # this target, maybe translating the name from @uploaded_names
    images, _upload, soft = image_spec_per_target.get(
        # FIXME: ugly workaround: run_fn_on_eachtargetspec returns an
        # array keyed by targetid, which is kinda iffy because we
        # don't necessarily know if it is an id or fullid -- so until
        # we fix that, try both
        target.fullid,
        image_spec_per_target[target.id])[0]
    image_spec = " ".join(f"{k}:{v}" for k, v in images.items())
    ts0 = time.time()
    # if we have uploaded the files, they might have a slightly
    # different name in the server (added hashes to avoid collisions,
    # etc), so update that
    for image_type, image_name in list(images.items()):
        if image_name in uploaded_names:
            images[image_type] = uploaded_names[image_name]
    print(f"{target.id}: flashing {image_spec}")
    sys.stdout.flush()
    r = target.images.flash(images,		# ok, flash now
                            upload = False,	# we already uploaded
                            timeout = timeout, soft = soft)
    ts = time.time()
    print(f"{target.id}: flashed {image_spec} in {ts - ts0:.1f}s")
    sys.stdout.flush()
    return r



def _cmdline_images_flash(cli_args: argparse.Namespace):

    # Flash one or more images in one or more targets
    #
    # This simple operation gets surprisingly complicated really quick
    # so we can make it flexible; the GOAL is to be able to flash a ton of
    # machines at the same time with a single command.
    #
    # What we flash (the flashing spec) is target specific, since the
    # flashing spec can include fields from the inventory (eg:
    # bios:/some/path/bios-%(type)s.bin would append the target's type
    # to the bios file name to flash).
    #
    # So we need to parse first for each target; we also need to first
    # extract all fields from the specs to ensure when we query
    # inventory we get those fields.
    #
    # Then we fold on two scenarios:
    #
    # A. Files are in the server already (either uploiaded or in a
    #    server folder)
    #
    # B. Files are in the local machine, they need to be uploaded to
    #    the server first
    #
    #    Not all files are needed in all servers and there is no need
    #    to upload the same file twice, so we need to be a bit smart
    #    about it; also since the same user might be running flashing
    #    on other processe, we want to assign slightly different names
    #    to what we upload vs the local file name, just in case.
    #
    # Once all this is done, we can then flash, taking into account
    # that if we uploaded, we need to change the names vs what is in
    # was uploaded to the server

    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    # The flashing image spec might include fields we'll need to pull
    # from the inventory, so extract those
    projections = set()
    # regex to match python replace-fields %(<FIELDNAME>)<TYPE>
    field_regex = re.compile(r"%\([-\._a-zA-Z0-9]+\)[a-z]")
    # now find what inventory fields are used in the image
    # specification, to make sure we query them
    for spec in cli_args.images:
        for field in re.findall(field_regex, spec):
            # field is now %(FIELDNAME)FORMAT, so extract
            field = field[2:]
            # now it is FIELDNAME)FORMAT
            field = field.split(')')[0]
            projections.add(field)
    logger.info("inventory fields from image spec: %s",
                " ".join(projections))
    # let's format like flash_parse_spec() likes it
    image_spec = " ".join(cli_args.images)
    if cli_args.upload:
        image_spec += " upload"
    else:
        image_spec += " no-upload"
    if cli_args.soft:
        image_spec += " soft"
    else:
        image_spec += " no-soft"
        
    # parse the flashing spec; this is done per target, since the
    # image spec might include inventoryfields that are target
    # specific (eg: type)
    image_spec_per_target = tcfl.targets.run_fn_on_each_targetspec(
        _images_flash_parse, cli_args.target, image_spec,
        targets_all = cli_args.all,
        ifaces = [ "images", "store" ],
        extensions_only = [ 'images', 'store' ],
        projections = projections)

    if not image_spec_per_target:
        logger.error(
            f"No targets match the specification (might be disabled, try -a):"
            f" {' '.join(cli_args.target)}")
        return 0

    
    # image_spec_per_target is { TARGETID: ( ( DICT, UPLOAD, SOFT ), e ) }
    # DICT is the map of image files to flash on what image destination:
    # { IMGTYPE1: IMGFILE 1, ... }

    # So now we need to create an index by server of which images need
    # to be loaded to what server; we extract the server from the
    # target's inventory info
    uploads_by_server = collections.defaultdict(set)
    targets_by_server = {}
    for targetid, ( result, e, tb ) in image_spec_per_target.items():
        if e != None:
            tb = "\n  ".join(tb)
            logger.error(f"can't parse flashing spec '{image_spec}'"
                          f" for {targetid}: {e}\n{tb}")
            continue
        imgdata, upload, _soft = result
        if not upload:
            continue
        rt = tcfl.rts[targetid]
        server_name = rt['server']
        uploads_by_server[server_name].update(imgdata.values())
        if server_name not in targets_by_server:
            targets_by_server[server_name] = targetid


    # Now uploads_by_server is kinda like:
    #
    # {
    #     SERVER1: { FILE1, FILE2, FILE3 },
    #     SERVER2: { FILE1, FILE4 },
    #     SERVER3: { FILE5 },
    #     ...
    # }
    #
    # So let's upload
    uploaded_names = {}
    if uploads_by_server:

        # upload the file once to each server, no need to upload to
        # each target
        r = tcfl.servers.run_fn_on_each_server(
            tcfl.server_c.servers, _images_flash_upload,
            uploads_by_server, targets_by_server,
            parallelization_factor = cli_args.parallelization_factor,
            traces = cli_args.traces)
        for server_name, ( _uploaded_names, e, tb ) in r.items():
            if e != None:
                if cli_args.traces:
                    tb = "\n" + "".join(tb)
                else:
                    tb = ""
                logger.error("%s: can't upload: %s%s", server_name, e, tb)
            else:
                uploaded_names.update(_uploaded_names)

    # now flash -- if we uploaded, flash the uploaded files (which
    # will have a different name, to avoid collisions)
    r = tcfl.targets.run_fn_on_each_targetspec(
        _images_flash, cli_args.target,
        image_spec_per_target, uploaded_names, cli_args.timeout,
        pool_type = concurrent.futures.ProcessPoolExecutor,
        targets_all = cli_args.all,
        iface = "images", extensions_only = [ 'images', 'store' ])

    # check errors
    retval = 0
    for targetid, ( result, e, tb ) in r.items():
        image_specl = []
        # image_spec_per_target looks like
        #
        ## {
        ##     'target1': (
        ##         (    # destinations dict, upload images, soft flash
        ##             {
        ##                 'bios': '/gfs/BKC/BHS-AVC-GNR/BKC_HEALTHCHECK_A0/bios',
        ##                 'bmc': '/gfs/BKC/BHS-AVC-GNR/BKC_HEALTHCHECK_A0/bmc'
        ##             },
        ##             False,
        ##             False
        ##         ),
        ##         None		# exception info if any ([0] would be None)
        ##     ),
        ##     'target2': (
        ##         None,
        ##         RuntimeError('target2: target does not support the images interface')
        ##     )
        ## }
        ir, ie, _itb = image_spec_per_target[targetid]
        if ie == None and ir != None:
            # note these ir, ie are for the result/e stored
            # image_spec_per_target[targetid] that is different to
            # that of the r.items() loop
            # ir is now ( destinations dict, upload images, soft flash )
            dest_dict = ir[0]
            for k, v in dest_dict.items():
                image_specl.append(f"{k}:{v}")
        image_spec = " ".join(image_specl)

        if e != None:
            tb = "\n  ".join(tb)
            logger.error(
                f"{targetid}: can't flash spec '{image_spec}': {e}\n{tb}")
            retval += 1
            continue
    return retval



def _images_read(target, image, filename, offset, length):
    logger.info("reading %dB from offset %s of %s", length, offset, image)
    target.images.read(image, filename, offset, length)

def _cmdline_images_read(cli_args: argparse.Namespace):

    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _images_read, cli_args,
        cli_args.image, cli_args.filename, cli_args.offset, cli_args.length,
        only_one = True,
        targets_all = cli_args.all,
        iface = "images", extensions_only = [ 'images' ])[0]



def _image_write(target, image: str, data: list):
    values = {}
    for item in data:
        offset, data = item.split(":")
        try:
            # list of bytes
            if re.match(r'^\[.*\]$', data):
                import ast	# import only if needed
                data = bytes(ast.literal_eval(data))
            # hex value
            elif re.match('^(0x)?[a-fA-F0-9]+$', data):
                if data.startswith("0x"):
                    data = data[2:]
                data = bytes.fromhex(data)
            # bytes string
            elif re.match('^b[\'\"].+[\'\"]$', data):
                data = data[2:-1].encode('utf-8')
            # normal string
            else:
                data = data.encode('utf-8')
            values[offset] = data
        except (TypeError, ValueError) as e:
            raise type(e)(f"value \"{data}\" must be valid bytes")
    logger.info("writing @%s: %s", image, values)
    target.images.write(image, values)


def _cmdline_image_write(cli_args: argparse.Namespace):

    tcfl.ui_cli.logger_verbosity_from_cli(logger, cli_args)

    return tcfl.ui_cli.run_fn_on_each_targetspec(
        _image_write, cli_args,
        cli_args.image, cli_args.data,
        only_one = True,
        targets_all = cli_args.all,
        iface = "images", extensions_only = [ 'images' ])[0]



def _cmdline_setup(arg_subparser):

    ap = arg_subparser.add_parser(
        f"images-ls",
        help = "List destinations that can be flashed in this target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.set_defaults(func = _cmdline_images_ls)


    ap = arg_subparser.add_parser(
        "images-flash",
        help = "(maybe upload) and flash images in the target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap, nargs = 1)
    ap.add_argument(
        "-u", "--upload",
        action = "store_true", default = False,
        help = "upload FILENAME first and then flash")
    ap.add_argument(
        "-s", "--soft",
        action = "store_true", default = False,
        help = "soft flash (only flash if the file's"
        " signature is different to the last one flashed)")
    ap.add_argument(
        "-t", "--timeout",
        action = "store", default = None, type = int,
        help = "timeout in seconds [default taken from"
        " what the server declares or 1m if none]")
    ap.add_argument(
        "images", metavar = "[TYPE:]FILENAME",
        action = "store", default = None, nargs = '+',
        help = "Each FILENAME is (maybe uploaded to the daemon) and then"
        " set as an image of the given TYPE; FILENAME is assumed to be"
        " present in the server's storage area (unless -u is given);"
        " TYPE can be omitted if the file name starts with the name of an"
        " image (eg: ~/place/bios-433 would be flashed into 'bios' if the"
        " target exposes the 'bios' flash destination). Note filenames can"
        " contain %%(FIELD)s strings that will be expanded from the"
        " inventory.")
    ap.set_defaults(func = _cmdline_images_flash)



def _cmdline_setup_advanced(arg_subparser):

    ap = arg_subparser.add_parser(
        "images-read",
        help = "Read image from the target")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "image", metavar = "TYPE",
        action = "store", default = None,
        help = "Image we are reading from")
    ap.add_argument(
        "filename", metavar = "FILENAME",
        action = "store", default = None,
        help = "File to create and write to")
    ap.add_argument(
        "-o", "--offset",
        action = "store", default = 0, type = int,
        help = "Base offset from 0 bytes to read from")
    ap.add_argument(
        "-b", "--bytes", dest = "length",
        action = "store", default = None, type = int,
        help = "Bytes to read from the image"
        " (defaults to reading the whole image)")
    ap.set_defaults(func = _cmdline_images_read)

    ap = arg_subparser.add_parser(
        "images-write",
        help = "Write data to specified offset in image")
    tcfl.ui_cli.args_verbosity_add(ap)
    tcfl.ui_cli.args_targetspec_add(ap)
    ap.add_argument(
        "image", metavar = "TYPE",
        action = "store", default = None,
        help = "Image we are writing to (eg: bios)")
    ap.add_argument(
        "data", metavar = "OFFSET:DATA", nargs = '+',
        action = "store", default = None,
        help = "offset and data to write; the data can be specified as"
        " a hex string (eg: 334:0f3456a1 would write bytes 0x0f 0x34"
        " 0x56 0xa1 to offset 334) or a normal string ")
    ap.set_defaults(func = _cmdline_image_write)
