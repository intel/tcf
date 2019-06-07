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

import time

import requests

from . import tc
from . import ttb_client

from . import msgid_c

class images(tc.target_extension_c):
    """\
    Extension to :py:class:`tcfl.tc.target_c` to run methods from the
    image management interface to TTBD targets.

    Use as:

    >>> target.images.set()

    Presence of the *images* attribute in a target indicates imaging
    is supported by it.

    """

    def __init__(self, target):
        if not 'test_target_images_mixin' in target.rt.get('interfaces', []):
            raise self.unneeded

    #: When a deployment fails, how many times can we retry before
    #: failing
    retries = 4
    #: When power cycling a target to retry a flashing operation, how
    #: much many seconds do we wait before powering on
    wait = 4

    def upload_set(self, images, wait = None, retries = None):
        """\
        Upload and flash a set of images to the target

        How this is done is HW specific on the target; however, upon
        return, the image is loaded in the target's memory, or flashed
        into some flash ROM or into a hardrive.

        :param images: list of images to upload; each item is a
          string in the format TYPE:PATHTOIMAGE, where TYPE is the
          kind of image to flash (target specific, but such "room",
          "fw", "kernel", etc...)
        :param int wait: see :attr:`wait`
        :param int retries: see :attr:`retries`
        """
        if wait == None:
            wait = self.wait
        if retries == None:
            retries = self.retries

        target = self.target
        testcase = target.testcase

        images_str = " ".join([ i[0] + ":" + i[1] for i in images ])
        retval = None
        tries = 0

        target.report_info("deploying", dlevel = 1)
        for tries in range(retries):
            remote_images = ttb_client.rest_tb_target_images_upload(
                target.rtb, images)
            with msgid_c("#%d" % (tries + 1)):
                try:
                    target.report_info("deploying (try %d/%d) %s"
                                       % (tries + 1, retries, images_str),
                                       dlevel = 1)
                    target.rtb.rest_tb_target_images_set(
                        target.rt, remote_images, ticket = testcase.ticket)
                    retval = tc.result_c(1, 0, 0, 0, 0)
                    target.report_pass("deployed (try %d/%d) %s"
                                       % (tries + 1, retries, images_str))
                    break
                except requests.exceptions.HTTPError as e:
                    if wait > 0:
                        if getattr(target, "power", None):
                            target.report_blck(
                                "deploying (try %d/%d) failed; "
                                "recovery: power cycling [with %ds break]"
                                % (tries + 1, retries, wait),
                                { "deploy failure error": e.message })
                            target.power.cycle(wait = wait)
                        else:
                            target.report_blck(
                                "deploying (try %d/%d) failed; "
                                "recovery: waiting %ds break"
                                % (tries + 1, retries, wait),
                                { "deploy failure error": e.message })
                            time.sleep(wait)
                        wait += wait
                        target.report_info(
                            "deploy failure (try %d/%d) "
                            "recovery: power cycled" % (tries + 1, retries))
                    else:
                        target.report_blck(
                            "deploying (try %d/%d) failed; retrying"
                            % (tries + 1, retries),
                            { "deploy failure error": e.message })
                    retval = tc.result_c(0, 0, 0, 1, 0)

        target.report_tweet("deploy (%d tries)" % (tries + 1), retval)
        return retval.summary()

    def get_types(self):
        # FIXME: return supported image types
        raise NotImplementedError
