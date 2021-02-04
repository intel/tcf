#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
""".. _conf_00_lib_capture:

Configuration API for capturing audio and video
-----------------------------------------------

These capture objects are meant to be fed to the capture interface
declaration of a target in the server, for example, in any server
configuration file you could have added a target and then a capture
interface can be added with:

.. code-block:: python

   ttbl.test_target.get('TARGETNAME').interface_add(
       "capture",
       ttbl.capture.interface(
           screen = "hdmi0_screenshot",
           screen_stream = "hdmi0_vstream",
           audio_stream = "front_astream",
           front_astream = capture_front_astream_vtop_0c76_161e,
           hdmi0_screenshot = capture_screenshot_ffmpeg_v4l,
           hdmi0_vstream = capture_vstream_ffmpeg_v4l,
           hdmi0_astream = capture_astream_ffmpeg_v4l,
       )
   )

This assumes we have connected and configured:

- an HDMI grabber to the target's HDMI0 output (see :data:`setup
  instructions <capture_screenshot_ffmpeg_v4l>`)

- an audio grabber to the front audio output (see :data:`setup
  instructions <capture_front_astream_vtop_0c76_161e>`).

to create multiple capture capabilityies (video and sound streams, and
screenshots) with specific names for the ouputs and aliases)

Note the audio capturers are many times HW specific because they
expose different audio controls that have to be set or queried.

"""

import ttbl.capture


#: A capturer to take screenshots from a v4l device using ffmpeg
#:
#: Note the fields are target's tags and others specified in
#: :class:`ttbl.capture.generic_snapshot` and
#: :class:`ttbl.capture.generic_stream`.
#:
#: To use:
#:
#:  - define a target
#:
#:  - physically connect the capture interface to it and to the
#:    server
#:
#:  - Create a *udev* configuration so the capture device exposes
#:    itself as */dev/video-TARGETNAME-INDEX*.
#:
#:    This requires creating a *udev* configuration so that the v4l
#:    device gets recognized and an alias created, which can be
#:    accomplished by dropping a udev rule in */etc/udev/rules.d* such
#:    as::
#:
#:      SUBSYSTEM == "video4linux", ACTION == "add", \
#:          KERNEL=="video*", \
#:          ENV{ID_SERIAL_SHORT} == "SOMESERIALNUMBER", \
#:          SYMLINK += "video-nuc-01A-$attr{index}"
#:
#:    note some USB devices don't offer a serial number, then you
#:    can use a device path, such as::
#:
#:      ENV{ID_PATH} == "pci-0000:00:14.0-usb-0:2.1:1.0", \
#:
#:    this is shall be a last resort, as then moving cables to
#:    different USB ports will change the paths and you will have to
#:    reconfigure.
#:
#:    See :ref:`methods to find device information <find_usb_info>`
#:
#:  - add the configuration snippet::
#:
#:      ttbl.test_target.get(TARGETNAME).interface_add(
#:          "capture",
#:          ttbl.capture.interface(
#:              screen = "hdmi0_screenshot",
#:              screen_stream = "hdmi0_vstream",
#:              hdmi0_screenshot = capture_screenshot_ffmpeg_v4l,
#:              hdmi0_vstream = capture_vstream_ffmpeg_v4l,
#:          ))
#:
#:    Note in this case we have used an
#:
#: This has tested with with:
#:
#: - https://www.agptek.com/AGPTEK-USB-3-0-HDMI-HD-Video-Capture-1089-212-1.html
#:
#:   Which shows in USB as::
#:
#:     3-2.2.4       1bcf:2c99 ef  3.10 5000MBit/s 512mA 4IFs (VXIS Inc ezcap U3 capture)
#:       3-2.2.4:1.2   (IF) 01:01:00 0EPs (Audio:Control Device) snd-usb-audio sound/card5
#:       3-2.2.4:1.0   (IF) 0e:01:00 1EP  (Video:Video Control) uvcvideo video4linux/video5 video4linux/video4 input/input15
#:       3-2.2.4:1.3   (IF) 01:02:00 0EPs (Audio:Streaming) snd-usb-audio
#:       3-2.2.4:1.1   (IF) 0e:02:00 1EP  (Video:Video Streaming) uvcvideo
#:
#:   Note this also can be used to capture video  of the HDMI stream
#:   using capture_vstream_ffmpeg_v4l and audio played over HDMI via
#:   an exposed ALSA interface (see capture_astream_ffmpeg_v4l below).
capture_screenshot_ffmpeg_v4l = ttbl.capture.generic_snapshot(
    "screenshot:/dev/video-%(id)s-0",
    "ffmpeg -i /dev/video-%(id)s-0"
    # -ss .50 to let the capturer warm up; 0 will come a
    # black frame always
    " -ss 0.5 -frames 1 -c:v png -f image2pipe "
    "-y %(output_file_name)s",
    mimetype = "image/png"
)


