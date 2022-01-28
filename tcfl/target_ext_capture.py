#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Capture snapshots or streams of target data, such as screenshots, audio, video, network, etc
--------------------------------------------------------------------------------------------

The capture interface allows to capture screenshots, audio and video
streams, network traffic, etc.

This provides an abstract interface to access it as well as means to
wait for things to be found when such captures, such as images on screenshots.

"""
# Roadmap:
#
# Extension to the TCF client API
#
#   extension
#     list()
#     start()
#     stop()
#     stop_and_get()
#     get()
#     image_on_screenshot()
#       _expect_image_on_screenshot_c
#         detect()
#           _squares_overlap()
#             _template_find()
#               _template_find_gray()
#         flush()
#           _draw_text()
#
# Command line invocation hookups
#
#   cmdline_*()

import collections
import contextlib
import inspect
import logging
import os
import shutil
import time

import commonl
from . import tc
from . import msgid_c


try:
    import cv2
    import numpy
    import imutils
    image_expectation_works = True
except ImportError as e:
    image_expectation_works = False




#
# implementation of the expectation to wait for an image template to
# show up in an screenshot
#

def _template_find_gray(image_gray, template, threshold = 0.8):
    # Find a gray template on a gray image, returning a list of boxes
    # that match the template in the image
    #
    # coordinates are 0,0 on top-left corner of the image
    #
    assert threshold > 0 and threshold <= 1
    width, height = template.shape[::-1]
    image_width, image_height = image_gray.shape[::-1]
    result = cv2.matchTemplate(image_gray, template, cv2.TM_CCOEFF_NORMED)
    locations = numpy.where(result >= threshold)
    r = []
    for point in zip(*locations[::-1]):
        r.append((
            float(point[0]) / image_width,
            float(point[1]) / image_height,
            float(point[0] + width) / image_width,
            float(point[1] + height) / image_height,
        ))
    return r

def _template_find(image_filename, image_rgb,
                   template_filename, template,
                   min_width = 30, min_height = 30):
    # Finds a template in an image, possibly scaling the template and
    # returning the locations where found in a resolution indendent
    # way
    image_gray = cv2.cvtColor(image_rgb, cv2.COLOR_BGR2GRAY)
    image_width, image_height = image_gray.shape[::-1]
    template = cv2.imread(template_filename, 0)
    template_width, template_height = template.shape[::-1]

    #for scale in numpy.linspace(0.2, 1.0, 20)[::-1]:
    squares = {}

    # Scale down the image to find smaller hits of the icon
    for scale in numpy.linspace(0.2, 1.0, 20)[::-1]:

        image_gray_resized = imutils.resize(
            image_gray, width = int(image_gray.shape[1] * scale))

        w, h = image_gray_resized.shape[::-1]

        # stop if the image is smaller than the template
        if w < template_width or h < template_height:
            logging.warning("%s: stopping at scale %.2f: smaller than "
                            "template", image_filename, scale)
            break
        if w < min_width or h < min_height:
            logging.warning("%s: stopping at scale %.2f: smaller than "
                            "args limit", image_filename, scale)
            break

        r = _template_find_gray(image_gray_resized, template)
        for square in r:
            square_original = (
                int(square[0] * image_width),
                int(square[1] * image_height),
                int(square[2] * image_width),
                int(square[3] * image_height),
            )
            squares[scale] = dict(relative = square,
                                  absolute = square_original)

    # scale down the template to find smaller hits of the template
    for scale in numpy.linspace(0.2, 1.0, 20)[::-1]:

        template_resized = imutils.resize(
            template, width = int(template.shape[1] * scale))

        w, h = template_resized.shape[::-1]
        #print "DEBUG scaling template to %d %d" % (w, h)
        # stop if the template size gets too small
        if w < min_width or h < min_height:
            logging.warning("%s: stopping at scale %.2f: smaller than "
                            "args limit", template_filename, scale)
            break

        r = _template_find_gray(image_gray, template_resized)
        for square in r:
            square_original = (
                int(square[0] * image_width),
                int(square[1] * image_height),
                int(square[2] * image_width),
                int(square[3] * image_height),
            )
            squares[1/scale] = dict(relative = square,
                                    absolute = square_original)

    return squares

class _expect_image_on_screenshot_c(tc.expectation_c):
    # note the parameters are fully documented in
    # :meth:`extension.image_on_screenshot`
    def __init__(self, target, template_image_filename, capturer,
                 in_area, merge_similar, min_width, min_height,
                 poll_period, timeout, raise_on_timeout, raise_on_found,
                 name = None):
        if not image_expectation_works:
            raise RuntimeError("Image matching won't work; need packages"
                               " cv2, imutils, numpy")
        assert isinstance(target, tc.target_c)
        assert isinstance(capturer, str)
        assert in_area == None \
            or isinstance(in_area, collections.Iterable) \
            and len(in_area) == 4 \
            and all(i >= 0 and i <= 1 for i in in_area), \
            'in_area parameter must be a tuple of four numbers ' \
            'from 0 to 1 describing the upper-left and lower-right ' \
            'of the area where to look for the image, ' \
            'eg: (0, 0, 0.5, 0.5) means in the top left quarter'
        assert merge_similar >= 0.0 and merge_similar <= 1.0, \
            "merge_similar has to be a float from 0.0 to 1.0"
        assert name == None or isinstance(name, str)
        tc.expectation_c.__init__(self, target, poll_period, timeout,
                                  raise_on_timeout = raise_on_timeout,
                                  raise_on_found = raise_on_found)
        self.capturer = capturer
        self.in_area = in_area
        self.merge_similar = merge_similar
        # if the image is relative, we make it relative to the
        # filename of the caller--so we can do short names
        if name:
            self.name = name
        else:
            self.name = commonl.name_make_safe(template_image_filename)
        if os.path.isabs(template_image_filename):
            self.template_image_filename = template_image_filename
        else:
            self.template_image_filename = os.path.join(
                # 2 up the stack is the guy who called
                # target.capture.image_on_screeshot()
                os.path.dirname(inspect.stack()[2][1]),
                template_image_filename)
        with open(self.template_image_filename) as _f:
            # try to open it, cv2.imread() is quite crappy at giving
            # errors on file not found
            pass
        self.template_img = cv2.imread(self.template_image_filename,
                                       cv2.IMREAD_GRAYSCALE)
        # FIXME: raise exception if too small
        self.min_width = min_width
        self.min_height = min_height

    def poll_context(self):
        # we are polling from target with role TARGET.WANT_NAME from
        # it's capturer CAPTURER, so this is our context, so anyone
        # who will capture from that reuses the capture.
        return '%s-%s' % (self.target.want_name, self.capturer)

    def poll(self, testcase, run_name, buffers_poll):
        target = self.target
        # we name the screenshots after the poll_name name, as
        # we'll share them amongs multiple expectations
        buffers_poll.setdefault('screenshot_count', 0)
        buffers_poll.setdefault('screenshots', [])
        dirname = os.path.join(testcase.tmpdir,
                               'expect-buffer-poll-%s' % self.poll_name)
        commonl.makedirs_p(dirname)
        filename = os.path.join(
            dirname,
            '.'.join([
                'screenshot',
                run_name, self.poll_name,
                # FIXME: replace number with datestamp? ideally from server?
                '%02d' % buffers_poll['screenshot_count'],
                'png'
            ])
        )
        target.capture.get(self.capturer, filename)
        buffers_poll['screenshot_count'] += 1
        buffers_poll['screenshots'].append(filename)
        target.report_info('captured screenshot from %s to %s'
                           % (self.capturer, filename), dlevel = 2)


    @staticmethod
    def _squares_overlap(ra, rb):
        #
        # Given two intersecting squares, return a measure of how much
        # of their areas intersect against the total square needed to
        # contain both of them (0 meaning they do not overlap at all,
        # 1 meaning they cover eactlt the same surface)
        #
        # Return the percentage, the overlapping square and the
        # intersecting square.
        #
        overlap_h0 = min(ra[0], rb[0])
        overlap_v0 = min(ra[1], rb[1])
        overlap_h1 = max(ra[2], rb[2])
        overlap_v1 = max(ra[3], rb[3])
        overlap_area = ( overlap_h1 - overlap_h0 ) \
            * ( overlap_v1 - overlap_v0 )

        intersect_h0 = max(ra[0], rb[0])
        intersect_v0 = max(ra[1], rb[1])
        intersect_h1 = min(ra[2], rb[2])
        intersect_v1 = min(ra[3], rb[3])
        intersect_area = ( intersect_h1 - intersect_h0 ) \
            * ( intersect_v1 - intersect_v0 )

        if overlap_area == 0:
            return 0, ( -1, -1, -1, -1 ), ( -1, -1, -1, -1 )
        return 1 - ( overlap_area - intersect_area ) / overlap_area, \
            (overlap_h0, overlap_v0, overlap_h1, overlap_v1), \
            (intersect_h0, intersect_v0, intersect_h1, intersect_v1)


    def _draw_text(self, img, text, x, y):
        img_w, img_h, _ = img.shape[::-1]
        # FIXME: make it a translucent box with an arrow at some point...
        font = cv2.FONT_HERSHEY_SIMPLEX
        # FIXME: compute scale to match image size
        font_scale = 0.5
        font_linetype = 1
        text = self.name
        text_w, text_h = cv2.getTextSize(
            text, font, font_scale, font_linetype)[0]
        text_w *= 1.02	# make space around
        text_h *= 1.02
        y += int(text_h)	# make it relative to the top of the text
        #somel.cv2.rectangle(
        #    img,
        #    x, y,
        #    x + text_width, y + text_height,
        #    box_coords[0], box_coords[1], rectangle_bgr,
        #    somel.cv2.FILLED)
        if x + text_w >= img_w:
            x = max(0, x - int(text_w))
        if y + text_h >= img_h:
            y = max(0, y - int(text_h))
        cv2.putText(img, text, (x, y),
                    fontFace = font, fontScale = font_scale,
                    color = (0, 0, 255), thickness = font_linetype)

    def detect(self, testcase, run_name, buffers_poll, buffers):
        """
        See :meth:`expectation_c.detect` for reference on the arguments

        :returns: dictionary of squares detected at different scales in
          relative and absolute coordinates, e.g:

          >>> {
          >>>     1.0 : {
          >>>         # relative|absolute: (X0, Y0) to (X1, Y1)
          >>>         'relative': ( 0.949, 0.005, 0.968, 0.0312 ),
          >>>         'absolute': ( 972, 4, 992, 24)
          >>>     },
          >>>     0.957 : {
          >>>         'relative': ( 0.948, 0.004, 0.969, 0.031 ),
          >>>         'absolute': ( 971, 3, 992, 24)
          >>>     },
          >>>     0.957 : {
          >>>         'relative': (0.948, 0.005, 0.969, 0.032 ),
          >>>         'absolute': (971, 4, 992, 25)
          >>>     },
          >>>     0.915 : {
          >>>         'relative': ( 0.948, 0.004, 0.970, 0.032 ),
          >>>         'absolute': (971, 3, 993, 25)
          >>>     }
          >>> }

        """
        target = self.target
        if not buffers_poll.get('screenshot_count', 0):
            target.report_info('%s/%s: not detecting, no screenshots yet'
                               % (run_name, self.name), dlevel = 3)
            return None
        most_recent = buffers_poll['screenshots'][-1]
        target.report_info('%s/%s: detecting in %s'
                           % (run_name, self.name, most_recent),
                           dlevel = 2)
        buffers['current'] = most_recent
        screenshot_img = cv2.imread(most_recent)
        r = _template_find(
            most_recent, screenshot_img,
            self.template_image_filename, self.template_img,
            min_width = self.min_width, min_height = self.min_height)
        if self.in_area:
            r_in_area = {}
            ax0 = self.in_area[0]
            ay0 = self.in_area[1]
            ax1 = self.in_area[2]
            ay1 = self.in_area[3]
            for scale, data in r.items():
                area_rel = data['relative']
                area_abs = data['absolute']
                x0 = area_rel[0]
                y0 = area_rel[1]
                x1 = area_rel[2]
                y1 = area_rel[3]
                if x0 >= ax0 and y0 >= ay0 \
                   and x1 <= ax1 and y1 <= ax1:
                    r_in_area[scale] = dict(relative = area_rel,
                                            absolute = area_abs)
                    target.report_info(
                        "%s/%s: taking match %.1fs@%.2f,%.2f-%.2f,%.2f "
                        "(in area %.2f,%.2f-%.2f,%.2f)"
                        % (run_name, self.name, scale, x0, y0, x1, y1,
                           ax0, ay0, ax1, ay1), dlevel = 3)
                else:
                    target.report_info(
                        "%s/%s: ignoring match %.1fs@%.2f,%.2f-%.2f,%.2f "
                        "(out of area %.2f,%.2f-%.2f,%.2f)"
                        % (run_name, self.name, scale, x0, y0, x1, y1,
                           ax0, ay0, ax1, ay1), dlevel = 3)
            target.report_info(
                "%s/%s: kept %d matches, ignored %d out-of-area"
                % (run_name, self.name,
                   len(r_in_area), len(r) - len(r_in_area)), dlevel = 2)
            r = r_in_area
        if r and self.merge_similar:	# merge similar detections
            start_idx = 0
            while start_idx < len(r):
                squarel = list(r.keys())
                r0 = r[squarel[0]]['relative']
                for r_name in squarel[start_idx+1:]:
                    rx = r[r_name]['relative']
                    measure, _, _ = self._squares_overlap(r0, rx)
                    if measure >= self.merge_similar:
                        # if more than the threshold we consider it is
                        # the same and ignore it
                        del r[r_name]
                start_idx += 1
        if r:
            # make sure there is a collateral image in the
            # buffers_poll (shared amongs all the expercations for
            # this target and capturer) and draw detected regions in
            # there -- when done, flush() will write it.
            if 'collateral' in buffers_poll:
                collateral_img = buffers_poll['collateral']
            else:
                collateral_img = cv2.imread(most_recent)
                buffers_poll['collateral'] = collateral_img
            # draw boxes for the squares detected
            for data in r.values():
                rect = data['absolute']
                cv2.rectangle(
                    collateral_img,
                    # note rect are the absolute coordinates
                    (rect[0], rect[1]), (rect[2], rect[3]),
                    (0, 0, 255),	# red
                    1) # thin line
                self._draw_text(collateral_img, self.name, rect[0], rect[3])
            if len(r) == 1:
                target.report_info(
                    '%s/%s: detected one match'
                    % (run_name, self.name),
                    dict(screenshot = most_recent), alevel = 2)
            else:
                target.report_info(
                    '%s/%s: detected %d matches'
                    % (run_name, self.name, len(r)),
                    dict(screenshot = most_recent), alevel = 2)
            return r

    def flush(self, testcase, run_name, buffers_poll, buffers, results):
        if 'collateral' in buffers_poll:
            # write the collateral images, which basically have
            # squares drawn on the icons we were asked to look for--we
            # marked the squares in detect()--we wrote one square per
            # expectation per polled image
            collateral_img = buffers_poll['collateral']
            # so we can draw all the detections on the same screenshot
            collateral_filename = \
                testcase.report_file_prefix \
                + "%s.detected.png" % run_name
            cv2.imwrite(collateral_filename, collateral_img)
            del buffers_poll['collateral']
            del collateral_img

        if not results:
            # if we have no results about this expectation, it
            # means we missed it, so record a miss for reference

            # First generate collateral for the screenshot, if still
            # not recorded
            collateral_missed_filename = buffers_poll.get('collateral_missed',
                                                          None)
            if not collateral_missed_filename:
                collateral_missed_filename = \
                    testcase.report_file_prefix \
                    + "%s.missed.%s.png" % (run_name, self.poll_context())
                screenshots = buffers_poll.get('screenshots', [ ])
                if not screenshots:
                    self.target.report_info(
                        "%s/%s: no screenshot collateral, "
                        "since no captures where done"
                        % (run_name, self.name))
                    return
                last_screenshot = screenshots[-1]
                commonl.rm_f(collateral_missed_filename)
                shutil.copy(last_screenshot, collateral_missed_filename)
                buffers_poll['collateral_missed'] = collateral_missed_filename

            # lastly, symlink the specific missed expectation to the
            # screenshot--remember we might be sharing the screenshot
            # for many expectations
            collateral_filename = \
                testcase.report_file_prefix \
                + "%s.missed.%s.%s.png" % (
                    run_name, self.poll_context(), self.name)
            # make sure we symlink in the same directory
            commonl.rm_f(collateral_filename)
            os.symlink(os.path.basename(collateral_missed_filename),
                       collateral_filename)


class extension(tc.target_extension_c):
    """
    When a target supports the *capture* interface, it's
    *tcfl.tc.target_c* object will expose *target.capture* where the
    following calls can be made to capture data from it.

    A streaming capturer will start capturing when :meth:`start` is
    called and stop when :meth:`stop_and_get` is called, bringing the
    capture file from the server to the machine executing *tcf run*.

    A non streaming capturer just takes a snapshot when :meth:`get`
    is called.

    You can find available capturers with :meth:`list` or::

      $ tcf capture-ls TARGETNAME
      vnc0:ready
      screen:ready
      video1:not-capturing
      video0:ready

    a *ready* capturer is capable of taking screenshots only

    or::

      $ tcf list TARGETNAME | grep capture:
        capture: vnc0 screen video1 video0

    """

    def __init__(self, target):
        tc.target_extension_c.__init__(self, target)
        if not 'capture' in target.rt.get('interfaces', []):
            raise self.unneeded

    def _capturers_data_get(self, capturer = None):
        if capturer == None:
            capturers = self.target.properties_get("interfaces.capture.*")
            return capturers.get('interfaces', {}).get('capture', {})
        capturers = self.target.properties_get(f"interfaces.capture.{capturer}.*")
        return capturers.get('interfaces', {}).get('capture', {}).get(capturer, {})

    def start(self, capturer):
        """
        Take a snapshot or start capturing

        >>> target.capture.start("screen_stream")

        :param str capturer: capturer to use, as listed in the
          target's *capture*
        :returns: dictionary of values passed by the server
        """
        self.target.report_info("%s: starting capture" % capturer, dlevel = 3)
        r = self.target.ttbd_iface_call("capture", "start", method = "PUT",
                                        capturer = capturer)
        self.target.report_info("%s: started capture: %s" % (capturer, r),
                                dlevel = 2)
        return r


    def stop(self, capturer):
        self.target.report_info("%s: stopping capture" % capturer, dlevel = 3)
        r = self.target.ttbd_iface_call("capture", "stop", method = "PUT",
                                        capturer = capturer)
        self.target.report_info("%s: stopped capture: %s" % (capturer, r),
                                dlevel = 2)
        return r


    def get(self, capturer, stream = None, file_name = None, offset = None,
            prefix = None, follow = False,
            **streams):
        assert isinstance(capturer, str)
        assert stream == None or isinstance(stream, str)
        assert prefix == None or isinstance(prefix, str)
        assert file_name == None or isinstance(file_name, str)
        assert offset == None or isinstance(offset, int)
        assert isinstance(follow, bool)

        if prefix == None:
            prefix = self.target.testcase.report_file_prefix
        if stream:
            streams[stream] = { 'file_name': file_name, 'offset': offset }
        capturers_data = self._capturers_data_get()
        capturer_data = capturers_data.get(capturer, {})
        if capturer_data == {}:
            raise tc.blocked_e(f"capturer '{capturer}': unknown"
                               f" (available: {' '.join(capturers_data.keys())})")
        streams_data = capturer_data.get('stream', {})

        # verify the streams are valid
        for stream_name in streams:
            if stream_name not in streams_data:
                raise tc.blocked_e(
                    f"capturer '{capturer}': unknown stream '{stream_name}'"
                    f" (available: {' '.join(streams_data.keys())}")
        r = {}
        for stream_name, stream_data in streams_data.items():
            if streams and stream_name not in streams:
                continue
            src_file_name = stream_data.get('file', None)
            if src_file_name == None:
                continue
            dst_file_name = streams.get(stream_name, {}).get('file_name', None)
            offset = streams.get('offset', None)
            if dst_file_name == None:
                _root, extension = os.path.splitext(src_file_name)
                dst_file_name = prefix + f"{capturer}.{stream_name}{extension}"

            try:
                if follow:
                    try:
                        offset = os.stat(dst_file_name).st_size
                    except FileNotFoundError:
                        offset = None	# still not existing, so start from scratch
                self.target.store.dnload("capture/" + src_file_name, dst_file_name,
                                         offset = offset, append = follow)
                r[stream_name] = dst_file_name
            except tc.exception as e:
                tc.result_c.report_from_exception(self.target.testcase, e)
        return r


    def list(self):
        """
        List capturers available for this target.

        >>> r = target.capture.list()
        >>> print r
        >>> { 'screen': None, 'audio': False, 'screen_stream': True }

        :returns: dictionary of capturers and their state:

          - *None*: snapshot capturer, no state
          - *True*: streaming capturer, currently capturing
          - *False*: streaming capturer, currently not-capturing
        """
        # pure target get w/o going through the cache

        r = {}
        capturers_data = self._capturers_data_get()
        for capturer_name, data in capturers_data.items():
            snapshot = data.get('snapshot', False)
            if snapshot == True:
                r[capturer_name] = None
            else:
                r[capturer_name] = data.get('capturing', False)
        return r


    def _healthcheck(self):
        # not much we can do here without knowing what the interfaces
        # can do, we can start and stop them, they might fail to start
        # since they might need the target to be powered on
        target = self.target

        capture_spec = {}
        for name, data in target.rt['interfaces'].get('capture', {}).items():
            capture_spec[name] = data.get('snapshot', True)
        capturers = target.capture.list()		# gather states

        target.report_info("capturers: listed %s" \
            % " ".join("%s:%s" % (k, v) for k, v in capturers.items()))
        try:
            if hasattr(target, "power"):		# ensure is on
                target.power.on()			# some might need it
        except RuntimeError as e:
            target.report_fail(
                "can't power on target; some capture healthcheck will fail",
                dict(exception = e))

        def _start_and_check(capturer):
            try:
                target.capture.start(capturer)
                target.report_pass("capturer %s: starts" % capturer)
            except RuntimeError as e:
                target.report_fail("capturer %s: can't start" % capturer,
                                   dict(exception = e), subcase = "start")

            # If the capturer is not a snapshot capturer check streaming state
            if capture_spec[capturer] == False:
                states = target.capture.list()
                state = states[capturer]
                if state == True:
                    target.report_pass(
                        "capturer %s is in expected streaming state" % capturer)
                else:
                    target.report_fail(
                        "capturer %s is not in expected streaming mode, but %s"
                        % (capturer, state))

        testcase = target.testcase
        for capturer, state in capturers.items():

            with testcase.subcase(capturer):
                _start_and_check(capturer)
                time.sleep(10)		# give it some time to record sth
                try:
                    r = target.capture.get(capturer)
                    for item in r.items():
                        target.report_pass(
                            "capturer %s: gets %s \"%s\""
                             % (capturer, item[0], item[1]))
                except RuntimeError as e:
                    target.report_fail(
                        "capturer %s: can't get" % capturer,
                        dict(exception = e), subcase = "get")

                _start_and_check(capturer)
                try:
                    target.capture.stop(capturer)
                    target.report_pass("capturer %s: stops" % capturer)
                except RuntimeError as e:
                    target.report_fail("capturer %s: can't stop" % capturer,
                                       dict(exception = e), subcase = "stop")


    def image_on_screenshot(
            self, template_image_filename, capturer = 'screen',
            in_area = None, merge_similar = 0.7,
            min_width = 30, min_height = 30,
            poll_period = 3, timeout = 130,
            raise_on_timeout = tc.error_e, raise_on_found = None,
            name = None):
        """
        Returns an object that finds an image/template in an
        screenshot from the target.

        This object is then given to :meth:`tcfl.tc.tc_c.expect` to
        poll for screenshot until the image is detected:

        >>> class _test(tcfl.tc.tc_c):
        >>> ...
        >>>     def eval(self, target):
        >>>         ...
        >>>         r = self.expect(
        >>>             target.capture.image_on_screenshot('icon1.png'),
        >>>             target.capture.image_on_screenshot('icon2.png'))

        upon return, *r* is a dictionary with the detection
        information for each icon:

        >>> {
        >>>     "icon1.png": [
        >>>         (
        >>>             1.0,
        >>>             ( 0.949, 0.005, 0.968, 0.0312 ),
        >>>             # relative (X0, Y0) to (X1, Y1)
        >>>             ( 972, 4, 992, 24)
        >>>             # absolute (X0, Y0) to (X1, Y1)
        >>>         ),
        >>>         (
        >>>             0.957,
        >>>             ( 0.948, 0.004, 0.969, 0.031 ),
        >>>             ( 971, 3, 992, 24)
        >>>         ),
        >>>     ],
        >>>     "icon2.png": [
        >>>         (
        >>>             0.915,
        >>>             (0.948, 0.004, 0.970, 0.032 ),
        >>>             (971, 3, 993, 25)
        >>>         )
        >>>     ]
        >>> }

        This detector's return values for reach icon are a list of
        squares where the template was found. On each entry we get a
        list of:

        - the scale of the template
        - a square in resolution-independent coordinates; (0,0) being
          the top left corner, (1, 1) bottom right corner)
        - a square in the screen's capture resolution; (0,0) being the
          top left corner.

        the detector will also produce collateral in the form of
        screenshots with annotations where the icons were found, named
        as *report-[RUNID]:HASHID.NN[.LABEL].detected.png*, where *NN*
        is a monotonically increasing number, read more for
        :ref:`RUNID <tcf_run_runid>`, and ref:`HASHID <tc_id>`).

        :param str template_image_filename: name of the file that
          contains the image that we will look for in the
          screenshot. This can be in jpeg, png, gif and other
          formats.

          If the filename is relative, it is considered to
          be relative to the file the contains the source file that
          calls this function.

        :param str capturer: (optional, default *screen*) where to capture
          the screenshot from; this has to be a capture output that supports
          screenshots in a graphical formatr (PNG, JPEG, etc), eg::

            $ tcf capture-ls nuc-01A
            ...
            hdmi0_screenshot:snapshot:image/png:ready
            screen:snapshot:image/png:ready
            ...

          any of these two could be used; *screen* is taken as a default
          that any target with graphic capture capabilities will provide
          as a convention.

        :param in_area: (optional) bounding box defining a square where
         the image/template has to be found for it to be considered; it is
         a very basic mask.

         The format is *(X0, Y0, X1, Y1)*, where all numbers are floats
         from 0 to 1. *(0, 0)* is the top left corner, *(1, 1)* the bottom
         right corner. Eg:

         - *(0, 0,  0.5, 0.5)* the top left 1/4th of the screen

         - *(0, 0.5, 1, 1)* the bottom half of the screen

         - *(0.5, 0, 1, 1)* the right half of the screen

         - *(0.95, 0, 1, 0.05)* a square with 5% side on the top right
            corner of the screen

        :param float merge_similar: (default 0.7) value from 0 to 1
          that indicates how much we consider two detections similar
          and we merge them into a single one.

          0 means two detections don't overlap at all, 1 means two
          detections have to be exatly the same. 0.85 would mean that
          the two detections overlap on 85% of the surface.

        :param int min_width: (optional, default 30) minimum width of
          the template when scaling.

        :param int min_height: (optional, default 30) minimum height of
          the template when scaling.

        :param str name: (optional) name of this expectation; defaults
          to a sanitized form of the filename

        The rest of the arguments are described in
        :class:`tcfl.tc.expectation_c`.
        """
        if not image_expectation_works:
            raise RuntimeError("Image matching won't work; need packages"
                               " cv2, imutils, numpy")
        return _expect_image_on_screenshot_c(
            self.target,
            template_image_filename, capturer,
            in_area, merge_similar, min_width, min_height,
            poll_period, timeout, raise_on_timeout, raise_on_found,
            name = name)


def _cmdline_capture(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "capture")
        capturer = args.capturer
        capturers = target.capture.list()
        if capturer not in capturers:
            raise RuntimeError(f"{capturer}: unknown capturer: {capturers}")
        streaming = capturers[capturer]
        if args.prefix:
            prefix = args.prefix
        else:
            prefix = target.id + "."
        if streaming == None:
            # snapshot
            print(f"{capturer}: taking snapshot")
            target.capture.start(capturer)
            print(f"{capturer}: downloading capture")
            r = target.capture.get(capturer, prefix = prefix)
        elif streaming == False:
            # not snapshot, start, wait, stop, get
            print(f"{capturer}: non-snapshot capturer was stopped, starting")
            target.capture.start(args.capturer)
            print(f"{capturer}: capturing for {args.wait} seconds")
            time.sleep(args.wait)
            print(f"{capturer}: stopping capture")
            target.capture.stop(args.capturer)
            print(f"{capturer}: downloading capture")
            r = target.capture.get(capturer, prefix = prefix)
        for stream_name, file_name in r.items():
            print(f"{capturer}: downloaded stream {stream_name} -> {file_name}")


def _cmdline_capture_start(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "capture")
        r = target.capture.start(args.capturer)
        for stream_name, file_name in r.items():
            print(f"{stream_name}: {file_name}")

def _cmdline_capture_get(args):
    # FIXME: add --continue to use offset to get from the same files
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "capture")
        if args.prefix:
            prefix = args.prefix
        else:
            prefix = target.id + "."
        while True:
            r = target.capture.get(args.capturer, prefix = prefix,
                                   follow = args.follow)
            for stream_name, file_name in r.items():
                print(f"{stream_name}: {file_name}")
            if not args.follow:
                break
            time.sleep(args.wait)

def _cmdline_capture_stop(args):
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "capture")
        r = target.capture.stop(args.capturer)
        for stream_name, file_name in r.items():
            print(f"{stream_name}: {file_name}")

def _cmdline_capture_list(args):
    state_to_str = {
        False: "not capturing",
        True: "capturing",
        None: "ready"
    }
    with msgid_c("cmdline"):
        target = tc.target_c.create_from_cmdline_args(args, iface = "capture")
        capturers_data = target.capture._capturers_data_get()
        capturers = target.capture.list()
        for name, state in capturers.items():
            streams = capturers_data[name].get('stream', {})
            l = [
                name + ":" + data.get('mimetype', "mimetype-n/a")
                for name, data in streams.items()
            ]
            print(f"{name} ({state_to_str[state]}): {' '.join(l)}")


def cmdline_setup(argsp):
    ap = argsp.add_parser("capture", help = "Generic capture; takes a"
                          " snapshot or captures for given SECONDS"
                          " and downloads captured data")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer")
    ap.add_argument("--prefix", action = "store", type = str, default = None,
                    help = "Prefix for downloaded files")
    ap.add_argument("--wait", action = "store", metavar = 'SECONDS', type = float, default = 5,
                    help = "How long to wait between starting and stopping")
    ap.add_argument("--stream", action = "append", metavar = 'STREAM-NAME',
                    type = str, default = [], nargs = "*",
                    help = "Specify stream(s) to download (default all)")
    ap.set_defaults(func = _cmdline_capture)

    ap = argsp.add_parser("capture-start", help = "start capturing")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should start")
    ap.set_defaults(func = _cmdline_capture_start)

    ap = argsp.add_parser("capture-get",
                          help = "stop capturing and get the result to a file")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should stop")
    ap.add_argument("--prefix", action = "store", type = str, default = None,
                    help = "Prefix for downloaded files")
    ap.add_argument("--wait", action = "store", metavar = 'SECONDS',
                    type = float, default = 2,
                    help = "When --follow, time to wait between downloads"
                    " [%(default).1f seconds]")
    ap.add_argument("--follow",
                    action = "store_true", default = False,
                    help = "Read any changes from the last download")
    ap.set_defaults(func = _cmdline_capture_get)

    ap = argsp.add_parser("capture-stop", help = "stop capturing, discarding "
                          "the capture")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.add_argument("capturer", metavar = "CAPTURER-NAME", action = "store",
                    type = str, help = "Name of capturer that should stop")
    ap.set_defaults(func = _cmdline_capture_stop)

    ap = argsp.add_parser("capture-ls", help = "List available capturers")
    ap.add_argument("target", metavar = "TARGET", action = "store", type = str,
                    default = None, help = "Target's name or URL")
    ap.set_defaults(func = _cmdline_capture_list)
