=========================
Support & Troubleshooting
=========================

For support, see the :ref:`contributing section
<support_and_reporting_issues>`.


TCF client
==========

.. _tcf_client_install_troubleshooting:

*tcf* dependencies installation failures
----------------------------------------

.. _tcf_client_missing_redhat_hardened_cc1:

Missing *redhat-hardened-cc1*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

During installation with pip3::

  $ pip3 install --user -r requirements.txt
  ...
  creating build/temp.linux-x86_64-2.7
  creating build/temp.linux-x86_64-2.7/Levenshtein
  gcc -pthread -fno-strict-aliasing -O2 -g -pipe -Wall -Werror=format-security -Wp,-D_FORTIFY_SOURCE=2 -fexceptions -fstack-protector-strong --param=ssp-buffer-size=4 -grecord-gcc-switches -specs=/usr/lib/rpm/redhat/redhat-hardened-cc1 -m64 -mtune=generic -D_GNU_SOURCE -fPIC -fwrapv -DNDEBUG -O2 -g -pipe -Wall -Werror=format-security -Wp,-D_FORTIFY_SOURCE=2 -fexceptions -fstack-protector-strong --param=ssp-buffer-size=4 -grecord-gcc-switches -specs=/usr/lib/rpm/redhat/redhat-hardened-cc1 -m64 -mtune=generic -D_GNU_SOURCE -fPIC -fwrapv -fPIC -I/usr/include/python2.7 -c Levenshtein/_levenshtein.c -o build/temp.linux-x86_64-2.7/Levenshtein/_levenshtein.o
  gcc: error: /usr/lib/rpm/redhat/redhat-hardened-cc1: No such file or directory
  error: command 'gcc' failed with exit status 1

this usually happens in Fedora based distros; fix by installing
missing package::

  # dnf install -y redhat-rpm-config

  
*tcf* just hangs there, nothing happens
---------------------------------------

Add ``-v``\s right after *tcf* (e.g.: ``tcf -vvv ...``; usually this
means TCF is trying to contact a host that is either:

- nonresponsive (the server might be up, the port open but the daemon
  is not responding or the server has crashed)
- blocked by a firewall (check your proxy settings are ok)



*tcf* verbosity increase with -v reports no logging messages
------------------------------------------------------------

Adding `-vvv` as an option to *tcf* is supposed to increase logging
verbosity.

If no loggin output is reported, it has happened in the past that some
piece of code has reinitialized the logging subsystem calling
`logging.basicConfig()`, causing logging output to die.



Client operations report *EOF occurred in violation of protocol*
----------------------------------------------------------------

Any client operation (such as *tcf list*)::

  $ ~/z/tcf.git/tcf list
  Traceback (most recent call last):
    File "~/z/tcf.git/tcf", line 350, in <module>
      retval = args.func(args)
    ...
    File "/usr/lib/python2.7/site-packages/requests/api.py", line 53, in request
      return session.request(method=method, url=url, **kwargs)
    File "/usr/lib/python2.7/site-packages/requests/sessions.py", line 468, in request
      resp = self.send(prep, **send_kwargs)
    File "/usr/lib/python2.7/site-packages/requests/sessions.py", line 576, in send
      r = adapter.send(request, **kwargs)
    File "/usr/lib/python2.7/site-packages/requests/adapters.py", line 447, in send
      raise SSLError(e, request=request)
  requests.exceptions.SSLError: EOF occurred in violation of protocol (_ssl.c:590)

If your network needs proxy support and you are seeing
messages from the client as *EOF occurred in violation of
protocol*, the proxy may be cutting you off; ensure your
proxies are properly setup as per `these instructions
<setup_proxies>`_).

In a pinch, you can unset your *proxy* environment
variables are unset::

  $ unset https_proxy http_proxy HTTPS_PROXY HTTP_PROXY

if your servers are locally accesible.

*tcf run* fails compiling in Zephyr...
--------------------------------------

FIXME: update

target power on fails with *timed out waiting for udev to set permissions*
--------------------------------------------------------------------------

Targets implemented with QEMU virtual machines do networking using
Linux's TAP interfaces, which need proper permissions being set.

*ttbd* relies on file :file:`ttbd/80-udev.rules` being installed in
``/usr/lib/udev/rules.d`` to perform this function. When a power on
fails with a message looking like::

  qlf04a: /dev/tapNNN: timed out waiting for udev to set permissions in /usr/lib/udev/rules.d/80-ttbd.rules

this usually means said file is not installed; RPM installation should
have put it in ``/usr/lib/udev/rules.d``; if running from source, make
sure to install it manually and ask *udev* to reload::

  # install tcf.git/ttbd/80-udev.rules /usr/lib/udev/rules.d
  # udevadm control --reload-rules

Sometimes instead this might be SELinux issue::

  $ tcf power-on ql06a
  Traceback (most recent call last):
    File "/usr/bin/tcf", line 517, in <module>
      retval = args.func(args)
    File "/usr/lib/python2.7/site-packages/tcfl/ttb_client.py", line 799, in rest_target_power_on
      rtb.rest_tb_target_power_on(rt)
    File "/usr/lib/python2.7/site-packages/tcfl/ttb_client.py", line 319, in rest_tb_target_power_on
      data = { 'ticket': ticket })
    File "/usr/lib/python2.7/site-packages/tcfl/ttb_client.py", line 196, in send_request
      commonl.request_response_maybe_raise(r)
    File "/usr/lib/python2.7/site-packages/commonl/__init__.py", line 468, in request_response_maybe_raise
      raise e
  requests.exceptions.HTTPError: 400: ql06a: [Errno 13] Permission denied: '/dev/tap1023'

is usually caused by a SELinux check disallowing the daemon access to
the ``/dev/tapNUMBER`` device.

The system's journal might show::

  audit[11345]: AVC avc:  denied  { open } for  pid=11345 comm="ttbd" path="/dev/tap1023" dev="devtmpfs" ino=35798295 scontext=system_u:system_r:init_t:s0 tcontext=system_u:object_r:tun_tap_device_t:s0 tclass=chr_file permissive=0

there is no current proper fix, other than disabling SELinux::

  # setenforce 0