#: A capturer to take screenshots from VNC
#:
#: Note the fields are target's tags and others specified in
#: :class:`ttbl.capture.generic_snapshot` and
#: :class:`ttbl.capture.generic_stream`.
#:
#: Deprecated in favour of :func:`mc_capture_screenshot_vnc`
capture_screenshot_vnc = ttbl.capture.generic_snapshot(
    # dont set the port for the name, otherwise the UPID keeps
    # changing
    "VNC %(id)s@%(vnc-host)s",
    # need to make sure vnc-host/port are defined in the target's tags
    # needs the .png, otherwise it balks at guessing extensions
    # don't do -q, otherwise when it fails, it fails silently; for
    # QEMU, it is *localhost*.
    "gvnccapture %(vnc-host)s:%(vnc-port)s %(output_file_name)s",
    mimetype = "image/png",
    extension = ".png"
)

#: Create a VNC screenshot capturer that captures off a VNC source
#: declared in inventory entry *vnc.NAME*
#:
#: Note the fields are target's tags and others specified in
#: :class:`ttbl.capture.generic_snapshot` and
#: :class:`ttbl.capture.generic_stream`.
#:
#: to use, add in a :ref:`server configuration file
#: <ttbd_configuration>` to any target that offers a VNC source:
#:
#: >>> target.interface_add("capture", ttbl.capture.interface(
#: >>>     vnc0_screenshot = mk_capture_screenshot_vnc("vnc0"),
#: >>>     screen = "vnc0_screenshot",
#: >>> ))

def mk_capture_screenshot_vnc(name):
    assert isinstance(name, str)
    # note the %(FIELD)s will be mapped to entries in the target's
    # inventory when the capture is going to be done, so if name is
    # ABC, it will capture off vnc.ABC,host
    return ttbl.capture.generic_snapshot(
        # dont set the port for the name, otherwise the UPID keeps
        # changing
        f"VNC %(id)s@%(vnc.{name}.host)s",
        # need to make sure vnc-host/port are defined in the target's tags
        # needs the .png, otherwise it balks at guessing extensions
        # don't do -q, otherwise when it fails, it fails silently; for
        # QEMU, it is *localhost*.
        f"gvnccapture %(vnc.{name}.host)s:%(vnc.{name}.port)s %(output_file_name)s",
        mimetype = "image/png",
        extension = ".png"
    )

#: Capture a screenshot off VNC port declared in inventory *vnc.vnc0*
capture_screenshot_vnc0 = mk_capture_screenshot_vnc("vnc0")


#: Capture video off a v4l device using ffmpeg
#:
#: See capture_screenshot_ffmpeg_v4l for setup instructions, as they
#: are common.
capture_vstream_ffmpeg_v4l = ttbl.capture.generic_stream(
    "video:/dev/video-%(id)s-0",
    "ffmpeg -i /dev/video-%(id)s-0"
    " -f avi -qscale:v 10 -y %(output_file_name)s",
    mimetype = "video/avi"
)


