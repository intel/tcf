===================
Examples and HOWTOs
===================

.. _examples_script:

Automation/testcase script examples
===================================

.. automodule:: examples.test_yielding_results
.. automodule:: examples.test_tagging

.. _examples_pos:
                
Deploying OS images and files to targets over the network
---------------------------------------------------------

TCF can do very fast :ref:`OS deployment <provisioning_os>` by
rsyncing images over the network instead of just overwritting
evertything:

- for simple testcases that just need a target provisioned, use test
  case templates :ref:`tc_pos_base <example_pos_base>`

- to have more control over the target selection process, use template
  :ref:`tc_pos0_base <example_pos0_base>`

- to have full control over the deployment process or find more
  details on how this process works in :ref:`here
  <example_pos_deploy>`

- to deploy multiple targets at the same time, for client/server
  tests, see :ref:`here <example_pos_deploy_2>` and :ref:`here
  <example_pos_deploy_N>`

- BIOS can be built and flashed too! see :ref:`here
  <example_qemu_bios>` and :ref:`here <example_qemu_bios_N>`

- to copy other content to the image after deploying the OS, see
  :ref:`this example <example_deploy_files>`

.. automodule:: examples.test_pos_base
.. automodule:: examples.test_pos0_base
.. automodule:: examples.test_pos_deploy
.. automodule:: examples.test_pos_ssh_enable
.. automodule:: examples.test_pos_deploy_2
.. automodule:: examples.test_pos_deploy_N
.. automodule:: examples.test_pos_boot
.. automodule:: examples.test_qemu_bios
.. automodule:: examples.test_qemu_bios_N
.. automodule:: examples.test_deploy_files
.. automodule:: examples.test_linux_kernel

Booting off images on the network
---------------------------------

Instead of connecting a USB drive to a machine, modern BIOSes can
download an image for you and boot off it.

.. automodule:: examples.test_efi_http_boot
.. automodule:: examples.test_efi_ipxe_sanboot

Booting to BIOS menus
---------------------

.. automodule:: examples.test_boot_to_bios_menu

                
Finding stuff in the desktop and injecting input
------------------------------------------------

TCF has a flexible expect engine, to which you can ask: wait for
something to come back on the console, has to be this; however, this
is an expandable pattern that can be extended to:

 - a regular expression of text on console output
 - wait for a pattern to show up in an image capture
 - a sound to be heard on some sound output
 - a network packet to appear in a network link
 - ... anything that can be measure capture and analyzed

These examples show case some of those use cases:

.. automodule:: examples.test_desktop_gedit
.. automodule:: examples.test_desktop_firefox_wikipedia
                
Common patterns
---------------

.. automodule:: examples.test_subcases


Capturing data, doing SSH
-------------------------

.. automodule:: examples.test_audio_capture
.. automodule:: examples.test_ssh_in
.. automodule:: examples.test_linux_ssh

.. _finding_testcase_metadata:

Keywords that are available to this testcase while running on a target
----------------------------------------------------------------------

Any of the keywords reported here can be used in a testcase script, in
multiple places of TCF configuration as Python templates with fields
such as `%(tc_name)s` and in report templates.

.. code:: python

   class _test(tcfl.tc.tc_c):
       ...
       dev eval(self, target, target1):
           ...
           something = self.kws[KEYWORDZ]
           ...
           somethingelse = target.kws[KEYWORDY]
           ...
           andthis = target1.kws[KEYWORDZ]
           ...

.. automodule:: examples.test_dump_kws
.. automodule:: examples.test_dump_kws_one_target
.. automodule:: examples.test_dump_kws_two_targets

Testcase drivers
----------------

Testcase drivers load and execute existing testcases.

.. automodule:: examples.test_ptest_runner


Creating a file in the target from the command line
---------------------------------------------------

The following Unix shell construct::

  $ cat <<EOF > somefile
  line1
  line2
  line3
  EOF

can also be done in a TCF script:

.. code-block: python

   target.shell.run("""
   cat <<EOF > somefile
   line1
   line2
   line3
   EOF""")

but since the shell console is actually *typing* the characters, it is
slightly more reliable to use:

.. code-block: python

   target.shell.run("""
   cat > somefile
   line1
   line2
   line3
   \x04
   """)

*\x04* is the ASCII end-of-transmission character, *Ctrl-D*. This is
the equivalent of typing the file contents on the command line.

Accessing the server API without the TCFL library
=================================================

The :ref:`server API <ttbd_api_http>` can also be accessed in other
ways outside the TCFL library:

Accessing the HTTP API from Python with *requests*
--------------------------------------------------

Sample code snippet to access a server using Python and the requests
module instead of the :ref:`TCF library<examples_script>` library.

This :download:`snippet <../examples/code/python.py>`:

- logs in to a server, acquiring credentials via cookies (which are
  then used for the rest of the operations)

- allocates a machine

- powers the machine off

- powers the machine on

- releases the machine


.. literalinclude:: /examples/code/python.py
   :language: python





TCF client tricks
=================

.. _tcf_client_configuration:

Where is the TCF client configuration taken from?
-------------------------------------------------

*tcf* reads configuration files from (in this order):

- *.tcf* (a subdirectory of the current working directory)
- *~/.tcf*
- *~/.local/etc/tcf* (if installed in user's home only with *python
  setup.py install --user* or *pip install --user*)
- */etc/tcf* (if installed globally, eg with a package manager)

Configuration files are called *conf_WHATEVER.py* and imported in
**alphabetical** order from each directory before proceeding to the
next one. They are written in plain Python code, so you can do
anything, even extend TCF from them. The module :mod:`tcfl.config`
provides access to functions to set TCF's configuration.

You can add new paths to parse with ``--config-path`` and force
specific files to be read with ``--config-file``. See *tcf --help*.

How do I list which targets I own?
----------------------------------

Run::

  $ tcf list -v 'owner:"MYNAME"'

*MYNAME* is whatever identifier you used to login.

.. _howto_release_target:

How do I release a target I don't own?
--------------------------------------

Someone owns the target and they have gone home...::

  $ tcf release -f TARGETNAME

But this only works if you have admin permissions.

The exception is if you have locked yourself the target with a
*ticket* (used by *tcf run* and others so that the same user running
different processes in parallel can still exclude itself from
overusing a target). It will say something like::

  requests.exceptions.HTTPError: 400: TARGETNAME: tried to use busy target (owned by 'MYUSERNAME:TICKETSTRING')

As a user, you can always force release any of your own locks with
`-f` or with `-t TICKETSTRING`::

  $ tcf -t TICKETSTRING release TARGETNAME

How do I release all the targets I own?
---------------------------------------

Run::

  $ tcf release -f $(tcf list 'owner:"MYNAME"')

- *MYNAME* is whatever identifier you used to login
- *tcf list 'owner:"MYNAME"'* lists which targets you currently own

.. _howto_target_keep_acquired:

How do I keep a target acquired
-------------------------------

The server will release targets it considers idle.

The server considers activity, once acquired

 - running server commands (such as power control, console
   reading/writing, accessing buttons, etc)

 - script execution (since those run commands)

The server can't detect as activity:

 - accessing the target via a tunnel (eg: an SSH session)

 - accessing the target via the network or instrumentation not
   abstracted by the server (eg: a KVM)

When the server doesn't detect activity, it will release the target to
make it available to others. If the system is being actively used, but
you find the server making it available because you are using
interfaces that the server doesn't know about, you can run::

  $ tcf acquire TARGETs --hold

``--hold`` takes the *acquire* command to send keep alives to the
server indicating the machine is under active use. It will keep
sending commands until you cancel it (or give it a time length for
which to send keep alives).

If the target is already acquired, you can find the allocation ID with
*tcf ls -v*::

   $ tcf ls -v TARGETNAME
   SERVER/TARGETNAME [USERNAME:b2Bkhb]

*b2Bkhb* is the allocation ID in this case; now use *tcf
acquire... --hold* to keep it allocated::

  $ tcf -a b2Bkhb acquire TARGETNAME --hold

Read on for how this can be combined with *tcf run*

How do I keep a target acquired/reserved after *tcf run* is done?
-----------------------------------------------------------------

Giving *--no-release* to *tcf run* will keep the target acquired after
the scrip execution concludes. Note however that it will be acquired
by *USERNAME\::term:`ALLOCID`* (:term:`what's an ALLOCID? <allocid>`).

For example, if we were using targets *nwa* and *qu04a* to :ref:`boot
in provisioning mode <example_pos_boot>`:

  $ tcf run --no-release -vvt 'nwa or qu04a' /usr/share/examples/test_pos_boot.py
  ...
  INFO1/ormorh	  ..../test_pos_boot.py#_test @3hyt-uo3g: will run on target group 'ic=localhost/nwa target=localhost/qu04a:x86_64'
  ...

to find the allocation ID, upon completion::

  $ tcf list -v owner
  localhost/nwa [USERNAME:ALLOCID] ON
  localhost/qu04a [USERNAME:ALLOCID] ON

to maintain the target acquired and powered while potentially
debugging or testing other things, run in a separate console, run::

  $ tcf -a ALLOCID acquire nwa qu04a --hold
  OoOWEa: NOT ALLOCATED! Holdin allocation ID given with -a
  allocation ID OoOWEa: [+224.5s] keeping alive during state 'active'

now you can access the console, do captures or interact with the
target in any other way, remembering to specify the ticket::

  $ tcf console-write -i qu04a
  $ tcf capture-get qu04a screen screencap.png
  ...

.. _howto_access_target_via_ssh:

or via SSH, first we have to ask the server to create a tunnel for us
from to the target's SSH port::

  $ tcf tunnel-add qu04a 22
  SERVERNAME:19893
  $ ssh -p 19893 root@SERVERNAME

.. note:: make sure you specify the user to login as; it likely won't
          be the same as in your client machine.

.. warning: remember to cancel the *tcf acquire* command when done
            with the target so other users can acquire it and use it.

You can also run either of::

  $ tcf release nwa qu04a
  $ tcf alloc-rm ALLOCID

Some details:

 - if you depend on the network, do not forget to also acquire the
   network, otherwise it will be powered off and routing won't work.

How can I debug a target?
-------------------------

TCF provides for means to connect remote debuggers to targets that
support them; if the target supports the :mod:`debug <ttbl.debug>`
interface (which you can find with `tcf list -vv TARGETNAME | grep
interfaces`).

How it is done and what are the capabilities depends on the target,
but in general, assuming you have a target with an image deployed::

  $ tcf acquire TARGETNAME
  $ tcf debug-start TARGETNAME
  $ tcf power-on TARGETNAME
  $ tcf debug-info TARGETNAME
  GDB server: tcp:myhostname:3744 (when target is on; currently ON)

at this point, the target is waiting for the debugger to connect
before powering up, so start (in this case) GDB pointing it to the
*elf* version of the image file uploaded and issue::

  gdb> target remote tcp:myhostname:3744

Some targets might support starting debugging after power up.

Find more:

- `tcf --help | grep debug-`

- the :class:`debug extension API <tcfl.target_ext_debug.extension>` to
  :class:`target objects <tcfl.tc.target_c>` for use inside Python testcases

- the server level debug interface :class:`ttbl.debug`

Zephyr debugging with TCF run
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When using targets in a high usage environment, it is easier to use
TCF run and a few switches:

- Make sure the target is acquired for a max of 30min while you work with it::

    $ for ((count = 0; count < 240; count++)); do tcf -t 1234 acquire TARGETNAME; sleep 15s; done &

  be sure to kill this process when done, to free it for other people;
  every 15s this re-acquires, as a way to tell the daemon you are
  still using it, to not free it from you.

  Note `-t 1234`; this says *use ticket 1234* to reserve this target;
  we'll use it later.

- Create a temporary directory::

    $ mkdir tmp