however, this seems to only happen when running the daemon from a
*$HOME* directory, instead of from a system installation.

PXE POS provisioning target fails to PXE boot: Unable to locate configuration file
----------------------------------------------------------------------------------

When a system is configured to boot targets to Provisioning OS over
PXE, a target fails to boot with a message on the BIOS console such
as::

  >>Start PXE over IPv4.
  Station IP address is 192.168.97.101
  Server IP address is 192.168.97.1
  NBP filename is ttbd-production/efi-x86_64/syslinux.efi
  NBP filesize is 176328 Bytes
  Downloading NBP file...
  NBP file downloaded successfully.
  Getting cached packet
  My IP is 192.168.97.101
  Unable to locate configuration file

There might be multiple causes for this, but here are the most common:

- there is a typo in the target's MAC address

  The target is given, via TFTP, the *syslinux PXE bootloader*, who
  will look for configuration files with multiple names (see
  https://www.syslinux.org/wiki/index.php?title=PXELINUX#Configuration_filename)
  on the TFTP server, but relies in one named after the target's MAC
  address.

  The TTBD server's :ref:`POS <pos_setup>` environment generates the
  configuration file when the network to which the target is attached
  is powered up.

  Thus, the target's MAC address listed in the configuration has to
  match the one the target actually uses on the network:

  >>> ttbl.test_target.get('TARGETNAME').add_to_interconnect(
  >>>   NETWORKNAME, dict(
  >>>       mac_addr = "00:07:32:4b:36:87",
  >>>       ipv4_addr = '192.168.98.160', ipv4_prefix_len = 24,
  >>>       ipv6_addr = 'fd:00:62::a0', ipv6_prefix_len = 104)
  >>>   )

  ensure the *mac_addr* value is the MAC address of the network
  interface the target is using to PXE boot from (*_addr* fields will
  vary from the example to your configuration).

- mismatch in IP addresses

  It is frequent to create typos in the network configuration and
  target configuration so that the target's IP address won't be in the
  network's address range. Ensure this is correct.

PXE POS provisioning target fails to boot: NFS: an incorrect mount option was specified
---------------------------------------------------------------------------------------

When the Provisoning OS kernel tries to NFS mount the root, it fails
with invalid mount option specified:

Check the MAC address is correct and the system is given the right IP
address (vs any from the pool).

This usually happens when the system doesn't recognize the MAC address
as matching the right host. It is very common when changing
names. Also, before reinitializing the server, clean up the cache::

  $ rm -rf /var/lib/tftpbootlib/ttbd-production/pxelinux.cfg/*

to ensure there are no left-over configuration files with old addresses

POS provisioning fails to install bootloader: unknown filesystem type 'vfat'
----------------------------------------------------------------------------

When provisioning a target, it boots to the Provisioning OS
environment, the image is provisioned and then when the bootloader is
going to be configured, it fails with something like::

  ...
  INFO3/f4todyDPOS ...examples/test_pos_deploy.py @v27a-vmtr|pgsotc09/nuc-17pi: [+156.8s] POS/EFI: /dev/sda1: mounting in /boot
  INFO3/f4todyDPOS ...examples/test_pos_deploy.py @v27a-vmtr|pgsotc09/nuc-17pi: [+157.4s] 1: wrote 54B (mount /dev/sda1 /boot; mkdir -p /boot/loader/entri...) to console
  ERRR2/f4todyD    ...examples/test_pos_deploy.py @v27a-vmtr|pgsotc09/nuc-17pi: [+157.7s] deploy errored: found expected (for error) `ERROR-IN-SHELL` in console `pgsotc09/nuc-17pi:1` at 0.30s
  ERRR1/f4tody	   ...examples/test_pos_deploy.py @v27a-vmtr: [+157.7s] deploy errored
  ERRR0/	toplevel @local: [+158.4s] 1 tests (0 passed, 1 error, 0 failed, 0 blocked, 0 skipped, in 0:02:37.259705) - errored
  make: *** [/tmp/tcf-TKXLbn.mk:2: tcf-jobserver-run] Error 1

in the report (for the example, *report-:f4tody.txt*) or by reading
the targets's console::

  $ tcf console-read nuc-17pi
  ...
  TCF-f4tody: 25 $ fsck.fat -aw /dev/sda1 || true
  fsck.fat 4.1 (2017-01-24)
  /dev/sda1: 1 files, 1/261372 clusters
  TCF-f4tody: 26 $ mount /dev/sda1 /boot; mkdir -p /boot/loader/entries
  mount: /boot: unknown filesystem type 'vfat'.
  ERROR-IN-SHELL

Note the error is that we cannot mount */dev/sda1* in */boot* because
the POS kernel doesn't recognize the filesystem *vfat*. This usually
means that the Provisioning OS environment doesn't have the Linux
kernel modules needed; verify that for the POS kernels available for
targets to load in */home/ttbd/public_html* or other locations
there is the corresponding Linux tree of kernel modules in the *TCF
Live* image located at */home/ttbd/images/x86_64*, subdirectory
*lib/modules*, where there shall be a subdirectory tree matching the
kernel version.

E.g, if the Linux POS kernel version is::

  TCF-f4tody: 23 $ uname -a
  Linux nuc-17pi 5.1.16-200.fc29.x86_64 #1 SMP Wed Jul 3 16:03:17 UTC 2019 x86_64 x86_64 x86_64 GNU/Linux

Then in the *lib/modules* subdir of */home/ttbd/images/x86_64*, there
shall be a subdirectory called *5.1.16-200.fc29.x86_64* which contains
the module tree for that version::

  TCF-f4tody: 24 $ $ ls -l /lib/modules
  ls -l /lib/modules
  total 8
  drwxr-xr-x 3 root root 4096 Oct 11 07:45 5.1.14-788.native
  drwxr-xr-x 6 root root 4096 Oct  2 04:01 5.1.16-200.fc29.x86_64
  drwxr-xr-x 6 root root 4096 Oct  3 03:40 5.2.17-100.fc29.x86_64

this is normall in the kernel RPM or package for the distribution; to
ensure it is installed, once you have it downloaded, you can install
it with::

  # rpm -i --root=/home/ttbd/images/x86_64 KERNEL.rpm

*ttbd* server
=============

Restart *ttbd*, watch the output for errors
-------------------------------------------

Run::

    $ journalctl -feu ttbd@NAME

`-f` follows the output, `-e` goes to the end of the file as of now,
`-u` means unit `ttbd@NAME`.

Ensure the targets are visible with `tcf list`

Log shows *can't find hub, retrying*
------------------------------------

This message::

  ... pc_ykush._command():139 target-TARGET: YKXXXXX[1]: can't find hub, retrying

this means that for whichever reason, when the YKUSH is powered on,
the system is not able to find it in the list of connected devices.

Most common cases:

  1. the configuration is not correct and it is not being powered up

     Accessing the infrastructure server, power-on the YKXXXX-base
     target and visually verify the YKush's hub led is turning on.

     If not:

     1. check the power-control configuration for the YKXXXX, is it
        the correct one?

     2. check the power brick

     3. check the micro-USB *power* cable

     Note sometimes it is useful to pluck out the components and
     test against a power outlet or USB power port we know to work.

  2. connect the hub against a wall outlet to a laptop and see if it
     enumerates, verify with `lsusb.py -iu | grep YKXXXX`

     1. Use `dmesg -w` in a laptop or another machine to verify what
        happens when you plug the hub.

     2. if `dmesg` shows messages like::

          kernel: usb 1-1.2.5: device descriptor read/64, error -32

        the micro USB cable for upstream connectivity might be bad;
        replace it.

  3. If nothing shows but the led is lit, the hub might be toast
     and is time to replace it

.. _ttbd_cannot_find_ykush_serial:

log shows errors *Cannot find YKUSH serial 'YKNNNNN'*
-----------------------------------------------------

Plenty of operations randomly fail with messages such as::

  ... @SERVER/TARGET:BSP: error resetting: 400: TARGET: Cannot find YKUSH serial 'YKNNNNN'

this is usually caused by overloaded USB buses (also :ref:`other
symptoms <troubleshooting_usb_bandwidth>`). Please spread your devices
amongst **different** USB buses that are connected to **different**
USB cards (root ports) in the host machine.

.. _systemd_tips_diagnosis:

Tips for diagnosing systemd startup
-----------------------------------

- if systemd fails to start the unit with a GROUP message, one or
  more of the supplemental groups in
  `/etc/systemd/system/ttbd@.service` might not exist; verify it.

- `journalctl -u ttbd@NAME`: to get all the log messages from the
  instance

- `journalctl -feu ttbd@NAME`: monitor log messages from the instance
  instance

- systemd fails to start the daemon with a *code=203/EXEC*:

  this is most likely a permissons issue; verify your Unix permissions
  and ACLs are right. SELinux might be in the way too (check your
  system output with *journalctl -xe* and look for ttbd.

- systemctl fails with *service not found*

  Besides the unit not existing, this might happen when you run the
  daemon from a :ref:`source directory <running_server_source>` and
  SELinux is not allowing access::

    $ sudo systemctl restart ttbd@afapli.service
    Failed to restart ttbd@afapli.service: Unit ttbd@afapli.service not found.

  Look in the *journalctl* for lines like::

    $ sudo systemctl restart ttbd@production.service
    Failed to restart ttbd@production.service: Unit ttbd@production.service not found.
    $ journalctl -S -2min | grep -B4

    ...audit[1]: AVC avc:  denied  { read } for  pid=1 comm="systemd" name="ttbd@.service" dev="dm-2" ino=48627844 scontext=system_u:system_r:init_t:s0 tcontext=unconfined_u:object_r:user_home_t:s0 tclass=file permissive=0
    ...systemd[1]: Cannot access "(null)": Permission denied
    ...systemd[1]: ttbd@production.service: Failed to load configuration: No such file or directory

  A quick way to fix this is to disable SELinux with::

    # setenforce

.. _systemd_tips_configuring:

Tips for configuring systemd startup
------------------------------------

The default integration with systemd in unit file
`/etc/systemd/system/ttbd@.service` can be extended and or modified;
for example:

1. copy `/etc/systemd/system/ttbd@.service` to `ttbd@NAME.service`
2. edit `ttbd@NAME.service`:

   - for example change the username

   - add dependencies to the `[Unit]` section, for example, if there
     is another daemon that should be started first, like::

       Requires = ttbd@NAME0.service

     this would make the `NAME0` daemon start before the `NAME`
     daemon.

3. tell systemd to reload configuration::

   # systemctl daemon-reload

Note you can use the following systemd commands (for the default
one, ommit NAME):

- `systemctl enable ttbd@NAME`: enable the running of the
       *NAME* ttbd instance automatically

- `systemctl start ttbd@NAME`: start ttbd *NAME* instance
- `systemctl stop ttbd@NAME`: stop ttbd *NAME* instance

- `systemctl status ttbd@NAME`: query status of the
  instance; add *-l* to get longer messages (without ellipsis)


USB device powers up, but serial port does not come up
------------------------------------------------------

Messages such as this pop from the server log::

  I[7742] pc.power_on_do():284: target-TARGETNAME[local:5fng]:\
    <ttbl.pc.delay_til_usb_device object at 0x7fce3611edd0>: \
    delaying power-on 5.00s until USB device with serial SOMESERIALNUMBER appears
  ...
  I[7743] ttbd.flask_logi_abort():104: TARGETNAME: \
    [Errno 2] could not open port /dev/tty-TARGETNAME: \
    [Errno 2] No such file or directory: '/dev/tty-TARGETNAME'

And *tcf run* and others report things such as::

  HTTPError: 400: TARGETNAME: timeout (39.67s) on power-on delay waiting \
  for USB device with serial SOMESERIALNUMBER to appear

There is a long list of reasons why this can happen, but these are the
most common:


- The device has no firmware that allows it to expose a serial port

- The device exposes more than one USB interface and the one which
  exposes the serial port hasn't been connected.

- The device does not have enough power to expose it's
  functionality. Inspect the kernel log with `dmesg` and verify the
  kernel is able to recognize the device and report it is powering up
  properly (for example, for an FRDM k64f)::

    usb 2-2.3.1: new full-speed USB device number 127 using xhci_hcd
    usb 2-2.3.1: New USB device found, idVendor=0d28, idProduct=0204
    usb 2-2.3.1: New USB device strings: Mfr=1, Product=2, SerialNumber=3
    usb 2-2.3.1: Product: MBED CMSIS-DAP
    usb 2-2.3.1: Manufacturer: MBED
    usb 2-2.3.1: SerialNumber: 024002011E741E6DE38AE3D5
    usb-storage 2-2.3.1:1.0: USB Mass Storage device detected
    scsi host3: usb-storage 2-2.3.1:1.0
    cdc_acm 2-2.3.1:1.1: ttyACM1: USB ACM device

.. _troubleshooting_usb_bandwidth:

- the USB bus is out of bandwidth and will refuse to configure the
  device in the USB configuration that provides the serial
  device. When trying to power up the target, look out for messages in
  the kernel log similar to (with `dmesg`)::

    usb 2-2.1.4.2: new full-speed USB device number 27 using xhci_hcd
    usb 2-2.1.4.2: New USB device found, idVendor=0d28, idProduct=0204
    usb 2-2.1.4.2: New USB device strings: Mfr=1, Product=2, SerialNumber=3
    usb 2-2.1.4.1: Product: MBED CMSIS-DAP
    usb 2-2.1.4.1: Manufacturer: MBED                                                                                                            [3199173.308138] usb 2-2.1.4.1: SerialNumber: 024002011E481E5DE3B6E3E5
    usb 2-2.1.4.1: Not enough bandwidth for new device state.

  when this happens, you need to reconfigure your setup, as you have
  probably maxed out the bandwidth of the USB bus. Posible ways to
  resolve it:

  - Move devices to another USB bus (not port, but bus). You can add
    more buses by adding new PCI-to-USB cards.

    Note some controllers show up as multiple buses to support
    different USB versions, but they are actually the same.

  - Spread your configuration across multiple physical servers
    operating in active/active mode, which also has the benefit of
    increasing the redundancy in your setup.

- `udev` is not properly configured and thus it does not see the event
  that will allow it to create whichever device link it has to
  create (see :ref:`usb_tty`).

  Double check the configuration, use `journalctl -au systemd-udevd`
  to inspect the *udev* ouput. You can also increase its log level
  with::

    # udevadm control -l debug

  power cycle the device and inspect the output from *udev* to see why
  the device link might not be created.

  Remember to restore the log level back when done to `err` to
  avoid polluting your system logs too much.


Multiple failures caused by *SELinux*
-------------------------------------

When the daemon is not installed system wide, *SELinux* will cause
multiple issues, even if started via *systemd*. This is common when
testing development versions that run from the git tree.

In these cases, the system journal will report *SELinux* denials or
interventions. In this case, sometimes the best thing is to disable
*SELinux* for the development work--however, it is important to later
test in a system wide deployment::

  # setenforce 0

will disable *SELinux*.

Different operations fail, daemon log reports *Connection reset by peer*
------------------------------------------------------------------------

This is caused in most cases by *OpenOCD* crashing, making all kinds
of operations fail. Mostly seen during retrying, where it retries and
retries but it keeps failing, with logs in the daemon such as::

  W[15024] flasher._expect_mgr():522: target-emsk-27[USER:lak2]: OpenOCD/snps_em_sk[251634500808]: target reset/halt for image flashing: Error shutting down socket: [Errno 107] Transport endpoint is not connected

there is no easy solution for this: *OpenOCD* is crashing, it is a
problem in OpenOCD or how it is being used is triggering it. The
*OpenOCD* log files in in */var/run/ttbd-production/TARGETNAME/* will
give a hint of what was being done, but will contain no information
about the crash itself.

You can run the whole setup with core file dumping enabled.

Note however, there are valid cases where *ttbd* **kills** *OpenOCD*
(when it doesn't start properly, for example), so it might be easy to
confuse them both. Run the daemon with increased verbosity to be able
to tell those cases apart.

Uploading files to the daemon fails with */var/cache/ttbd-production/USERNAME: cannot create path*
--------------------------------------------------------------------------------------------------

A client operation (normally uploading files to the server), ends with::

  requests.exceptions.HTTPError: 400: /var/cache/ttbd-production/USERNAME: cannot create path: [Errno 13] Permission denied: '/var/cache/ttbd-production/USERNAME'

if the path ``/var/cache/ttbd-production`` exists, it is owned by user
*ttbd:ttbd* and the user has permissions to write, create, this might
be a SELinux issue.

If in the system's journal, it can be found::

  $ journal -x
  ...

  python3[23087]: SELinux is preventing ttbd from create access on the directory USERNAME.

                  *****  Plugin catchall_labels (83.8 confidence) suggests   *******************

                  If you want to allow ttbd to have create access on the local directory
                  Then you need to change the label on local
                  Do
                  # semanage fcontext -a -t FILE_TYPE 'USERNAME'
                  where FILE_TYPE is one of the following: NetworkManager_unit_file_t, NetworkManager_var_run_t, abrt_unit_file_t, abrt_var_run_t, accountsd_unit_file_t, aiccu_var_run_t, ajaxterm_var_run_t, alsa_lock_t, alsa_unit_file_t, alsa_var_run_t, amanda_unit_file_t, antivirus_unit_file_t, antivirus_var_run_t, apcupsd_lock_t, apcupsd_unit_file_t, apcupsd_var_run_t, apmd_lock_t, apmd_unit_file_t, apmd_var_run_t, arpwatch_unit_file_t, arpwatch_var_run_t, asterisk_var_run_t, audisp_var_run_t, auditd_unit_file_t, auditd_var_run_t, automount_lock_t, automount_unit_file_t, automount_var_run_t, avahi_unit_file_t, avahi_var_run_t, bacula_var_run_t, bcfg2_unit_file_t, bcfg2_var_run_t, bitlbee_var_run_t, blkmapd_var_run_t, blktap_var_run_t, blueman_var_run_t, bluetooth_lock_t, bluetooth_unit_file_t, bluetooth_var_run_t, boinc_unit_file_t, bootloader_var_run_t, brltty_unit_file_t, brltty_var_run_t, bumblebee_unit_file_t, bumblebee_var_run_t, cache_home_t, cachefilesd_var_run_t, callweaver_var_run_t, canna_var_run_t, cardmgr_var_run_t, ccs_var_run_t, certmaster_var_run_t, certmonger_var_run_t, cgred_var_run_t, cgroup_t, chronyd_unit_file_t, chronyd_var_run_t, cinder_api_unit_file_t, cinder_backup_unit_file_t, cinder_scheduler_unit_file_t, cinder_var_run_t, cinder_volume_unit_file_t, clogd_var_run_t, cloud_init_unit_file_t, cluster_unit_file_t, cluster_var_run_t, clvmd_var_run_t, cmirrord_var_run_t, cockpit_unit_file_t, cockpit_var_run_t, collectd_unit_file_t, collectd_var_run_t, colord_unit_file_t, comsat_var_run_t, condor_unit_file_t, condor_var_lock_t, condor_var_run_t, config_home_t, conman_unit_file_t, conman_var_run_t, consolekit_unit_file_t, consolekit_var_run_t, container_lock_t, container_plugin_var_run_t, container_unit_file_t, container_var_run_t, couchdb_unit_file_t, couchdb_var_run_t, courier_var_run_t, cpuplug_lock_t, cpuplug_var_run_t, cpuspeed_var_run_t, cron_var_run_t, crond_unit_file_t, crond_var_run_t, ctdbd_var_run_t, cupsd_config_var_run_t, cupsd_lock_t, cupsd_lpd_var_run_t, cupsd_unit_file_t, cupsd_var_run_t, cvs_var_run_t, cyphesis_var_run_t, cyrus_var_run_t, data_home_t, dbskkd_var_run_t, dbus_home_t, dcc_var_run_t, dccd_var_run_t, dccifd_var_run_t, dccm_var_run_t, dcerpcd_var_run_t, ddclient_var_run_t, deltacloudd_var_run_t, denyhosts_var_lock_t, device_t, devicekit_var_run_t, devpts_t, dhcpc_var_run_t, dhcpd_unit_file_t, dhcpd_var_run_t, dictd_var_run_t, dirsrv_snmp_var_run_t, dirsrv_var_lock_t, dirsrv_var_run_t, dirsrvadmin_lock_t, dirsrvadmin_unit_file_t, dkim_milter_data_t, dlm_controld_var_run_t, dnsmasq_unit_file_t, dnsmasq_var_run_t, dnssec_trigger_unit_file_t, dnssec_trigger_var_run_t, dovecot_var_run_t, drbd_lock_t, drbd_var_run_t, dspam_var_run_t, entropyd_var_run_t, etc_t, eventlogd_var_run_t, evtchnd_var_run_t, exim_var_run_t, fail2ban_var_run_t, fcoemon_var_run_t, fenced_lock_t, fenced_var_run_t, fetchmail_var_run_t, fingerd_var_run_t, firewalld_unit_file_t, firewalld_var_run_t, foghorn_var_run_t, freeipmi_bmc_watchdog_unit_file_t, freeipmi_bmc_watchdog_var_run_t, freeipmi_ipmidetectd_unit_file_t, freeipmi_ipmidetectd_var_run_t, freeipmi_ipmiseld_unit_file_t, freeipmi_ipmiseld_var_run_t, fsadm_var_run_t, fsdaemon_var_run_t, ftpd_lock_t, ftpd_unit_file_t, ftpd_var_run_t, fwupd_unit_file_t, games_srv_var_run_t, gconf_home_t, gdomap_var_run_t, getty_lock_t, getty_unit_file_t, getty_var_run_t, gfs_controld_var_run_t, gkeyringd_gnome_home_t, glance_api_unit_file_t, glance_registry_unit_file_t, glance_scrubber_unit_file_t, glance_var_run_t, glusterd_var_run_t, gnome_home_t, gpm_var_run_t, gpsd_var_run_t, greylist_milter_data_t, groupd_var_run_t, gssproxy_unit_file_t, gssproxy_var_run_t, gstreamer_home_t, haproxy_unit_file_t, haproxy_var_run_t, hostapd_unit_file_t, hostapd_var_run_t, hsqldb_unit_file_t, httpd_lock_t, httpd_unit_file_t, httpd_var_run_t, hugetlbfs_t, hwloc_dhwd_unit_t, hwloc_var_run_t, hypervkvp_unit_file_t, hypervvssd_unit_file_t, icc_data_home_t, icecast_var_run_t, iceccd_var_run_t, ifconfig_var_run_t, inetd_child_var_run_t, inetd_var_run_t, init_tmp_t, init_var_lib_t, init_var_run_t, initrc_var_run_t, innd_unit_file_t, innd_var_run_t, insmod_var_run_t, iodined_unit_file_t, ipa_dnskey_unit_file_t, ipa_ods_exporter_unit_file_t, ipa_otpd_unit_file_t, ipa_var_run_t, ipmievd_lock_t, ipmievd_unit_file_t, ipmievd_var_run_t, ipsec_mgmt_lock_t, ipsec_mgmt_unit_file_t, ipsec_mgmt_var_run_t, ipsec_var_run_t, iptables_lock_t, iptables_unit_file_t, iptables_var_lib_t, iptables_var_run_t, irqbalance_var_run_t, iscsi_lock_t, iscsi_unit_file_t, iscsi_var_run_t, isnsd_var_run_t, iwhd_var_run_t, jetty_unit_file_t, jetty_var_run_t, kadmind_var_run_t, kdump_lock_t, kdump_unit_file_t, keepalived_unit_file_t, keepalived_var_run_t, keystone_unit_file_t, keystone_var_run_t, kismet_var_run_t, klogd_var_run_t, kmscon_unit_file_t, krb5kdc_lock_t, krb5kdc_var_run_t, ksmtuned_unit_file_t, ksmtuned_var_run_t, ktalkd_unit_file_t, l2tpd_var_run_t, likewise_pstore_lock_t, lircd_var_run_t, lldpad_var_run_t, local_login_lock_t, locale_t, locate_var_run_t, lockdev_lock_t, logrotate_lock_t, logwatch_lock_t, logwatch_var_run_t, lpd_var_run_t, lsassd_var_run_t, lsmd_unit_file_t, lsmd_var_run_t, lttng_sessiond_unit_file_t, lttng_sessiond_var_run_t, lvm_lock_t, lvm_unit_file_t, lvm_var_run_t, lwiod_var_run_t, lwregd_var_run_t, lwsmd_var_run_t, mailman_lock_t, mailman_var_run_t, mandb_lock_t, mcelog_var_run_t, mdadm_unit_file_t, mdadm_var_run_t, memcached_var_run_t, minidlna_var_run_t, minissdpd_var_run_t, mip6d_unit_file_t, mirrormanager_var_run_t, mock_var_run_t, modemmanager_unit_file_t, mon_statd_var_run_t, mongod_unit_file_t, mongod_var_run_t, motion_unit_file_t, motion_var_run_t, mount_var_run_t, mpd_var_run_t, mrtg_lock_t, mrtg_var_run_t, mscan_var_run_t, munin_var_run_t, mysqld_unit_file_t, mysqld_var_run_t, mysqlmanagerd_var_run_t, naemon_var_run_t, nagios_var_run_t, named_conf_t, named_unit_file_t, named_var_run_t, netlabel_mgmt_unit_file_t, netlogond_var_run_t, neutron_unit_file_t, neutron_var_run_t, nfsd_unit_file_t, ninfod_run_t, ninfod_unit_file_t, nis_unit_file_t, nmbd_var_run_t, nova_unit_file_t, nova_var_run_t, nrpe_var_run_t, nscd_unit_file_t, nscd_var_run_t, nsd_var_run_t, nslcd_var_run_t, ntop_var_run_t, ntpd_unit_file_t, ntpd_var_run_t, numad_unit_file_t, numad_var_run_t, nut_unit_file_t, nut_var_run_t, nx_server_var_run_t, oddjob_unit_file_t, oddjob_var_run_t, openct_var_run_t, opendnssec_unit_file_t, opendnssec_var_run_t, openhpid_var_run_t, openshift_var_run_t, opensm_unit_file_t, openvpn_var_run_t, openvswitch_unit_file_t, openvswitch_var_run_t, openwsman_run_t, openwsman_unit_file_t, osad_var_run_t, pads_var_run_t, pam_var_console_t, pam_var_run_t, passenger_var_run_t, pcp_var_run_t, pcscd_var_run_t, pdns_unit_file_t, pdns_var_run_t, pegasus_openlmi_storage_var_run_t, pegasus_var_run_t, pesign_unit_file_t, pesign_var_run_t, phc2sys_unit_file_t, piranha_fos_var_run_t, piranha_lvs_var_run_t, piranha_pulse_var_run_t, piranha_web_var_run_t, pkcs11proxyd_unit_file_t, pkcs11proxyd_var_run_t, pkcs_slotd_lock_t, pkcs_slotd_var_run_t, pki_ra_lock_t, pki_ra_var_run_t, pki_tomcat_lock_t, pki_tomcat_unit_file_t, pki_tomcat_var_run_t, pki_tps_lock_t, pki_tps_var_run_t, plymouthd_var_run_t, policykit_var_run_t, polipo_pid_t, polipo_unit_file_t, portmap_var_run_t, portreserve_var_run_t, postfix_var_run_t, postgresql_lock_t, postgresql_unit_file_t, postgresql_var_run_t, postgrey_var_run_t, power_unit_file_t, pppd_lock_t, pppd_unit_file_t, pppd_var_run_t, pptp_var_run_t, prelude_audisp_var_run_t, prelude_lml_var_run_t, prelude_var_run_t, print_spool_t, privoxy_var_run_t, prosody_unit_file_t, prosody_var_run_t, psad_var_run_t, ptal_var_run_t, ptp4l_unit_file_t, pulseaudio_var_run_t, puppet_var_run_t, pwauth_var_run_t, pyicqt_var_run_t, qdiskd_var_run_t, qemu_var_run_t, qpidd_var_run_t, quota_nld_var_run_t, rabbitmq_unit_file_t, rabbitmq_var_lock_t, rabbitmq_var_run_t, radiusd_unit_file_t, radiusd_var_run_t, radvd_var_run_t, rasdaemon_unit_file_t, rdisc_unit_file_t, readahead_var_run_t, redis_unit_file_t, redis_var_run_t, regex_milter_data_t, restorecond_var_run_t, rhev_agentd_unit_file_t, rhev_agentd_var_run_t, rhnsd_unit_file_t, rhnsd_var_run_t, rhsmcertd_lock_t, rhsmcertd_var_run_t, ricci_modcluster_var_run_t, ricci_modstorage_lock_t, ricci_var_run_t, rkt_unit_file_t, rlogind_var_run_t, rngd_unit_file_t, rngd_var_run_t, rolekit_unit_file_t, roundup_var_run_t, rpcbind_unit_file_t, rpcbind_var_run_t, rpcd_lock_t, rpcd_unit_file_t, rpcd_var_run_t, rpm_var_run_t, rsync_var_run_t, rtas_errd_unit_file_t, rtas_errd_var_lock_t, rtas_errd_var_run_t, samba_unit_file_t, sanlk_resetd_unit_file_t, sanlock_unit_file_t, sanlock_var_run_t, saslauthd_var_run_t, sbd_unit_file_t, sbd_var_run_t, sblim_var_run_t, screen_var_run_t, semanage_read_lock_t, semanage_trans_lock_t, sendmail_var_run_t, sensord_unit_file_t, sensord_var_run_t, setrans_var_run_t, setroubleshoot_var_run_t, shorewall_lock_t, slapd_lock_t, slapd_unit_file_t, slapd_var_run_t, slpd_var_run_t, smbd_var_run_t, smokeping_var_run_t, smsd_var_run_t, snmpd_var_run_t, snort_var_run_t, sosreport_var_run_t, soundd_var_run_t, spamass_milter_data_t, spamd_var_run_t, spc_var_run_t, speech-dispatcher_unit_file_t, squid_var_run_t, srvsvcd_var_run_t, sshd_keygen_unit_file_t, sshd_unit_file_t, sshd_var_run_t, sslh_unit_file_t, sslh_var_run_t, sssd_public_t, sssd_unit_file_t, sssd_var_run_t, stapserver_var_run_t, stunnel_var_run_t, svnserve_unit_file_t, svnserve_var_run_t, swat_var_run_t, swift_lock_t, swift_unit_file_t, swift_var_run_t, sysfs_t, syslogd_unit_file_t, syslogd_var_run_t, system_cronjob_lock_t, system_cronjob_var_run_t, system_dbusd_var_run_t, systemd_gpt_generator_unit_file_t, systemd_home_t, systemd_hwdb_unit_file_t, systemd_logind_inhibit_var_run_t, systemd_logind_sessions_t, systemd_logind_var_run_t, systemd_machined_unit_file_t, systemd_machined_var_run_t, systemd_modules_load_unit_file_t, systemd_networkd_unit_file_t, systemd_networkd_var_run_t, systemd_passwd_var_run_t, systemd_resolved_unit_file_t, systemd_resolved_var_run_t, systemd_rfkill_unit_file_t, systemd_runtime_unit_file_t, systemd_timedated_unit_file_t, systemd_unit_file_t, systemd_vconsole_unit_file_t, targetd_unit_file_t, telnetd_var_run_t, tftpd_var_run_t, tgtd_var_run_t, thin_aeolus_configserver_var_run_t, thin_var_run_t, timemaster_unit_file_t, timemaster_var_run_t, tlp_unit_file_t, tlp_var_run_t, tmp_t, tmpfs_t, tomcat_unit_file_t, tomcat_var_run_t, tor_unit_file_t, tor_var_run_t, tuned_var_run_t, udev_var_run_t, uml_switch_var_run_t, usbmuxd_unit_file_t, usbmuxd_var_run_t, user_tmp_t, useradd_var_run_t, uucpd_lock_t, uucpd_var_run_t, uuidd_var_run_t, var_lock_t, var_run_t, varnishd_var_run_t, varnishlog_var_run_t, vdagent_var_run_t, vhostmd_var_run_t, virt_lock_t, virt_lxc_var_run_t, virt_qemu_ga_var_run_t, virt_var_run_t, virtd_unit_file_t, virtlogd_unit_file_t, virtlogd_var_run_t, vmtools_unit_file_t, vmware_host_pid_t, vmware_pid_t, vnstatd_var_run_t, vpnc_var_run_t, watchdog_var_run_t, wdmd_var_run_t, winbind_var_run_t, xdm_lock_t, xdm_var_run_t, xenconsoled_var_run_t, xend_var_run_t, xenstored_var_run_t, xserver_var_run_t, ypbind_unit_file_t, ypbind_var_run_t, yppasswdd_var_run_t, ypserv_var_run_t, ypxfr_var_run_t, zabbix_var_run_t, zarafa_deliver_var_run_t, zarafa_gateway_var_run_t, zarafa_ical_var_run_t, zarafa_indexer_var_run_t, zarafa_monitor_var_run_t, zarafa_server_var_run_t, zarafa_spooler_var_run_t, zebra_unit_file_t, zebra_var_run_t, zoneminder_unit_file_t, zoneminder_var_run_t.
                  Then execute:
                  restorecon -v 'USERNAME'


                  *****  Plugin catchall (17.1 confidence) suggests   **************************

                  If you believe that ttbd should be allowed create access on the local directory by default.
                  Then you should report this as a bug.
                  You can generate a local policy module to allow this access.
                  Do
                  allow this access for now by executing:
                  # ausearch -c 'ttbd' --raw | audit2allow -M my-ttbd
                  # semodule -X 300 -i my-ttbd.pp

where *USERNAME* is any user with access to *ttbd*.

This usually happens when the daemon is being ran from an installation
that is not installed in the system; for remediation::

  # semanage fcontext -a -t var_run_t /var/cache/ttbd-staging
  # restorecon -v /var/cache/ttbd-staging

.. _ttbd_auth_ldap_invalid_creds:

LDAP login fails with invalid credentials, but the password is right, I know
----------------------------------------------------------------------------

It's been seeing that sometimes LDAP fails when the password is well
known; seen when ``journalctl -eu ttbd@production | grep -i ldap``
reports::

  Mar 21 02:08:30 HOSTNAME ttbd[10041]: I[10217] ttbd.login():249: \
    user USERNAME: invalid credentials from ldap://LDAPSERVER:PORT: \
    USERNAME: invalid credentials for LDAP ldap://LDAPSERVER:PORT: \
    {'info': '80090308: LdapErr: DSID-0C0903D9, \
      comment: AcceptSecurityContext error, data 52e, v2580', \
      'desc': 'Invalid credentials'}

Root causing help welcome, as it's still unknown.

Restarting the daemon usually fixes it::

  # systemctl restart ttbd@production


Freedom Board k64f
------------------

Freedom Board k64f, openocd fails to power up (unable to open CMSIS-DAP device 0xd28:0x204)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When an *frdm* target fails to power up and *ttbd* logs in
*journalctl -eu ttbd@production* show::

  Info : auto-selecting first available session transport "swd". To override use 'transport select <transport>'.
  Info : add flash_bank kinetis k60.flash
  adapter speed: 1000 kHz
  none separate
  cortex_m reset_config sysresetreq
  Error: unable to open CMSIS-DAP device 0xd28:0x204

this usually means *openocd* is trying to open the `/dev/hidrawN` file
that represents this device, but it can't. Usually it happens because
the way *udev* has configured it with *uaccess*, and it looks like::

  # getfacl /dev/hidraw0
  getfacl: Removing leading '/' from absolute path names
  # file: dev/hidraw0
  # owner: root
  # group: root
  user::rw-
  user:gdm:rw-
  group::---
  mask::rw-
  other::---

there is no *group::* permission and because of ACL rules, even if
there is *g+rw* in the Unix bits. The solution has been implemented
with *udev* rule that forces any CMSIS devices to be owned by group
*ttbd*.

Make sure your *ttbd-zephyr* version is at least >= *0.10_6_N-M*
with::

  # rpm -qa | grep ttbd
  ttbd-0.10_8_g69bcfa3-1.noarch
  ttbd-zephyr-0.10_8_g69bcfa3-1.noarch

which can be quickly updated with::

  # dnf update --best --allowerasing ttbd ttbd-zephyr

(:ref:`update instructions <tcf_update>`).

FRDM k64f boards fail to power up, OpenOCD prints message about RESET/WDOG loop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An FRDM board fails to power up because OpenOCD cannot initialize,
printing in the journal a message similar to::

  log: Info : SWD DPIDR 0x2ba01477
  log: Warn : **** Your Kinetis MCU is probably locked-up in RESET/WDOG loop. ****
  log: Warn : **** Common reason is a blank flash (at least a reset vector).  ****
  log: Warn : **** Issue 'kinetis mdm halt' command or if SRST is connected   ****
  log: Warn : **** and configured, use 'reset halt'                           ****
  log: Warn : **** If MCU cannot be halted, it is likely secured and running  ****
  log: Warn : **** in RESET/WDOG loop. Issue 'kinetis mdm mass_erase'         ****
  log: Info : SWD DPIDR 0x2ba01477
  log: Error: Failed to read memory at 0xe000ed00
  log: Info : accepting 'tcl' connection on tcp/38743

(which can be found with ``journalctl -au ttbd@production | grep BOARDNAME | less -S``)

this means that the board cannot boot properly because it is stuck in
a Reset/Watchdog loop. The watchdog resets the board before it can
load the firmware. OpenOCD is not able to get in there. The green led
next to the *SDAUSB* is on and next to it, the *RST* red light blinks.

The procedure to fix, involves, in the following order:

- set the up the target in debug mode

- issue OpenOCD commands to stop the loop

- copy a known firmware image to its flash drive

- reset the board to normal configuration

this is accomplished by as script in the examples directory::

  $ tcf run -vvt frdm-NN /usr/share/tcf/examples/test_frdm_recover.py


Manual execution of the procedure
+++++++++++++++++++++++++++++++++

Set the up the target in debug mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Disable the board so none tries to use it::

  $ tcf disable frdm-NN; tcf release -f frdm-NN; tcf acquire frdm-NN

.. note:: this might have to be done a few times, as other jobs might
          acquire the target in between; it helps to do it all in a
          single line.

Set OpenOCD to operate in relaxed mode, so it doesn't require the
target to be in standing order to succesfully start::

  $ tcf power-off frdm-NN
  $ tcf property-set frdm-NN openocd-relaxed True

Power cycle the target (will take a while as it will retry)::

  $ tcf power-cycle frdm-NN

it might take a while as OpenOCD tries to start. The green red light next to
green power light is on, blinking

Issue OpenOCD commands to stop the loop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Issue the OpenOCD command ``kinetis mdm halt``::

  $ tcf debug-openocd frdm-NN "kinetis mdm halt"

Repeat this command until any the following things happen:

- the following output is printed::

    Halt timed out, wake up GDB.
    Polling target k60.cpu failed, trying to reexamine
    MDM: Chip is unsecured. Continuing.
    k60.cpu: hardware has 6 breakpoints, 4 watchpoints
    k60.cpu: target state: halted
    target halted due to debug-request, current mode: Thread
    xPSR: 0x01000000 pc: 0xfffffffe msp: 0xfffffffc

- nothing is printed

- the red led stops blinking

Verify with the following command reporting the CPU is halted::

  $ tcf debug-openocd frdm-28y "targets"
  TargetName         Type       Endian TapName            State
  --  ------------------ ---------- ------ ------------------ ------------
  0* k60.cpu            cortex_m   little k60.cpu            halted

Retry otherwise, with any of::

  $ tcf debug-openocd frdm-NN "kinetis mdm halt"
  $ tcf debug-openocd frdm-NN "reset halt"

Sometimes you might have to issue a *kinetis mdm mass_erase* command
and press the *RESET* button on the board. Follow the messages.

Copy a known firmware image to its flash drive
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Flash using openocd commands::

  $ tcf debug-openocd frdm-NN "flash write_image erase /var/lib/ttbd/frdm_k64f_recovery.bin 0"
  auto erase enabled
  Flash Configuration Field written.
  Reset or power off the device to make settings effective.
  wrote 12288 bytes from file /var/lib/ttbd/frdm_k64f_recovery.bin in 0.998723s (12.015 KiB/s)

  might need to retry a couple times.

Reset the board to normal configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Remove the relaxed setting for openocd::

    $ tcf property-set frdm-NN openocd-relaxed

- power off the target::

    $ tcf power-off frdm-NN

- run a healtcheck on it::

    $ tcf healthcheck frdm-NN
    ...
    frdm-NN: healthcheck completed

- finally, enable the target for normal operation::

    $ tcf enable frdm-NN

Arduino101
----------

Arduino101: openocd fails to power up (targets report tap-disabled)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When the target fails to power up and in the daemon log,
*journalctl -eu ttbd@production* shows something like::

  init verification JTAG (1/8): Error condition: n/a
  init verification JTAG (1/8): output[before]: TargetName         Type       Endian TapName            State
  init verification JTAG (1/8): output[before]: --  ------------------ ---------- ------ ------------------ ------------
  init verification JTAG (1/8): output[before]: 0  quark_se.quark     quark_se   little quark_se.quark     tap-disabled
  init verification JTAG (1/8): output[before]: 1* quark_se.arc-em    arc32      little quark_se.arc-em    tap-disabled
  init verification JTAG (1/8): output[before]: ^Z

Note the *tap-disabled* part--this says that OpenOCD can talk to the
JTAG, but they JTAG can't talk to the CPU. There are usually the
following reasons for it:

- the JTAG cable is not properly connected; ensure the cable is the
  right one and it is properly connected, paying close attention to
  the pinout (for example, as described in the fixture documented in
  :func:`conf_00_lib_mcu.arduino101_add`).

- the hardware itself might have a hardware block against
  JTAGs. Disable it (if possible).