#: Capture audio off an Alsa device using ffmpeg
#:
#: See capture_screenshot_ffmpeg_v4l for setup instructions, as they
#: are similar.
#:
#: Note the udev setup instructions for Alsa devices are slightly
#: different; instead of *SYMLINKS* we have to set *ATTR{id}*::
#:
#:   SUBSYSTEM == "sound", ACTION == "add", \
#:     ENV{ID_PATH} == "pci-0000:00:14.0-usb-0:2.1:1.2", \
#:     ATTR{id} = "TARGETNAME"
#:
#: Once this configuration is completed, udev is reloaded (*sudo
#: udevadm control --reload-rules*) and the
#: device is triggered (with *udevadm trigger /dev/snd/controlCX* or
#: the machine restarted), */proc/asound* should contain a symlink to
#: the actual card::
#:
#:   $ ls /proc/asound/ -l
#:   total 0
#:   dr-xr-xr-x. 3 root root 0 Jun 21 21:52 card0
#:   dr-xr-xr-x. 7 root root 0 Jun 21 21:52 card4
#:   ..
#:   lrwxrwxrwx. 1 root root 5 Jun 21 21:52 TARGETNAME -> card4
#:   ...
#:
#: Device information for Alsa devices (Card 0, Card 1, etc...) can be
#: found with::
#:
#:   $ udevadm info /dev/snd/controlC0
#:   P: /devices/pci0000:00/0000:00:1f.3/sound/card0/controlC0
#:   N: snd/controlC0
#:   S: snd/by-path/pci-0000:00:1f.3
#:   E: DEVLINKS=/dev/snd/by-path/pci-0000:00:1f.3
#:   E: DEVNAME=/dev/snd/controlC0
#:   E: DEVPATH=/devices/pci0000:00/0000:00:1f.3/sound/card0/controlC0
#:   E: ID_PATH=pci-0000:00:1f.3
#:   E: ID_PATH_TAG=pci-0000_00_1f_3
#:   E: MAJOR=116
#:   E: MINOR=11
#:   E: SUBSYSTEM=sound
#:   E: TAGS=:uaccess:
#:   E: USEC_INITIALIZED=30391111
#:
#: As indicated in capture_screenshot_ffmpeg_v4l, using
#: *ENV{ID_SERIAL_SHORT}* is preferred if available.
capture_astream_ffmpeg_v4l = ttbl.capture.generic_stream(
    "audio:%(id)s",
    "ffmpeg -f alsa -i sysdefault:%(id)s"
    " -f avi -qscale:v 10 -y %(output_file_name)s",
    mimetype = "audio/wav"
)

#:
#: Capture HDMI Audio from an AGPTEK USB 3.0 HDMI HD Video Capture
#:
#: - https://www.agptek.com/AGPTEK-USB-3-0-HDMI-HD-Video-Capture-1089-212-1.html
#:
#: We can't use a generic ALSA capturer because there seem to be
#: glitches in the device
#:
capture_agptek_hdmi_astream = ttbl.capture.generic_stream(
    "hdmi0-audio:%(id)s",
    "ffmpeg -f alsa -i sysdefault:%(id)s-hdmi"
    " -f avi -qscale:v 10 -y %(output_file_name)s",
    mimetype = "audio/wav",
    pre_commands = [
        # somehow the adapter doesn't work right unless "reset" it
        # with the USB kernel interface.
        #
        # This gets the path in the
        # /sys sysfs filesystem of /dev/video-%(id)s-0 (wih 'udevadm
        # info') that yiedls something like:
        #
        #   $ udevadm info /dev/video-%(id)s-0 -q path
        #   /devices/pci0000:00/0000:00:14.0/usb1/1-4/1-4.2/1-4.2:1.0/video4linux/video0
        #
        # three levels up (removing 1-4.2:1.0/video4linux/video0) gets
        # us to the top level USB device information node:
        #
        #   /devices/pci0000:00/0000:00:14.0/usb1/1-4/1-4.2
        #
        # so in /sys/devices/pci0000:00/0000:00:14.0/usb1/1-4/1-4.2
        # there is a file called 'authorized' that will force the USB
        # device to be disconnected or connected to the
        # system. Writing 0 we soft-disconnect it, writing 1 we ask
        # for it to be connected.
        "echo 0 > /sys/$(udevadm info video-%(id)s-0 -q path)/../../../authorized",
        "sleep 0.5s",
        "echo 1 > /sys/$(udevadm info video-%(id)s-0 -q path)/../../../authorized",
        "sleep 1s",
        # vtop HW has "Digital In" for an input name
        # FIXME: we have issues with the spaces, somewhere it is being
        # split?
        "amixer -c %(id)s-hdmi sset 'Digital In' 75%%"
    ]
)

#: Capture audio with the USB capturer VTOP/JMTEK 0c76:161e
#:
#: https://www.amazon.com/Digital-Audio-Capture-Windows-10-11/dp/B019T9KS04
#:
#: This is for capturing audio on the audio grabber connected to the
#: main builtin sound output of the target (usually identified as
#: *front* by the Linux driver subsystem), which UDEV has configured
#: to be called TARGETNAME-front::
#:
#:   SUBSYSTEM == "sound", ACTION == "add", \
#:     ENV{ID_PATH} == "pci-0000:00:14.0-usb-0:2.3.1:1.0", \
#:     ATTR{id} = "TARGETNAME-front"
#:
capture_front_astream_vtop_0c76_161e = ttbl.capture.generic_stream(
    "audio:%(id)s-front",
    "ffmpeg -f alsa -i sysdefault:%(id)s-front"
    " -f wav -qscale:v 10 -y %(output_file_name)s",
    mimetype = "audio/wav",
    # vtop HW has Mic for an input name
    pre_commands = [ "amixer -c %(id)s-front sset Mic 75%%" ]
)