- Build and deploy::

    $ tcf -t 1234 run -vvvv -E --tmpdir tmp -t TARGETNAME --no-release PATH-TO-TC

  note the following:

  - `-t 1234` says to use ticket 1234, as the one we used for the reservation

  - `-E` tells it not to evaluate -- it will just build and deploy / flash

  - `--no-release` says do not release the target when done (because
    you want to do other stuff, like debug)

  - In the case of Zephyr, the ELF file will be in
    `tmp/1234/outdir-1234-SOMETHING/zephyr/zephyr.elf`, which you can
    find with::

      $ find tmp/1234/ -iname zephyr.elf
      tmp/1234/outdir-1234-j38h-quark_d2000_crb/zephyr/zephyr.elf

- Tell the target to start debugging::

    $ tcf -t 1234 debug-start TARGETNAME

- Now reset / power cycle it, so it goes fresh to start. Because we
  told it to start debugging, it will start but stop the CPU until you
  attach a debugger (only for OpenOCD targets or targets that support
  debugging, anyway)::

    $ tcf -t 1234 reset TARGETNAME
    $ tcf -t 1234 debug-info TARGETNAME
    OpenOCD telnet server: srrsotc03.iind.intel.com 20944
    GDB server: x86: tcp:srrsotc03.iind.intel.com:20946
    Debugging available as target is ON

- Note we now can start the debugger; find it first::

    $ find /opt/zephyr-sdk-0.9.5/ -iname \*gdb
    ...
    /opt/zephyr-sdk-0.9.5/sysroots/x86_64-pokysdk-linux/usr/bin/i586-zephyr-elf/i586-zephyr-elf-gdb
    ...

  run the debugger to the ELF file we found above::

    $ /opt/zephyr-sdk-0.9.5/sysroots/x86_64-pokysdk-linux/usr/bin/i586-zephyr-elf/i586-zephyr-elf-gdb \
        tmp/1234/outdir-1234-j38h-quark_d2000_crb/zephyr/zephyr.elf
    ...
    Reading symbols from tmp/1234/outdir-1234-j38h-quark_d2000_crb/zephyr/zephyr.elf...done.

  tell the debugger to connect to the GDB server found by running
  `debug-info` before::

    (gdb) target remote tcp:srrsotc03.iind.intel.com:20946
    Remote debugging using tcp:srrsotc03.iind.intel.com:20946
    0x0000fff0 in ?? ()

  Debug away!::

    (gdb) b _main
    Breakpoint 1 at 0x180f71: file /home/inaky/z/kernel.git/kernel/init.c, line 182.
    (gdb) c
    Continuing.
    target running
    redirect to PM, tapstatus=0x08302c1c
    hit software breakpoint at 0x00180f71

    Breakpoint 1, _main (unused1=0x0, unused2=0x0, unused3=unused3@entry=0x0) at /home/inaky/z/kernel.git/kernel/init.c:182
    182	{
    (gdb)
    ...

- on a separate terminal, you can:

  - read the target's console output with::

      $ tcf console-read --follow TARGETNAME

  - issue CPU resets, halts, resumes or OpenOCD commands (for targets
    that support it)::

      $ tcf debug-reset TARGETNAME
      $ tcf debug-halt TARGETNAME
      $ tcf debug-resume TARGETNAME
      $ tcf debug-openocd TARGETNAME OPENOCDCOMMAND

Note that resetting or power-cycling the board will create a new GDB
target with a different port, so you will have to reconnect that GDB
wo the new target remote reported by *tcf debug-info*.

.. _howto_pos_list_deploy:

How can I quickly flash a Linux target
--------------------------------------

When your server and targets are configured for Provisisoning OS
support (target exports the *pos_capable* tag in ``tcf list -vv
TARGET``), you can quickly flash the target *target1A*, which is
connected to network *nwA* with::

  $ IMAGE=fedora::29 tcf run -vvvt 'nwA or target1A' /usr/share/tcf/examples/test_pos_deploy.py

to find our which images your server has available

.. _howto_pos_list_images:

To find out available images::

  $ tcf run /usr/share/tcf/examples/test_pos_list_images.py
  server10/nwa clear:live:25550::x86_64
  server10/nwa clear:live:25890::x86_64
  server10/nwa fedora::29::x86_64
  server10/nwa yocto:core-minimal:2.5.1::x86_64
  PASS0/	toplevel @local: 1 tests (1 passed, 0 error, 0 failed, 0 blocked, 0 skipped, in 0:00:06.635452) - passed

See how to :ref:`install more images <ttbd_pos_deploying_images>`.


How can I quickly build and deploy an image to a Zephyr target?
---------------------------------------------------------------

You can use the boilerplate testcase :download:`test_zephyr_boots.py
<../examples/test_zephyr_boots.py>`, which will build any Zephyr app
and try to boot it and see if it prints the Zephyr boot banner::

  $ ZEPHYR_APP=path/to/source tcf run -t TARGETNAME /usr/share/tcf/examples/test_zephyr_boots.py
  $ tcf acquire TARGENAME
  $ <work on it> ...

TCF will build your code configuring it properly for the chosen target
and deploy it. You want to inmediately acquire so it is not
powered-off by the daemon.


TCF's `run` says something failed, can I get more detail?
---------------------------------------------------------

FIXME: update

TCF's ``run`` tries to be quiet to the console, so when you run a lot
of tests on a lot of targets, the forest lets you see the trees.

When you need more detail, you can:

- add `-v`\s after ``run`` (but then it gives you detail everywhere)

- log to a file with `--log-file=FILENAME` and when something fails,
  grep for it::

    FAIL0/kaoe ../Makefile[quark]@.../frankie: (dynamic) build failed
    PASS1/tctp ../Makefile[x86]@.../mv-03: (dynamic) build passed

  that build failed; take those four letters next to the ``FAIL0``
  message (`kaoe`) -- that's a unique identifier for each message, and
  look for it with `grep`, printing 30 lines of context before the match::

    $ grep -B 100 kaoe FILENAME
    ....
    FAIL3/iigx ../Makefile[quark]@.../frankie: @build failed [2] ('make -j -C samples/hello_world/nanokernel BOARD=quark_se_sss_ctb  O=outdir-httpsSERVER5000ttb-v0targetsfrankie-quark_se_sss_ctb-quark_se_sss_ctb' from /home/inaky/z/kernel.git/samples/.tcdefaults:48)
    FAIL3/iigx ../Makefile[quark]@.../frankie: output: FF make: Entering directory '/home/inaky/z/kernel.git/samples/hello_world/nanokernel'
    FAIL3/iigx ../Makefile[quark]@.../frankie: output: FF make[1]: Entering directory '/home/inaky/z/kernel.git'
    ...

  most likely, the complete failure message will be right before the
  final failure message -- and you can now tell what happened. In this
  case, there is no good configuration for the chosen target

  The output driver can be changed to lay out the information
  diferently; look at :ref:`more information on report drivers
  <tcf_guide_report_driver>`.

Linux targets: Common tricks
----------------------------

.. _linux_c_c:

Linux targets: sending Ctrl-C to a target
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Trick over the serial console is that it is a pure pipe, there is no
special characters. So a quick way to do it is::

  $ tcf console-write TARGETNAME $(echo -e \\x03)

where that *\\x03* is the hex code of Ctrl-C. *man ascii* can tell you
the quick shortcuts for others.

.. _linux_send_command_target:

Linux targets: running a Linux shell command
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Try::

  $ tcf console-write TARGETNAME "ping -c 3 localhost"

Note that once the command is sent, the console, for whatever the
target cares, is still connected, even if the *console-write* command
returned for you. The command might still be executing; see
:ref:`Sending a Ctrl-C <linux_c_c>` is not as in a usual, synchronous,
Linux console.

From a script, you can use :func:`tcfl.tc.target_c.shell.run
<tcfl.target_ext_shell.shell.run>` or :func:`tcfl.tc.target_c.send`:

.. code-block:: python

   ...
   @tcfl.tc.target("linux")
   class some_test(tcfl.tc.tc_c):

       def eval_something(self, target):
           ...
           target.shell.send("ping localhost")
           target.shell.expect("3 packets transmitted, 3 received")
           ...
           # better to use
           ...
           target.shell.run("ping -c 3 localhost",
                            "3 packets transmitted, 3 received")

you can also get the output by adding ``output = True``:

.. code-block:: python

           ...
           output = target.shell.run("ping -c 3 localhost",
                                     "3 packets transmitted, 3 received",
                                     output = True)
           ...

.. _tunnels_linux_ssh:

Linux targets: ssh login from a testcase / client
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The :term:`ttbd` server can create tunnels that allow you to reach the
target's ports, assuming the target is

- connected to a network to which the server is also connected
- on and listening on a port

In your test scripts, use the :class:`tunnel
<tcfl.target_ext_tunnel.tunnel>` extension to create a port
redirection, adding to your script:

.. code-block:: python

   ...
   @tcfl.tc.interconnect("ipv4_addr")
   @tcfl.tc.target(...)
   class some_test(tcfl.tc.tc_c):

       def eval_something(self, ic, target):
           ...
           # ensure target and interconnect is powered up and the
           # script is logged in.
           # Indicate to the tunnel system the target's address in the
           # interconnect
           target.tunnel.ip_addr = target.addr_get(ic, "ipv4")

           # create a tunnel from server_name:server_port -> to target:22
           server_name = target.rtb.parsed_url.hostname
           server_port = target.tunnel.add(22)

           # use SSH to get the content's of the target's /etc/passwd
           output = subprocess.check_output(
                        "ssh -p %d root@%s cat /etc/passwd"
                        % (server_port, server_name),
                        shell = True)

Tunnels can also be created with the command line::

  $ tcf tunnel-add TARGETNAME 22 tcp TARGETADDR
  SERVERNAME:19893
  $ ssh -p 19893 root@SERVERNAME cat /etc/passwd
  root:x:0:0:root:/root:/bin/bash
  bin:x:1:1:bin:/bin:/sbin/nologin
  daemon:x:2:2:daemon:/sbin:/sbin/nologin
  adm:x:3:4:adm:/var/adm:/sbin/nologin
  ...

Note you might need first the steps in the next section to allow SSH
to login with a passwordless root.

Linux targets: restarting the SSH daemon
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

See the examples in :func:`tcfl.tl.linux_ssh_root_nopwd`.

.. _target_pos_manually:

How do I boot a target to PXE boot mode manually?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A target can be told to boot to PXE Provisioning OS by issuing the
following commands::

  $ while tcf acquire NETWORKNAME TARGETNAME; do sleep 10s; done &
  $ tcf power-on NETWORKNAME
  $ tcf property-set TARGETNAME pos_mode pxe
  $ tcf power-cycle TARGETNAME

.. FIXME: make an entry explaining well the while loop thing

The *while* loop in the background keeps the target acquired, do not
forget to release them by killing it. Then we ensure the network is on
and finally, we set the target to *POS mode* PXE and we power cycle
the target.

To have it boot back in local mode::

  $ tcf property-set TARGETNAME pos_mode
  $ tcf power-cycle TARGETNAME

.. _pos_boot_http_tftp:

POS: booting from HTTP or TFTP
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When a target is given a syslinux configuration file to boot from, the
places where it loads the Provisioning OS kernels can be forced with
:ref:`pos_http_url_prefix <pos_http_url_prefix>`.

By default (no prefix) the boot loader will tend to load with
TFTP. But by specifying an HTTP or FTP URL prefix, it can boot over
any of those protocols (which can be faster).

When specified in an interconnect's tags, it will be taken as default
for that interconnect, but this can be overriden specifying it for
each target; for the example in :ref:`POS: Configuring networks
<ttbd_pos_network_config>`, we can add::

  pos_http_url_prefix = "http://192.168.97.1/ttbd-pos/%(bsp)s/"

This will replace in the syslinux configuration file any occurrence of
``pos_http_url_prefix`` with
``http://192.168.97.1/ttbd-pos/ARCHNAME/``, where ``ARCHNAME`` is the
architecture of the target.

.. _linux_target_pos_kernel_options:

Linux targets: POS: setting default linux kernel options
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When a Linux target is botted using :term:`POS`, default kernel
options can be fed to the POS scripts for bootloader consumption by
setting the following tags or properties (all optional):

- ``linux_serial_console_default``: sets which is the default serial
  console. For */dev/NAME*, specify *NAME*, as this will be given as
  the Linux kernel command line option *console=NAME,115200*

- ``linux_options_append``: a space separated string with any other
  Linux kernel command line options to add.

For example, when adding the target:

>>> ttbl.config.target_add(
>>>     ...
>>>     tags = {
>>>         ...
>>>         'linux_serial_console_default': 'ttyS2',
>>>         'linux_options_append': 'rw foo=bar',
>>>         ...
>>>     })

which can also be done once the target is added with
:meth:`tags_update <ttbl.test_target.tags_update>`::

>>> ttbl.test_target.get('TARGETNAME').tags_update({
>>>         ...
>>>         'linux_serial_console_default': 'ttyS2',
>>>         'linux_options_append': 'rw foo=bar',
>>>         ...
>>>     })

.. _tcf_testcase_proxy:

Linux targets: using proxies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:term:`NUT`\s to which targets are connected are usually setup very
isolated from upstream or other networks; there is a common practice
to declare a proxy availability in an interconnect by it exporting any
of the following variables::

  $ tcf list -vv nwb | grep -i proxy
  ftp_proxy: http://192.168.98.1:911
  http_proxy: http://192.168.98.1:911
  https_proxy: http://192.168.98.1:911

so in a test script running a Linux target, one could do:

.. code-block:: python

   @tcfl.tc.interconnect("ipv4_addr")
   @tcfl.tc.target('pos_capable')
   class _test(tcfl.tc.tc_c):

       def eval_something(self, ic, target):
           ...
           if 'http_proxy' in ic.kws:
              target.shell.run("export http_proxy=%s" % ic.kws.get('http_proxy'))
              target.shell.run("export HTTP_PROXY=%s" % ic.kws.get('http_proxy'))
           if 'https_proxy' in ic.kws:
              target.shell.run("export https_proxy=%s" % ic.kws.get('https_proxy'))
              target.shell.run("export HTTPS_PROXY=%s" % ic.kws.get('https_proxy'))
           ...

note however, that those settings will apply only to the shell being
run in that console. You can make more permanent settings in the
target by for example, modifying ``/etc/bashrc``::

   @tcfl.tc.interconnect("ipv4_addr")
   @tcfl.tc.target('pos_capable')
   class _test(tcfl.tc.tc_c):

       def eval_something(self, ic, target):
           ...
           if 'http_proxy' in ic.kws:
              target.shell.run("echo http_proxy=%s >> /etc/bashrc" % ic.kws.get('http_proxy'))
              target.shell.run("echo HTTP_PROXY=%s >> /etc/bashrc" % ic.kws.get('http_proxy'))
           if 'https_proxy' in ic.kws:
              target.shell.run("echo https_proxy=%s >> /etc/bashrc" % ic.kws.get('https_proxy'))
              target.shell.run("echo HTTPS_PROXY=%s >> /etc/bashrc" % ic.kws.get('https_proxy'))
           ...

and those will also apply if your script logs in via SSH or other methods.


Linux targets: removing the root password
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If your target is not connected to any networks or to an isolated
network, you can remove the root password.

.. code-block:: python

   ...
   @tcfl.tc.interconnect("ipv4_addr")
   @tcfl.tc.target("linux")
   class some_test(tcfl.tc.tc_c):

       # ensure target is powered up and the script is logged in
       def eval_something(self, ic, target):
           ...
           target.shell.run("passwd -d root")
           ...

or from the console::

  $ tcf console-write TARGETNAME "passwd -d root"
  $ tcf console-read TARGETNAME
  ...
  # passwd -d root
  Removing password for user root.
  passwd: Success

.. _linux_ssh_no_root_password:

Linux targets: allowing SSH as root with no passwords
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Most Linux deployments default configure SSH to be very conservative;
for testing, you might want to open it up.

To allow login in with SSH, add to your test script:

.. code-block:: python

   ...
   @tcfl.tc.interconnect("ipv4_addr")
   @tcfl.tc.target("linux")
   class some_test(tcfl.tc.tc_c):

       # ensure target is powered up and the script is logged in
       def eval_something(self, ic, target):
           target.shell.run("""\
   cat <<EOF >> /etc/ssh/sshd_config
   PermitRootLogin yes
   PermitEmptyPasswords yes
   EOF""")
           target.shell.run("systemctl restart sshd")

or using the :func:`library function tcfl.tl.linux_ssh_root_nopwd
<tcfl.tl.linux_ssh_root_nopwd>`:

.. code-block:: python

   import tcfl.tl
   ...
   @tcfl.tc.interconnect("ipv4_addr")
   @tcfl.tc.target("linux")
   class some_test(tcfl.tc.tc_c):

       # ensure target is powered up and the script is logged in
       def eval_something(self, ic, target):
           ...
           tcfl.tl.linux_ssh_root_nopwd(target)
           ...
           target.shell.run("systemctl restart sshd")

or even having that done in deployment time when flashing with POS:

.. code-block:: python

   @tcfl.tc.interconnect("ipv4_addr")
   @tcfl.tc.target('pos_capable', mode = 'any')
   class _test(tcfl.tc.tc_c):

       def deploy(self, ic, target):
           # ensure network, DHCP, TFTP, etc are up and deploy
           ic.power.on()
           ic.report_pass("powered on")

           image = target.pos.deploy_image(
               ic, "clear",
               extra_deploy_fns = [ tcfl.pos.deploy_linux_ssh_root_nopwd ])


or from the shell::

  $ tcf console-write TARGETNAME "echo PermitRootLogin yes >> /etc/ssh/sshd_config"
  $ tcf console-write TARGETNAME "echo PermitEmptyPasswords yes >> /etc/ssh/sshd_config"

.. _tcf_client_timetout:

How do I change the default timeout in my test scripts
------------------------------------------------------

The default timeout different parts of the *tcf run* engines wait for
the target to respond can be changed by setting the variable
*self.tls.expect_timeout* (note *self* is a testcase class):

.. code-block:: python

   class some_tc(tcfl.tc.tc_c):
       ...
       def eval_some(self):
           # wait a max of 40 seconds
           self.tls.expect_timeout = 40
           ...

It is a bit awkward and we'll make a better way to do it. Other places
that take a *timeout* parameter that has to be less than
*self.tls.expect_timeout*:

- :func:`target.shell.up <tcfl.target_ext_shell.shell.up>`
- :func:`target.on_console_rx <tcfl.tc.target_c.on_console_rx>`
- :func:`target.wait <tcfl.tc.target_c.wait>`
- :func:`target.expect <tcfl.tc.target_c.expect>`

and others

.. _report_always:

Making the client always generate report files
----------------------------------------------

*tcf run* will normally generate a report file if a testcase does not
*pass*. If you want report files generated always, you can add to any
:ref:`configuration file <tcf_client_configuration>`:

.. code-block:: python

   tcfl.report_jinja2.driver.templates['text']['report_pass'] = True

Reporting is handled by the :mod:`reporting API <tcfl.tc.reporter_c>`
and the *report* files are created by the Jinja2 :mod:`reporter
<tcfl.report_jinja2>` based on a template called *text*.

.. _report_domain_breakup:

Splitting report files by domain
--------------------------------

You could want to break your testcases by a domain, mapping to any
categories and you can want the report files to be stored in specific
subdirectories.

You can define a hook that calculates that domain and generates
metadata for it, so the templating engine can use it

>>> ...
>>> tcfl.tc.tc_c.hook_pre.append(_my_hook_fn)
>>> filename = tcfl.report_jinja2.driver.templates["text"]["output_file_name"]
>>> tcfl.report_jinja2.driver.templates["text"]["output_file_name"] = \
>>>     "%(category)s/" + file_name

The `_my_hook_fn()` would look as:

>>> def _my_hook_fn(testcase):
>>>     # define some calculations that generates category
>>>     testcase.tag_set("category", categoryvalue)

If the data needed is not available until after the testcase executes,
you can use :class:`reporting hooks <tcfl.report_jinja2.driver.hooks>`.

Capturing network traffic
-------------------------

TCF servers (*ttbd*) can capture the traffic in a :term:NUT network if
they are connected to it.

For this to happen, when the network is powered up, it must contain a
property called *tcpdump* set to a file name where to capture it::

  $ tcf property-set nwb tcpdump somename.cap
  $ tcf power-cycle nwb

when all the network traffic is done, it can be downloaded::

  $ tcf power-off nwb
  $ tcf store-dnload nwb somename.cap local_somename.cap

which now can be opened with wireshark to see what happened (or
analyzed with other tools).

In a script, ensure your start routine contains:

>>> class sometest(tcfl.tc.tc_c):
>>>
>>>     def start_something(self, ic, ...):
>>>         ...
>>>         # before powering up the interconnect
>>>         ic.property_set('tcpdump', self.kws['tc_hash'] + ".cap")
>>>         ...
>>>         ic.power.cycle()

and on teardown:

>>>
>>>     def teardown_whatever(self, ic, ...):
>>>         ic.store.dnload(
>>>              self.kws['tc_hash'] + ".cap",
>>>              "report-%(runid)s:%(tc_hash)s.tcpdump" % self.kws)
>>>         self.report_info("tcpdump available in file "
>>>                          "report-%(runid)s:%(tc_hash)s.tcpdump" % self.kws)

the file will be made available in the same directory where *tcf run*
was executed from.


.. _tcf_ci:

Continuous Integration
----------------------

*TCF run* can be used in a CI system to run testcases as part of the
continuous integration process. A few helpful tricks:

Generate a unique ID for each run and feed it to TCF
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is common practice to generate a unique ID for each build or
continuous integration run. It should include:

- timestamp (YYMMDD-HHMM): allows to tell when the build happened and
  to map to logs in other parts of the system; might not be sufficient
  if more than one build can be started in the same hour/minute/second

- monotonic counter (BBB): CI engines like Jenkins will refer to
  builds by their internal build monotonic counter--it also helps
  distinguish in the unlikely case two builds were started on the same
  second (or minute)

- branch/project identifier (PROJECT-BRANCH): if a single build might
  be running on multiple branches or projects, it helps to add a short
  version of it -- thus, when the Unique ID is propagated to other
  parts of the CI system, we can see who is causing whatever action.

*tcf run* supports the concept of a :ref:`RunID <tcf_run_runid>`,
which will be then used in all the reports.

A good RunID specification for *TCF run* would be something like::

  PROJECT-BRANCH-YYMMDD-HHMM-BBB

it is a good idea to also give it to the hashing engine as salt so
that the :term:`hash` identifiers used to acquire targets don't
conflict with other projects that might be using the same
testcase. e.g.::

  $ tcf run --hash-salt PROJECT-BRANCH-YYMMDD-HHMM-BBB \
      --runid PROJECT-BRANCH-YYMMDD-HHMM-BBB -v path/to/testcases

add to the hash salt any other factors that might contribute to the
same testcase/target combination being run as the same but that shall
be considered different (eg: using a different toolchain).

Splitting in multiple shards
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When running CI in multiple slaves in parallel, the CI engine can tell
*tcf run* to only run an specific shard of the whole list of
testcases. Assuming all the slaves have the same list of testcases,
the list will be evenly split::

  slave1$ tcf run --shard 1-3 --runid X path/to/testcases
  slave2$ tcf run --shard 2-3 --runid X path/to/testcases
  slave3$ tcf run --shard 3-3 --runid X path/to/testcases

will split the deck of testcases in 3 shards and run one on each slave
in parallel.

Note that if the availability of targets to run the shards doesn't
allow them to run testcases in parallel, you might not gain much by
the paralallelization of *tcf run*.

Controlling output location
^^^^^^^^^^^^^^^^^^^^^^^^^^^

*tcf run* can be given ``--log-dir`` to specify the location where
most default output files will be placed, including:

- failure/error/block/skip reports
- tcpdump outputs

this defaults to the directory where *tcf run* was invoked from.

.. _general_catchas:

General catchas
===============

Some common issues that make it automating hard

Hidden characters in console output, ANSI menus
-----------------------------------------------

This happens very commonly when console prompts or text produce ANSI
escape sequences to colorize output; as a human on the console, we see
clearly the *root@hostname:DIR* prompt, but our regex for the console
is expecting:

``root@SOMETHING:DIR``

however, the chain of bytes that the serial port is reading might be

``ESC[ 38;5;2rootESC[ 38;5;2SOMETHING:DIR``

(where ESC is the escape character, ASCII 0x1b dev 27) and hence why
the regular expression is not working.

Parsing ANSI escape sequences is quite tricky and if this is a command
prompt, a more simple sollution is to remove them from the prompt
configuration.

An option to see them is::

  tcf console-read --follow TARGET | cat -A

``-A`` in cat will escape the ANSI characters for you.

When trying to automate an application that implements an ANSI TUI
(Text User Interface) with menus and such, it becomes quite
complicated. For example, BIOS over serials.

The application might be sending strings such as:

    - *^[[X;YHSTRING* put *STRING* in X,Y
    - *^[[0m* normal letters
    - *^[[1m* bold letters
    - *^[[37m* white FG
    - *^[[40m* black BG

sometimes text is intersped in ANSI escape sequences (especially with
very awkward software) that print **STRING** like this::

  ^[[1mS^[[1mT^[[1mR^[[1mI^[[1mN^[[1mSG

to match this against a regular expression, you need to do::

  re.compile("\x1b\[1mS\x1b\[1mT\x1b\[1mR\x1b\[1mI\x1b\[1mN\x1b\[1mSG")

for example

Another problem is the sequence of characters you will see on the
screen menu but how they come out in the serial port might be
different; it usually helps to open two terminals, side by side and in
one open the TUI via the TCF console::

  $ tcf console-write -i TARGET

and on another, just the byte stream::

  $ tcf console-read --follow TARGET | cat -A

interacting with it on the first console will give you an idea of what
is actually printed that can be used to latch on.

Hints on disabling coloured output in Linux commands::

  $ grep --color=never ...
  $ ls --color=never ...

Newlines when reading output of a command
-----------------------------------------

Let's say we are reading the top level tree of a git directory:

>>> tree = subprocess.check_output(
>>>      [
>>>          'git', 'rev-parse', '--flags', '--show-toplevel',
>>>          'SOMEFILENAME'
>>>      ],
>>>      stderr = subprocess.STDOUT,
>>>      cwd = os.path.dirname('SOMEFILENAME')
>>> )

then we try to use *tree* and it does not exist. Why? because::

  $ git rev-parse --flags --show-toplevel SOMEFILENAME
  SOMEPATH
  $

which means that after *SOMEPATH* there is a newline and thus the
output we are getting is *SOMEPATH\\n*. So :func:`strip
<string.strip>` it:

>>> tree = tree.strip()

General Linux system
====================

.. _setup_wsl:

Setup: install Windows Services for Linux (WSL)
-----------------------------------------------

The TCF client can be installed in Windows Services for Linux, which
can be setup following these instructions (applies to WSL v1,
untested on v2):

1. Enable Windows Services for Linux (summary of
   https://docs.microsoft.com/en-us/windows/wsl/install-win10):

   A. Open PowerShell as Administrator and run (press left Windows
      key, type *PowerShell* and click on *Run as administrator*)::

        Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux

   B. Restart your computer when prompted.

2. Wait for Windows to boot

3. Press left Windows key, type *Microsoft store* > search for *Ubuntu
   18.04 LTS*, press on *Get*; wait for Ubuntu 18.04 LTS to download.

4. Click 'Launch" for the install process to start; opens a Ubuntu
   18.04 LTS black window that works for a while.

   Install process will ask to *Enter new Unix name*, this is your
   Unix account name.

   Install process will ask for a *Unix password*: enter a password
   for the Unix machine that will run inside your Windows machine; you
   can use the same as in Windows

5. The install process now goes into a Linux shell; it can be closed.

6. Click the Windows search box, type *Ubuntu*, select *Ubuntu
   18.04 LTS*; a terminal window opens.

From the Linux environment, you can access your Windows files:

- `/mnt/c/Users/USERNAME/Desktop`
- `/mnt/c/Users/USERNAME/Documents`

From here, you can :ref:`install the client <install_tcf_client>`.

.. _setup_proxies:

Setup proxies
-------------

.. note:: this applies to setting the proxy for the server; if you
          need to set proxies during testcase execution, see
          :ref:`here <tcf_testcase_proxy>`

If your network requires proxy support:

- From the GUI: log in as a normal user to the graphical interface

  1. On the top right click the configuration arrow, select * →
     configuration icon → select network → select proxies*

  2. Set:

     - Method *Manual*

     .. include:: 04-HOWTOs-LL-proxy-1.rst

- From the terminal, (when remotedly logged in, optional) add to
  ``/etc/environment`` (for system wide, headless machines):

    .. literalinclude:: 04-HOWTOs-LL-proxy-2.sh
       :language: shell

Why?

.. include:: 04-HOWTOs-LL-proxy-3.rst

- *127.0.0.1/8* and *192.168.0.0/16* will be all networks we'll use
  internally from our server, so they don't need to be proxyed.

.. _tcf_update:

How do I update my TCF installation?
------------------------------------

You can check if there is a new version available with::

  # dnf check-update --refresh | grep TCF

if so, you can update to it with::

  # dnf update --best ttbd ttbd-zephyr tcf tcf-zephyr
  # systemctl restart ttbd@production

Note that if there is a major version change (from *v0* to *v1*, or
*v1* to *v2*, etc), more steps have to be done, which will be like
(example is from *v0* to *v1*)

.. include:: 04-HOWTOs-LL-update.rst

This is so because we release the TCF stable branches as separate RPM
repositories, for simplicity.

Note you might need to clean the metadata caches with::

  # dnf clean all

to force an update of the metadata to be pulled from the servers.

.. _internal_network:

Configuring a USB or other network adapter for an infrastructure network
------------------------------------------------------------------------

Test targets or infrastructure (like power control switches) that
require IP connectivity can be connected to your server via a
dedicated network interface and switch.

.. warning:: do not connect infrastructure and test devices to the
             same network! You have to :ref:`keep them separated
             <separated_networks>`.

You will need:

- a network interface (USB, PCI, etc)
- its MAC address
- an IP address range (recommended *192.168.X.0/24*)

1. Identify the network interface you will use, using tools such as::

     # ifconfig -a
     # ip addr

2. Now configure it as described in :ref:`Configuring a static interface
   Via NetworkManager's nmcli <howto_nm_config_static>`::

     # nmcli con add type ethernet con-name TCF-infrastructure ifname IFNAME ip4 192.168.0.20X/24
     # nmcli con up TCF-infrastructure

   note that you can also use VLANs if you add with **type vlan id NN
   dev IFNAME** for VLAN number ``NN``::

     # nmcli con add type vlan con-name TCF-Infrastructure dev enp0s20u4 id 4 ip4 192.168.4.209/24

Conventions for assignment of addresses in the infastructure network:

- use IPv4 (easier)

- use a local network (eg: 192.168.x.0/24)

- servers get IP addresses > 192.168.x.200 (try to establish a server
  naming conventions where numbers are assigned, *server1*, *server2*,
  etc) and thus their IP addresses are *.201*, *.202*, etc...

- PDUs and other equipment use IP addresses > 192.168.x.100

.. warning:: Keep this switch isolated from upstream routers; connect
             only test-targets OR infrastructure elements to it.

Configuring network interfaces with NetworkManager and nmcli
------------------------------------------------------------

NetworkManager will by default take control of most network interfaces
in the system; some adjustments might be needed.

.. _howto_nm_disable_control:

Disabling NetworkManager from controlling an interface
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Network interfaces which connect the server to a NUT (network under
test) need to be left alone by NetworkManager. NetworkManager can be
told to ignore a network device in two ways:

- run the command::

    # nmcli dev set IFNAME managed no

- or create a configuration file::

    $ sudo tee /etc/NetworkManager/conf.d/disabled.conf <<EOF
    [keyfile]
    unmanaged-devices=mac:00:10:60:31:a4:ba
    EOF

  Or edit said file and add *mac:MACADDR* statements separated by
  semicolons to the *unmanaged-devices* line.


.. _howto_nm_config_static:

Configuring a static interface Via NetworkManager's nmcli
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To configure an internal network interface *IFNAME* for internal
network for infrastructure control *192.168.2.0/24* with IP *.205* ,
run::

  # nmcli con add type ethernet con-name NETWORKNAME ifname IFNAME ip4 192.168.2.205/24
  # nmcli con up NETWORKNAME

note that you can also use VLANs if you add with **id NN** for VLAN
number ``NN``::

  # nmcli con add type vlan con-name NETWORKNAME dev IFNAME id NN ip4 192.168.2.205/24


.. _generate_ssl_certificate:

Generating an SSL certificate
-----------------------------

To use secure layers HTTPS connections between daemon and client, you
must have a valid certificate and key, or use an autosigned
certificate. This can be fed to the target server with the options
``--ssl-crt`` and ``--ssl-key``.

If  you want to create your own certificate you must have installed
OpenSSL:

1. Generate a private key::

   $ openssl genrsa -des3 -out server.key 1024

2. Generate a CSR::

   $ openssl req -new -key server.key -out server.csr

3. Remove Passphrase from key::

   $ cp server.key server.key.org
   $ openssl rsa -in server.key.org -out server.key

4. Generate self signed certificate::

   $ openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt

 Instructions taken from:
 http://kracekumar.com/post/54437887454/ssl-for-flask-local-development

.. _configure_udev:

Configuring and reloading UDEV
------------------------------

*udev* is the Linux low-level service that acts when devices are
added/removed from/to the system to set them up. TCF relies on it to
create device alias named after the targets to make administration
easier.

- *udev* rule configuration files are stored in */etc/udev/rules.d/*
  and are called *NN-FILENAME.rules*, where *NN* is a number to sort
  inclusion. Most commonly you can use *90-ttbd.rules*

- When the rule file is changed, it can be reloaded with::

    # udevadm control --reload-rules

- Information about a given device can be obtained with::

    $ udevadm info /dev/snd/controlC0
    P: /devices/pci0000:00/0000:00:1f.3/sound/card0/controlC0
    N: snd/controlC0
    S: snd/by-path/pci-0000:00:1f.3
    E: DEVLINKS=/dev/snd/by-path/pci-0000:00:1f.3
    E: DEVNAME=/dev/snd/controlC0
    E: DEVPATH=/devices/pci0000:00/0000:00:1f.3/sound/card0/controlC0
    E: ID_PATH=pci-0000:00:1f.3
    E: ID_PATH_TAG=pci-0000_00_1f_3
    E: MAJOR=116
    E: MINOR=11
    E: SUBSYSTEM=sound
    E: TAGS=:uaccess:
    E: USEC_INITIALIZED=30391111

  those *KEYS=* we can use to match in the *udev* rule files to do
  actions.

- Verbosity can be controlled with::

    # udevadm control -l LEVEL    (see --help)

.. _find_usb_info:

Finding USB device information
------------------------------

To find information about USB devices (serial numbers, paths) use any
of these methods.

Note it is also possible that a device declares a serial number but it
is all the same for every device (for example, in the FlySwatter2 and
other FTDI based hardware). In FTDI based case, it is possible to
re-flash a new serial number with :ref:`these instructions
<fs2_serial_update>`

.. note:: use these methods in a Linux machine that is not running
          *TTBD* actively, as it will keep producing messages in the
          kernel output and it will be difficult to tell which device
          is the right one.

Finding USB device information with dmesg
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. disconnect the device
2. run `dmesg -w` in a console to see the kernel log, hit ``enter`` a
   few times to create space
3. plug the device, see a message pop up with device data from the
   kernel
4. Note the device data, along::

     usb 1-1.4.4.4.1: new full-speed USB device number 62 using ehci-pci
     usb 1-1.4.4.4.1: New USB device found, idVendor=2a03, idProduct=003d
     usb 1-1.4.4.4.1: New USB device strings: Mfr=1, Product=2, SerialNumber=220
     usb 1-1.4.4.4.1: Product: Arduino Due Prog. Port
     usb 1-1.4.4.4.1: Manufacturer: Arduino (www.arduino.org)
     usb 1-1.4.4.4.1: SerialNumber: 85439303033351E06162

   in this example, ignore the *SerialNumber* where it says *New USB
   device Strings* and focus on the following one.

   If there is no serial number, there will be something like::

     New USB device strings: Mfr=XYZ, Product=XYZ, SerialNumber=0

   and no line with just *SerialNumber* on its own will appear.

Finding USB device information with lsusb.py
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``lsusb.py -iu`` provides a tree display of the USB connected devices::

  usb1            1d6b:0002 09  2.00  480MBit/s 0mA 1IFs (ehci_hcd 0000:00:1a.7) hub
   1-1            05e3:0608 09  2.00  480MBit/s 100mA 1IFs (Genesys Logic, Inc. Hub) hub
    1-1.1         2001:f103 09  2.00  480MBit/s 0mA 1IFs (D-Link Corp. DUB-H7 7-port USB 2.0 hub) hub
     1-1.1.1      0424:2514 09  2.00  480MBit/s 2mA 1IFs (Standard Microsystems Corp. USB 2.0 Hub) hub
      1-1.1.1.1   2a03:003d 02  1.10   12MBit/s 100mA 2IFs (Arduino (www.arduino.org) Arduino Due Prog. Port 85439303033351E01192)
     1-1.1.2      0424:2514 09  2.00  480MBit/s 2mA 1IFs (Standard Microsystems Corp. USB 2.0 Hub) hub
      1-1.1.2.4   04d8:f2f7 00  2.00   12MBit/s 100mA 1IFs (Yepkit Lda. YKUSH YK20946)
       1-1.1.2.4:1.0(IF) 03:00:00 2EPs (Human Interface Device:No Subclass:None)
     1-1.1.5      0403:6001 00  2.00   12MBit/s 90mA 1IFs (FTDI FT232R USB UART A5026SO1)

if we know the brand of our device, we can look it up; in the excerpt
tree below, we can see, for example, a YKUSH on *1-1.1.2.4*; next to
the name of the device is the serial number (if available), *YK20946*
(in this example).

Finding USB device information with udevadm
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Once we know a device node of any time has been established (eg:
:file:`/dev/ttyUSB9`), use ``udevadm info`` to find information about
it::

  # udevadm info /dev/ttyUSB0	# or whichever device node (eg: /dev/video or /dev/snd/XYZ)
  P: /devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0/ttyUSB0/tty/ttyUSB0
  N: ttyUSB0
  S: serial/by-id/pci-Prolific_Technology_Inc._USB-Serial_Controller-if00-port0
  S: serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0
  ...
  E: ID_SERIAL_SHORT=OR0497598
  E: ID_PATH=pci-0000:00:14.0-usb-0:2:1.0
  E: ID_PATH_TAG=pci-0000_00_14_0-usb-0_2_1_0
  E: ID_PCI_CLASS_FROM_DATABASE=Serial bus controller
  E: ID_PCI_INTERFACE_FROM_DATABASE=XHCI
  E: ID_PCI_SUBCLASS_FROM_DATABASE=USB controller
  ...

those values can be used to match in udev

.. _usb_tty:

udev configuration of serial port
---------------------------------

Methods for configuring a serial port by name. When a USB serial port
is connected to the system, it is assigned a non-predictable name (eg:
*/dev/ttyUSB14* or */dev/ttyACM3*) which will change each time is
plugged (or not).

In order to have an stable name that consistently represents the
device we are connecting, follow any of the following recipes, based
on the capabilities of the USB device you are plugging to the system.

.. _usb_tty_serial:

udev configuration of serial port based on serial number
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Given a target name (TARGETNAME) we are going to name a serial port
assigned to it `/dev/tty-TARGETNAME` based on the *serial number* of
the USB device (that can be found using the :ref:`tricks above
<find_usb_info>`) in :file:`/etc/udev/rules.d/90-ttbd.rules`::

  SUBSYSTEM == "tty", ENV{ID_SERIAL_SHORT} == "SERIALNUMBER", \
    SYMLINK += "tty-TARGETNAME"

Remember to :ref:`update udev <configure_udev>`::

    # udevadm control --reload-rules

.. _usb_tty_path:

udev configuration of serial port without serial number based on path
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is used for USB serial dongles that have no unique USB serial number.

.. warning:: This approach is very risky--any physical changes in the
             positions of cables or logical changes in enumeration
             order when kernel boots will change the path and might
             render your configuration inoperative or working incorrectly.

Given a target name (TARGETNAME) we are going to name a serial port
assigned to it `/dev/tty-TARGETNAME` based on the *path* the USB
device is connected, as most serial cables have no serial number; in
:file:`/etc/udev/rules.d/90-ttbd.rules`::

  SUBSYSTEM == "tty", ENV{ID_PATH} == "*-usb-0:1.2.2:1.0", \
    SYMLINK += "tty-TARGETNAME"

find the path by plugging the device, using `dmesg -w` to find which
`/dev/ttyUSBX` (or `/dev/ttyACMX`) name is given and then running::

  # udevadm info /dev/ttyUSBX | grep ID_PATH=
  ID_PATH=pciblahblah-usb-0:1.2.2:1.0

:ref:`reload udev config <configure_udev>`::

  # udevadm control --reload-rules

replug the USB dongle or device and verify the symlink
`/dev/tty-TARGETNAME` is there.

If not found, use syslog or `journalctl -r` and `udevadm
control --log-level debug` to find our what is going on when the
device is plugged.


.. _usb_tty_sibling:

udev configuration of serial port based on sibling's serial number
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is used for USB-to-TTY serial dongles that have no unique USB
serial number.

Given a target name (TARGETNAME) we are going to name a USB-to-TTY
serial port assigned to it `/dev/tty-TARGETNAME` based on the USB
serial number of another device (the sibling) connected to the same
USB hub.

The sibling USB device has to have a unique USB serial number. By
knowing in which port our the USB-to-TTY serial dongle is, we can
piggy back on the other sibling device's USB serial number.

Thus, if we move the USB hub around, it'll still have the same name,
as long as we don't change the port to which it is connected.

In :file:`/etc/udev/rules.d/90-ttbd.rules`::

  # When the USB-TTL port is connected to the hub with serial number
  # YKXXXXX
  SUBSYSTEM == "tty", \
      PROGRAM = "/usr/bin/usb-sibling-by-serial YKXXXXX", \
      ENV{ID_PATH} == "*2:1.0", \
      SYMLINK += "tty-TARGETNAME"

note the ``*2:1.0``; that selects port 2, where we connect the
serial port adapter. Port 1 would be ``*1:1.0``, etc.

Remember to :ref:`update udev <configure_udev>`::

  # udevadm control --reload-rules

.. _usbrly08b_serial_number:

Finding the serial number of a Devantech USBRLY08B relay controller
-------------------------------------------------------------------

Plug your board to the system and list::

  $ lsusb.py | grep -i Devantech
   1-1.1.1       04d8:ffee 02  2.00   12MBit/s 100mA 2IFs (Devantech Ltd. USB-RLY08 00023456)

*00023456* is the serial number; if there are multiple devices and you
are not sure which one is it, disconnect the one you care for and run::

  $ lsusb.py | grep -i Devantech > before

now reconnect it and run::

  $ lsusb.py | grep -i Devantech > after

diff the files *before* and *after*::

  $ diff before after
  3d2
  <  1-1.1.1       04d8:ffee 02  2.00   12MBit/s 100mA 2IFs (Devantech Ltd. USB-RLY08 00023456)

or run `dmesg -w` on the terminal, unplug and plug the device, see the
kernel message about the new USB device, note the serial number.


.. _ykush_serial_number:

Finding the serial number of an YKUSH hub
-----------------------------------------

Methods to find the serial number of an YKUSH hub:

- plug your YKush hub to the system and list::

    # lsusb.py | grep YKUSH | tee before
      2-2.1.1.4    04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21297)
      2-2.1.2.4    04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21292)
      2-2.1.3.4    04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21290)
      2-2.1.4.4    04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21294)
     2-2.3.4       04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21293)

  you might have many; to tell which one is the one in your hand, you
  can just unplug it and list again::

    # lsusb.py | grep YKUSH | tee after
     2-2.1.1.4    04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21297)
     2-2.1.2.4    04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21292)
     2-2.1.4.4    04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21294)
    2-2.3.4       04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21293)

  to (quickly) find out which one was unplugged, diff the files
  *before* and *after*::

    # diff before after
    3d2
    <     2-2.1.3.4    04d8:f2f7 00  2.00   12MBit/s 100mA 1IF  (Yepkit Lda. YKUSH YK21290)

  the line that was removed when we unplugged was the one for *YK21290*,
  which is the serial number of the hub.

- run `dmesg -w` on a terminal and plug the device, see the kernel
  message about the new USB device, note the serial number

.. note:: the hub itself has no serial number, but an internal device
          connected to its downstream port number 4 does have the
          *YK34567* serial number.


.. _howto_fog_ipxe:

iPXE: sharing bootloader with a Fog installation
------------------------------------------------

TCF can use the services provided by a `Fog installation
<http://fogproject.org>`_; however, to be able to use effectively,
Fog's iPXE Ctrl-B prompt has to be enabled.

By default, the Fog setup process creates their own iPXE binary and
disable the Ctrl-B prompt that allows to break into the console to do
manual configuration.

This does not change the process work workflow, it just enables the
targets to be able to use Ctrl-B while booting. TCF uses that to drive
its own provisioning mechanism.

To enable back the Ctrl-B prompt:

1. login to your Fog server, and locate file
   */tftpboot/default.ipxe*; we need to add a line::

    prompt --key 0x02 --timeout 2000 Press Ctrl-B for the iPXE command line... && shell ||

2. Edit the */tftpboot/default.ipxe* file and add said line after the first line::

     #!ipxe
     <<<<===== HERE ===>>>>
     cpuid --ext 29 && set arch x86_64 || set arch ${buildarch}
     params
     param mac0 ${net0/mac}
     param arch ${arch}
     param platform ${platform}
     param product ${product}
     ...

   so it ends up looking as::

     #!ipxe
     prompt --key 0x02 --timeout 2000 Press Ctrl-B for the iPXE command line... && shell ||
     cpuid --ext 29 && set arch x86_64 || set arch ${buildarch}
     params
     param mac0 ${net0/mac}
     ...

*ttbd*: TCF server configuration and tricks
===========================================

.. _ttbd_config_multiple_instances:

Starting more that one instance
-------------------------------

Most setups will only have one instance, the *production* instance;
however, two more are recommended:

- *infrastructure*: handles power to USB hubs, equipment, normal and
  power switching to reset them in case) of issues, individual raw
  access to all the power switching units connected throughout the
  system, network switches, etc

- *staging*: targets whose drivers are being developed before moving
  into production (optional)

To bring up an instance (repeat these steps replacing *production* with
*INSTANCENAME* for other instances):

1. Create the instance's configuration directory::

     # install -d -m 2775 -o ttbd -g ttbd /etc/ttbd-production

   systemd will create the runtime directories needed when starting
   *ttbd* in `/var/run/ttbd-production` and
   `/var/cache/ttbd-production` as they will be wiped by the system
   on restart.

2. Each instance listens on a different port, so we create the initial
   server configuration `/etc/ttbd-production/conf_00_bind.py`::

     host = "0.0.0.0"		# Listen on all interfaces
     port = 5000

   *infrastructure* is usually assigned 4999, *staging* 5001. Enable
   access through the firewall to said ports::

     # firewall-cmd --add-port=4999-5001/tcp --permanent

4. Enable and start the instance::

     # systemctl enable ttbd@production
     # systemctl start ttbd@production

   *systemd* runs the daemon run as user *ttbd*, group *ttbd* and
   the following supplemental groups:

     - *root*: to be able to scan USB devices
     - *dialout*: to be able to access serial devices and USB connected
       serial devices (for consoles, JTAGs, etc)
     - *ttbd*: to access configuration and other files

   See log output with ``journalctl -fu ttbd@NAME``. Diagnose issues
   starting with systemd in :ref:`troubleshooting
   <systemd_tips_diagnosis>`. Further configuration :ref:`tips
   <systemd_tips_configuring>`.

5. At this point you could create or copy existing ``conf_*.py``
   configuration files to ``/etc/ttbd-production`` and restart the
   service with::

     # systemctl restart ttbd@production

   If you have none, that is ok, we'll add them in the next sections.

Note that now, none can access the server yet because there is no way
to authenticate with it :) Let's add some configuration.


.. _ttbd_configuration:

Where is the TCF server (TTBD) configuration taken from?
--------------------------------------------------------

*ttbd* reads configuration files from an invocation & installation
specific set of paths.

In most cases, the configuration comes from */etc/ttbd-production*
(configuration for the system-wide production instance of *ttbd*).

Other options:

  - when multiple *ttbd* instances are to be executed side by side,
    this can be controlled with the *-i INSTANCE* command line switch
    to *ttbd* so configuration is loaded from */etc/ttbd-INSTANCE*.

    When invoking with systemd, service *ttbd@INSTANCE* loads from
    */etc/ttbd-INSTANCE*; see :ref:`starting multiple instances
    <ttbd_config_multiple_instances>`.

  - when running from source or manually, configuration and state
    paths defaults to *~/.ttbd/*

  - use the command line switch *--config-path* to force a different
    configuration path.

Configuration files are called *conf_NN_WHATEVER.py* and imported in
**alphabetical** order from each directory before proceeding to the
next one. They are written in plain Python code, so you can do
anything, even implement or add drivers from them. The naming
convention establishes the following levels:

- *conf_00_\*.py*: configuration libraries provided by the
  distribution (documented :ref:`here <ttbd_conf_api>`)

- *conf_01_\*.py*: configuration libraries specific to your deployment

- *conf_04_\*.py*: configuration files specific to the :term:`herd`
  (such as authentication, ports where the server listens, etc)

- *conf_05_\*.py*: configuration of server-specific authentication

- *conf_06_\*.py*: configuration of defaults, some come from the
  source distribution, some might be specific to the site, etc.

- *conf_09_\*.py*: configuration of :term:`site` specifics

- *conf_10_SERVERNAME.py*: configuration of the server's targets

The module :mod:`ttbl.config` provides access to the top functions to
set TTBD's configuration.

.. _ttbd_config_auth_local:

Configure authentication for local users (optional)
---------------------------------------------------

A quick way to allow any user in the local machine to use the server
without authenticating is to request local authentication for
127.0.0.1; run::

  # echo 'local_auth.append("127.0.0.1")' \
    > /etc/ttbd-production/conf_00_auth_local.py
  # systemctl restart ttbd@production

Now login in should work with no need to input anything (in this case,
there will be no output either)::

  $ tcf -iu https://localhost:5000 login

.. note:: feel free to ignore the error message about `ZEPHYR_BASE not
          being defined`; it is a glitch that will be fixed. You can
          work around it by running::

            $ export ZEPHYR_BASE=

You can configure local TCF clients to access the local instance
by default (:ref:`more <tcf_configuring>`)::

  # mkdir -p /etc/tcf
  # echo "tcfl.config.url_add('https://localhost:5000', ssl_ignore = True)" \
    >> /etc/tcf/conf_local.py


.. _ttbd_config_authdb:

Configure simple authentication / for Jenkins jobs (optional)
-------------------------------------------------------------

You can setup static accounts for users or Jenkins autobuilders with
passwords by following the instructions in :class:`ttbl.auth_userdb.driver`

.. _ttbd_config_auth_ldap:

.. include:: 04-HOWTOs-LL-auth-ldap.rst

Configure authentication against LDAP
-------------------------------------

Copy the configuration example
`/etc/ttbd/production/example_conf_05_auth_ldap.py` and modify it to
suit your LDAP setup::

  # cp /etc/ttbd-production/example_conf_05_auth_ldap.py /etc/ttbd-production/conf_05_auth_ldap.py
  # <edit away>
  # systemctl restart ttbd@production

Authorized users (users in the declared LDAP groups in the
configurtion file) should now be able to login with::

  $ tcf login LDAPLOGIN

This file can be tweaked to fit your authentication needs. For
example, you might want to change the name of the LDAP groups your
users need to be members off.

If this does not work, most likely the configuration files where not
loaded properly; check the daemon output (:ref:`troubleshooting
<systemd_tips_diagnosis>` and :ref:`troubleshooting LDAP
<ttbd_auth_ldap_invalid_creds>`).



.. _tt_power:

Configuring a target for just controlling power to something
------------------------------------------------------------

In your *ttbd*'s `conf_SOMETHING.py` config file, add::

  target_pdu_socket_add("TARGETNAME",
        pc = POWER_CONTROLLER,
        tags = dict(idle_poweroff = 0),
        power = True)

this creates a target called *TARGETNAME* that you can power on, off
or cycle. The *power* argument indicates what do do with the power at
startup (*True* turn it on, *False* turn it off, *None*--or omitting
this argument, leave it as is). *tags = dict(idle_poweroff = 32)* is
used to have *TARGETNAME* not being powered off when idle.

Now, *PC_OBJECT* is the actual implementation of power control and you
can make it be things like::

  ttbl.pc.dlwps7("http://admin:1234@sp3/5")

This would make *TARGETNAME*'s power be controlled by plug #5 of the
*Digital Logger Web Power Switch 7* named *sp3* (:py:func:`setup
instructions <conf_00_lib_pdu.dlwps7_add>`). Because this is a normal,
120V plug, if a light bulb were connected to it::

  target_pdu_socket_add("Entrance_light",
        pc = ttbl.pc.dlwps7("http://admin:1234@sp3/5"),
        tags = dict(idle_poweroff = 0),
        power = True)

and like this, the target *Entrance_light* can be switched on or off
with *tcf power-on Entrance_light* and *tcf power-off Entrance_light*.

It could also be::

  ttbl.pc_ykush.ykush("YK21080", 3)

which means that power to *TARGETNAME* would be implemented by
powering on or off port #3 of the YKush power-switching hub with
serial number *YK21080* (:py:func:`setup instructions
<conf_00_lib_pdu.ykush_targets_add>`).

Other power controller implementations are possible, of course, by
subclassing :py:class:`ttbl.power.impl_c`; currently there are
multiple power control drivers listed here FIXME.

.. _tt_linux_simple:

Configuring a Linux target to power on/off with serial console
--------------------------------------------------------------

FIXME: old documentation, needs updating

Building on the previous example, we can create a target that provides
serial consoles, can be powered on or off and we can interact with the
target over the serial console.

If we have a Linux machine which is installed with a distro that
provides serial console access, then this will work:

**Bill of materials**

- a Linux machine
- a serial console to the physical Linux machine (if your machine
  doesn't have serial ports, a `USB null modem
  <https://www.serialgear.com/Serial-Adapters-USBG-NULL-30.html>`_ or
  two USB serial dongles with a NULL modem adapter will do.
- one available port on a power switch, to turn the physical machine
  on/off (eg, a :func:`DLWPS7 <conf_00_lib_pdu.dlwps7_add>`)

**Connecting the test target fixture**

1. Configure the Linux machine to:

   - always power on when AC power is on

   - provide a serial console on the serial port; this can be done by
     adding ``console=ttyS0,115200`` and/or ``console=ttyUSB0,115200``
     to the kernel command line.

     In modern systemd-enable distributions, also with::

       # systemd enable agetty@ttyUSB0
       # systemd enable agetty@ttyS0

3. Connect the serial dongle cables to the physical target and to the
   server

4. Connect the physical target to port PORT of power switch
   POWERSWITCH

**Configuring the system for the fixture**

1. Choose a name for the target: *linux-NN* (where NN is a number)

2. Configure *udev* to add a name for the serial device for the
   board's serial console so it can be easily found at
   ``/dev/tty-TARGETNAME``. Follow :ref:`these instructions
   <usb_tty_serial>` using the serial dongle's *serial number*.

3. Add a configuration block to the server configuration file:

   .. code:: python

      FIXME: needs reformulating

.. _target_tag:

Adding tags to a target
-----------------------

Once a target is configured, new tags can be added to it using
:meth:`ttbl.test_target.tags_update` in any configuration file
(preferrably next to the target definition); for example, if in
``/etc/ttbd-production/conf_10_targets.py`` you had the statement:

.. code-block:: python

   arduino101_add(name = "a101-15",
                  fs2_serial = "a101-15-fs2",
                  ykush_url = "http://admin:1234@HOSTNAME/PORT",
                  ykush_serial = "YK24439")

you can add the tags ``fixture_spi_basic_0`` (as a boolean that
defaults to *True* and  ``tempsetting`` (as an integer) with:

.. code-block:: python

   arduino101_add(name = "a101-15",
                  fs2_serial = "a101-15-fs2",
                  ykush_url = "http://admin:1234@HOSTNAME/PORT",
                  ykush_serial = "YK24439")
   tcfl.config.targets['a101-15'].tags_update(dict(
       fixture_spi_basic_0 = True,
       tempsetting = 32))

.. _target_disable_default:

How do I disable a target by default?
-------------------------------------

When a target has to be disabled by default, add this to the
configuration file::

  ttbl.test_target.get('TARGETNAME').disable("")

the target will be loaded and the configuration will be accesible,
however, *tcf* clients that select targets automatically (*list*,
*run*) will not use it unless *-a* is given.

This is used for targets that are misbehaving for any reason but still
need to be connected to debug. They can be manually enabled/disabled
with::

  $ tcf disable TARGETNAME
  $ tcf enable TARGETNAME

The user has to have *admin* capabilities in the *TTBD* server to run
this operation.

.. _ttbd_config_bind:

Allowing the server to be used remotely
---------------------------------------

By default, the server is configured to only listen on local ports,
thus only accessible from the server itself.

To allow the server to be accessible on all the network interfaces of
the machine on TCP port 5000, create
``/etc/ttbd-production/conf_00_bind.py`` with the content:

.. code-block:: python

   host = "0.0.0.0"
   port = 5000

Now restart the daemon and verify it restarted properly::

  # systemctl restart ttbd@production
  # journalctl -eu ttbd@production

As well, ensure the server's firewall allows the given ports to be
accessible. In Fedora 25::

  # dnf install -y firewall-config
  $ firewall-config

In the current firewall zone, add in *Ports* a range *4999-5001*, type
TCP.

Now select in the menu *Options* > *Runtime to permanent* to ensure
the changes are permanent and next time the server restarts they are
applied.


Increasing the verbosity of the server
--------------------------------------

When debugging issues with the server, you might have to increase its
verbosity; for that, more *-v* have to be given to the command
line. For that, edit ``/etc/systemd/system/ttbd@.service`` to add more
``-v`` to the ``ExecStart`` line.

Reread *systemd*'s configuration and restart the server::

  # systemctl daemon-reload
  # systemctl restart ttbd@production


Remember to toggle it back to the default ``-vv``--it gets chatty.

.. _manual_install:

Manual installation of TCF from source
======================================

Creation and setup of user *ttbd*
---------------------------------

The *ttbd* user is used to store TCF's software and files, and the
*ttbd* group to give normal user access to said files.

To create it (if not yet created)::

  # useradd -G kvm ttbd

Allow members of group *ttbd* access to *ttbd*\'s home so they can
write files needed for the deployment in there; never shall need to
login as the *ttbd* user::

  # chmod g+ws ~ttbd

Allow other users access to *ttbd*\'s files::

  # usermod -aG ttbd USER1 USER2 ….  # Make USERs members of ttbdgroup

Install required software
-------------------------

Run::

  # dnf install -y openocd make gcc-c++ python-ldap pyserial \
    python-requests git python-werkzeug python-tornado python-flask \
    python-flask-login python-flask-principal pyusb python-pexpect \
    pyOpenSSL

to install software packages required by TCF's server:

- openocd is used to interact with targets
- gcc-c++ and make are used to build
- Git is a source control manager we’ll use to obtain TCF’s source
- python-ldap, pyserial and python-requests are Python libraries TCF relies on
- python-werkzeug, python-flask* and python-tornado are the HTTP
  server framework TTBD uses to serve data.
- pyusb is the library used to access USB devices from Python
- python-pexpect is a expect-like language implementation in Python


You might need to :ref:`install support packages
<install_support_pkgs>` that are not in distributions dependning on
what you want to run with TCF.

Remove conflicting packages
---------------------------

Remove *Modem Manager*, as it interferes with the serial ports::

  # dnf remove -y ModemManager

this won't be needed if you will only use QEMU devices.

Install TCF
-----------

Obtain the code

.. include:: 04-HOWTOs-LL-install-tcf.rst

.. _tcf_install_manual:

**Install the TCF client**

Follow the steps on the :ref:`quickstart <install_tcf_client>` to
install the client from source.

  $ cd tcf.git
  $ python setup.py install --user

.. note:: you will also need to install the `Zephyr SDK 0.9
          <https://www.zephyrproject.org/downloads/tools>`_ to
          ``/opt/zephyr-sdk-0.9.5`` if you want to build Zephyr OS
          apps and other dependencies:

          Fedora::

            # dnf install -y make python-requests python-ply cmake \
              PyYAML python2-junit_xml python2-jinja2

          Ubuntu::

            # apt-get install -y python-ply python-requests make \
              python-junit.xml python-jinja2

**Install the server**

Install requirements: sdnotify, a library to help TCF’s server TTBD
integrate with systemd::

  $ sudo pip install sdnotify

Now the server itself::

  $ cd tcf.git/ttbd
  $ sudo python setup.py install

Note the server needs configuration of SELinux, kernel credentials,
UIDs and GIDs for operation -- so running it off the RPM package can
get complicated.

.. _install_support_pkgs:

Manual installation of support packages
=======================================

These are dependencies needed when certain kind of test hardware is
going to be connected or certain OSes / testcases are to be used:

- Bossac: Arduino Due flasher: see :class:ttbl.images.bossac_c's
  documentation

- Arduino CLI: The Arduino CLI will be needed by the TCF client to
  build *.ino* files into appplications that can be flashed into targets
  for test and for flashing them. Follow the instructions in
  :class:ttbl.images.arduino_cli_c.

.. _xtensa_esp32:

- Xtensa ESP32: In order to build (TCF client) and deploy/flash (ttbd
  server) for ESP32 boards, you will need the *xtensa-esp32* SDK and the ESP-IDF
  libraries:

  - to only provide flashing support with *esptool.py*, follow the
    instructions in :class:ttbl.images.esptool_c.

  - to provide build support too, install the *xtensa-esp32 SDK*:

    1. Download from
       https://dl.espressif.com/dl/xtensa-esp32-elf-linux64-1.22.0-59.tar.gz

    2. Extract to */opt/xtensa-esp32-elf*::

         # tar xf xtensa-esp32-elf-linux64-1.22.0-59.tar.gz -C /opt

    3. Add to */etc/environment*::

         ESPRESSIF_TOOLCHAIN_PATH=/opt/xtensa-esp32-elf

- *ESP-IDF*: This is Xtensa's IOT framework that is used by Zephyr and others

  1. Clone to */opt/esp-idf.git*::

       $ rm -rf /opt/esp-idf.git
       $ git clone --recursive https://github.com/espressif/esp-idf.git /opt/esp-idf.git
       $ (cd /opt/esp-idf.git && git checkout -f $(ESP_IDF_REV))

  2. Add to */etc/environment*::

       ESP_IDF_PATH=/opt/esp-idf.git


.. _zephyr_sdk:

Zephyr SDK
----------

To build some Zephyr OS apps/testcases or to flash certain hardware,
you will need this SDK:

1. Download the Zephyr SDK from
   https://www.zephyrproject.org/downloads/tools

2. Install in */opt/zephyr-sdk-VERSION*::

     # chmod a+x zephyr-sdk-0.9.5-setup.run
     # ./zephyr-sdk-0.9.5-setup.run -- -y -d /opt/zephyr-sdk-0.9.5

3. (optional) Create a fast RPM with::

     $ fpm -n zephyr-sdk-0.9.5 -v 0.9.5 \
     >     --rpm-rpmbuild-define '_build_id_links alldebug' \
     >     -s dir -C / -t rpm opt/zephyr-sdk-0.9.5

   *_build_id_links alldebug* is needed to disable generation of build
   symlinks in */usr/lib/.build-id*. Because the SDK packs a lot of
   files that are similar/identical to those present in the system, it
   will conflict.



tunslip6
--------

*tunslip6* is used to create a SLIP interface for a QEMU virtual
machine and connecting it to a TAP interface. This code has been
floating around for different small OSes that also run in QEMU, so
there is a few versions.

The one we currently use is the one used by the Zephyr project at the
*net-tools* repository:

  http://github.com/zephyrproject-rtos/net-tools

which has added functionality to defer configuration to external
parties (*ttbd* in this case) and some strenghtening to deal with race
conditions.


1. Clone::

     $ git clone http://github.com/zephyrproject-rtos/net-tools

2. Build::

     $ cd net-tools
     $ make tunslip6
     # make install

3. (optional) Create a fast RPM with::

     $ install -m 0755 tunslip6 -D root/usr/bin/tunslip6
     $ fpm -n tunslip6 -v $(git describe --always) -s dir -C root -t rpm usr/bin


libcoap
-------

Use the following script to create the RPM::

.. code-block:: sh

   # Use absolute dirs, libtool needs it
   dir=$PWD/libcoap.git
   rootdir=$PWD/root-libcoap.git

   rm -rf $dir
   git clone --recursive -b dtls https://github.com/obgm/libcoap.git $dir

   rm -rf $rootdir
   mkdir -p $rootdir

   (cd $dir; ./autogen.sh)
   sed -i 's|prefix = @prefix@|prefix = $(DESTDIR)/@prefix@|g' $(find $dir/ext/tinydtls -iname Makefile.in)
   (cd $dir; ./configure --disable-shared --disable-documentation --prefix=/usr)
   make -C $dir all
   make -C $dir DESTDIR=$rootdir install
   rm -rf $rootdir/usr/share
   ver=${ver:-$(git -C $dir describe --tags)}
   fpm  -n libcoap -v $ver -s dir -t rpm -C $rootdir

Invoke as::

  $ ./mklibcoap.sh



Platform firmware / BIOS update procedures
==========================================


.. _fs2_serial_update:

Updating the serial number and / or description of a FTDI serial device
-----------------------------------------------------------------------

These devices are used in multiple USB to serial dongles and embedded
in a number of devices, for example:

- Flyswatter JTAGs, which come all with the same serial number
  (usually *FS20000*).

- standalone dongles

- MCU boards, embedded computers

These usually come as USB vendor ID 0x0403, product ID starting with
0x6NNN.

When there are multiple FTDI devices that have the same serial number,
the system needs to be able to tell them apart, so we can flash a new
serial number in them, which we usually make match the target name, or
whatever is needed.

.. warning:: this process should be done in a separate machine; if you
             do it in a server with multiple of these devices
             connected, the tool can't tell them apart and might flash
             the wrong device.

To flash a new serial number or descriptionusing ``ftdi_eeprom`` on
your laptop (`Windows utility
<https://www.ftdichip.com/Support/Utilities.htm#FT_PROG>`_)::

  $ sudo dnf install -y libftdi-devel
  $ cat > file.conf <<EOF
  vendor_id=0x0403
  product_id=0x6010
  serial="NEWSERIALNUMBER"
  use_serial=true
  EOF

Now plug the USB cable to your server or laptop, making sure it is the
only one and run, as super user::

  # ftdi_eeprom --flash-eeprom file.conf

Reconnect it to have the system read the new serial number / description.

Notes:

 - if you have the unit you are re-flashing connected to a USB
   power switching hub (like a YKush), make sure to power it on and to
   power off any other device that has a 0x0403/6010 USB vendor ID /
   product ID code, which you can find with::

     $ lsusb.py  | grep 0403:6010
       1-1.2.1      0403:6010 00  2.00  480MBit/s 0mA 2IFs (Acme Inc. Flyswatter2 Flyswatter2-galileo-04)

 - make *NEWSERIALNUMBER* shorter if you receive this error
   message::

     FTDI eeprom generator v0.17(c) Intra2net AG and the libftdi developers <opensource@intra2net.com (opensource%40intra2net.com)>
     FTDI read eeprom: 0
     EEPROM size: 128
     Sorry, the eeprom can only contain 128 bytes (100 bytes for your strings).
     You need to short your string by: -1 bytes
     FTDI close: 0

 - For **Flyswatter2** devices, add::

     product="Flyswatter2"

   to the configuration file so the product name is set to
   *Flyswatter2*, needed for OpenOCD to find the device.

.. _cp210x_serial_update:

Updating the serial number and / or description of a CP210x serial device
-------------------------------------------------------------------------

Some hardware use serial-to-USB converters based on the CP210x series
by `Silicon Labs <http://www.silabs.com/>`_.

If the serial number programed on it is not unique enough, it can be
programmed with the tool ``cp120x-program``, available from
http://cp210x-program.sourceforge.net/.

Once installed:

1. identify the device to operate with::

     $ lsusb | grep -i CP210x
     Bus 002 Device 085: ID 10c4:ea60 Cygnal Integrated Products, Inc. CP210x UART Bridge / myAVR mySmartUSB light

   .. note:: your device might show differnt vendor or product ID and
             strings, in such case, adjust your grepping.

2. take the bus and device numbers (`002/085` in the example) and feed
   it to the `cp219x-program` tool with the new serial number you
   want::

     # cp210x-program -m 002/085 -w --set-serial-number "NEWSERIALNUMBER"

   it is always a good idea to set as new serial number the name of
   the target it is going to be assigned to.

3. Reconnect the device and verify the new serial number is set with
   ``lsusb.py``::

     $ lsusb.py -ciu
     ...
       2-2.4          10c4:ea60 00  1.10   12MBit/s 100mA 1IF  (Silicon Labs CP2102 USB to UART Bridge Controller esp32-39)
         2-2.4:1.0      (IF) ff:00:00 2EPs (Vendor Specific Class) cp210x ttyUSB0
     ..

   in this case, we set *esp32-39* as new serial number, which is
   displayed at the end of the line.


.. _a101_fw_upgrade:

Updating the firmware in an Arduino101 to factory settings
----------------------------------------------------------

This is needed to operate with Zephyr OS > v1.5.0-349-gecf96d2, which
dropped support for the older Arduino101 Zephyr boot ROM.

- Download from https://software.intel.com/en-us/node/675552 the
  package ``arduino101-factory_recovery-flashpack.tar.bz2`` and
  decompress to your home directory::

    $ cd
    $ tar xf LOCATION/arduino101-factory_recovery-flashpack.tar.bz2

- Ensure your TTBD server is >= v0.10 (dated 9/21/16 or later)

- Disable you Arduino101 target (to avoid it being used by other
  automated runs) and acquire it::

    $ tcf disable arduino101-NN
    $ tcf acquire arduino101-NN

- Flash the new Boot ROM and bootloader::

    $ tcf images-upload-set arduino101-NN \
      rom:$HOME/arduino101-factory_recovery-flashpack/images/firmware/FSRom.bin \
      bootloader:$HOME/arduino101-factory_recovery-flashpack/images/firmware/bootloader_quark.bin

- Release the target and enable it::

    $ tcf release arduino101-NN
    $ tcf enable arduino101-NN

- Test with::

    $ cd LOCATION/OF/ZEPHYR/KERNEL
    $ export ZEPHYR_BASE=$PWD
    $ tcf run -v -t arduino101-NN samples/hello_world


Updating the firmware in an Quark C1000 reference boards
--------------------------------------------------------

This updates to the QSMI v1.3 bootrom support, needed to operate with
Zephyr OS > v1.5.0, which dropps support older ROMs.

- Download from https://github.com/quark-mcu/qmsi/releases/tag/v1.3.0 the
  file ``quark_se_rom-v1.3.0.bin`` to your home directory::

    $ wget https://github.com/quark-mcu/qmsi/releases/download/v1.3.0/quark_se_rom.bin \
        -O ~/quark_se_rom-v1.3.0.bin

- Ensure your TTBD server is >= v0.10 (dated 11/01/16 or later)

- Disable you Quark C1000 target (to avoid it being used by other
  automated runs), maybe wait for no still-running jobs are using it
  (use `tcf list -v qc1000-NN` to see if it is acquired by anyone)::

    $ tcf disable qc1000-NN

For the actual flashing process, there is a list of steps that have to
be performed that are needed to wipe the flash and reset the board in
such a way that it puts it in a receptive state. This implies running
specific OpenOCD commands and modifying the way the OpenOCD driver
operates on the board to maintain those settings.

1. Use the script `tcf-qc1000-fw-upload.sh TARGETNAME FWFILE` to
   update the Boot ROM::

     $ tcf-qc1000-fw-upload.sh qc1000-NN $HOME/quark_se_rom.bin

   In case of failure, retry one or two times, as some commands get
   stuck. If after the retries it still fails, it might be time to try
   remediation steps as described below.

2. Verify operation with running a Zephyr test case::

     $ cd LOCATION/OF/ZEPHYR/KERNEL
     $ export ZEPHYR_BASE=$PWD
     $ tcf run -vat qc1000-NN  /usr/share/tcf/examples/test_healtcheck.py

   Testcase should `PASS`. Note the `-a`, so TCF can use a disabled
   target. If they fail and `tcf console-read qc1000-NN` reports
   garbage instead of some ASCII text, it is possible board timings
   are messed up. Go back to flashing the Boot ROM and maybe use the
   remediation steps described below.

3. Re-enable the target::

    $ tcf enable qc1000-NN

The process is thus concluced

Remediation steps
^^^^^^^^^^^^^^^^^

In some situations it has been seen that the stock OpenOCD version
distributed with the Zephyr SDK or most system cannot flash properly
the QC1000.

In said case, we can try with the ISSM version of OpenOCD:

1. obtain the ISSM toolchain package for Linux from
   https://software.intel.com/en-us/articles/issm-toolchain-only-download

2. Install in your system in path opt with::

     # tar xf PATH/TO/issm-toolchain-linux-2016-05-12-pub.tar.gz  -C /opt

3. Disable ISSM's OpenOCD using a TCL port, otherwise the TCF server,
   TTBD, will not be able to talk to it::

     # sed -i 's/tcl_port/#tcl_port/' \
       /opt/issm-toolchain-linux-2016-05-12/tools/debugger/openocd/scripts/board/quark*.cfg

4. Alter the TCF's configuration of each QC1000 target to be updated
   so it uses the OpenOCD from ISSM; in file
   `/etc/ttbd-production/conf_FILE.py`:

   .. code-block:: python

      quark_c1000_add(
          "TARGETNAME",
          serial_number = "SERIALNUMBER",
          ykush_serial = "YKUSHHUBSERIALNUMBER",
          ykush_port_board = YKUSHHUBPORT,
          openocd_path = "/opt/issm-toolchain-linux-2016-05-12/tools/debugger/openocd/bin/openocd",
          openocd_scripts = "/opt/issm-toolchain-linux-2016-05-12/tools/debugger/openocd/scripts")

5. Restart the server::

     # systemctl restart ttbd@production

6. Run a healthcheck on the target::

     $ tcf run -vat TARGETNAME  /usr/share/tcf/examples/test_healtcheck.py

   In case of trouble, diagnose by looking at the :ref:`journal
   <systemd_tips_diagnosis>`::

     $ journalctl -aeu ttbd@production

6. Retry the firmware update script

7. Upon success, revert the configuration change and restart the server

.. _fw_update_d2000:

Updating the firmware in an Quark D2000 reference boards
--------------------------------------------------------

This is needed to operate with Zephyr OS.

- Download from
  https://github.com/quark-mcu/qm-bootloader/releases/tag/v1.3.0 the
  file ``quark_d2000_rom.bin`` to your home directory::

    $ wget https://github.com/quark-mcu/qm-bootloader/releases/download/v1.4.0/quark_d2000_rom_fm_hmac.bin

- Ensure your TTBD server is >= v0.10 (dated 9/21/16 or later)

- Disable you Quark D2000 target (to avoid it being used by other
  automated runs) and acquire it::

    $ tcf disable qd2000-NN
    $ tcf acquire qd2000-NN

- Flash the new Boot ROM and bootloader::

    $ tcf images-upload-set qd2000-NN rom:quark_d2000_rom_fm_hmac.bin

- Release the target::

    $ tcf release qd2000-NN

- Verify operation with running a Zephyr test case::

     $ export ZEPHYR_BASE=LOCATION/OF/ZEPHYR/KERNEL
     $ tcf run -vat qd2000-NN  /usr/share/tcf/examples/test_healtcheck.py

   Testcase should `PASS`. Note the `-a`, so TCF can use a disabled
   target. If they fail and `tcf console-read qc1000-NN` reports
   garbage instead of some ASCII text, it is possible board timings
   are messed up. Go back to flashing the Boot ROM and maybe use the
   remediation steps described below.

- Enable the target::

    $ tcf enable qd2000-NN

Updating the FPGA image in Synopsys EMSK boards
-----------------------------------------------

1. You will need a Synopsys account; `register
   <https://www.synopsys.com/cgi-bin/dwarcsw/req1.cgi>`_ and wait for
   them to accept you

2. Use this account to `download their newest firmware
   <https://www.synopsys.com/cgi-bin/dwarcsw/arcemsk/menu.cgi>`_. Currently
   set to v2.2.

3. Now download the `Lab Tools 14.7` or newer (You may have to create
   a Xilinx account `here
   <https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/design-tools.html>`_
   to access this download)

   If you need installation instruction you can find them here under
   Appendix: C (page 86) of
   https://www.embarc.org/pdf/ARC_EM_Starter_Kit_UserGuide.pdf
   (important note, when running this it seems you have to use Windows
   and the Impact 32 bit version. The 64 bit version seems to fail out
   on certain steps you need to use).

4. Now just go through the flashing instructions located on page 93
   towards the bottom, called SPI Flash-Programming Sequence
   https://www.embarc.org/pdf/ARC_EM_Starter_Kit_UserGuide.pdf

   If you need another resource the synopsys instructions can be found
   here under (page 86) Appendix: C for installing the tools, and
   (page 93 bottom) under SPI Flash-Programming Sequence.
   https://www.embarc.org/pdf/ARC_EM_Starter_Kit_UserGuide.pdf

.. note::
   the switch configuration we are currently using is ARC_EM9D for the 9D model.

   Here is the switch configuration for SW1 (bit 1 is switch one; bit 2 is switch 2)

   ===== ==== =============
   Bit 1 Bit2 Configuration
   ----- ---- -------------
   OFF   OFF  ARC_EM7D
   ON    OFF  ARC_EM9D
   OFF   ON   ARC_EM11D
   ON    ON   Reserved
   ===== ==== =============

.. _pos_image_creation:

Creating images for the Provisioning OS
=======================================

For provisioning using :mod:`Provisioning OS <tcfl.pos>`, images have
to be extracted and installed in the server (or an rsync server as
described in the :ref:`setup guide <ttbd_pos_deploying_images>`).

The images for provisioning are a flat root filesystem that is
rsync'ed by with :mod:`tcfl.pos`.

Extracting them can be a little bit tricky, but there are different
methodologies that allow automating the process.

Linux Live images
-----------------

When images are Linux Live filesystems, they can usually be extracted
easily, using the :download:`/usr/share/tcf/tcf-image-setup.sh
<../ttbd/pos/tcf-image-setup.sh>` script, which understands most Live
images.

See the :ref:`examples <ttbd_pos_deploying_images>`.

.. _kickstart_install:

Linux Kickstart images using QEMU
---------------------------------

Linux distributions that can be installed via kickstart can use
:download:`/usr/share/tcf/kickstart-install.sh
<../ttbd/pos/kickstart-install.sh>`, which uses QEMU to run the
installation with a built in kickstart, creating a qcow2 file image
that then *tcf-image-setup.sh* can install.

*kickstart-install.sh* creates a kickstart file in a drive that is
passed to the virtual machine, so there is no need for PXE servers. It
extracts the kernel and initrd from the ISO image as well.

See the :ref:`examples <ttbd_pos_deploying_images>`.

Manual image extraction using QEMU
----------------------------------

1. create a 20G virtual disk::

     $ qemu-img create -f qcow2 ubuntu-18.10.qcow2 20G
     $ qemu-img create -f qcow2 Fedora-Workstation-29.qcow2 20G

2. Install using QEMU all with default options (click next). Power
   off the machine when done instead of power cycling::

     $ qemu-system-x86_64 --enable-kvm -m 2048 -hdah ubuntu-18.10.qcow2 -cdrom ubuntu-18.10-desktop-amd64.iso
     $ qemu-system-x86_64 --enable-kvm -m 2048 -hda Fedora-Workstation-29.qcow2 -cdrom Fedora-Workstation-Live-x86_64-29-1.2.iso

   Key thing here is to make sure everything is contained in a
   single partition (first partition).

   For Ubuntu 18.10:

     - select install
     - select any language and keyboard layout
     - Normal installation
     - Erase disk and install Ubuntu
     - Create a user 'Test User', with any password
     - when asked to restart, restart, but close QEMU before it
       actually starts again

   For Fedora:

     - turn off networking
     - select install to hard drive
     - select english keyboard
     - select installation destination, "CUSTOM" storage configuration
       > DONE
     - Select Standard partition
     - Click on + to add a partition, mount it on /, 20G in size
       (the system later will add boot and swap, we only want what goes
       in the root partition).
       Select DONE
     - Click BEGIN INSTALLATION
     - Click QUIT when done
     - Power off the VM

3. Create image::

     $ /usr/share/tcf/tcf-iamge-setup.sh ubuntu:desktop:18.10::x86_64 ubuntu-18.10.qcow2
