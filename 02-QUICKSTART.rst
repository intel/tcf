.. _quickstart:

============
 Quickstart
============

.. _install_tcf_client:

.. include:: doc/02-client-setup-LL-00.rst

1. Install the client software from source; install Python2
   development support::

     $ sudo dnf install -y python2-devel python2-pip  # Fedora <= 30
     $ sudo yum install -y python2-devel python2-pip  # CentOS/RHEL 7
     $ sudo apt install -y python-dev python-pip      # Ubuntu <= 18

   (TCF is still using python2, hence the limitation to older ditros
   that still support it, we are in the process of porting to Python3;
   see branch *pyv3*).
     
   now clone install Python dependencies and install the TCF client

   .. include:: doc/02-client-setup-LL-02.rst

   (see :ref:`installation
   troubleshooting<tcf_client_install_troubleshooting>` for things
   that can go wrong)

   .. note:: For **Ubuntu** (mostly): ensure your PATH includes
             *$HOME/.local/bin*, where *install --user* puts things,
             by adding to *~/.bashrc*::
     
               $ echo 'test -z "${PATH##*$HOME/.local/bin*}" || export PATH=$PATH:$HOME/.local/bin' >> ~/.bashrc

             source bashrc to ensure the setting is there::

               $ source ~/.bashrc
               
   Other installation options:

   a. You can run *tcf* from the :ref:`source directory
      <tcf_run_from_source_tree>`

   b. You can run it under WSL (Windows Services for Linux), which
      first has to be :ref:`installed <setup_wsl>`
     
   .. include:: doc/02-client-setup-LL-01.rst

2. :ref:`Configure it <tcf_guide_configuration>`, access to remote HW
   servers, adding to `~/.tcf/conf_servers.py` or
   `/etc/tcf/conf_servers.py`::

     $ mkdir -p ~/.tcf
     $ vi ~/.tcf/conf_servers.py
   
   .. include:: doc/02-client-setup-LL-03.rst

   You can also :ref:`install a server <ttbd_guide_deployment>`, in
   your machine or another one.

3.

   .. include:: doc/02-client-setup-LL-04-login.rst

   Run *tcf login --help* for other login options.


     
4. (optional) to run Zephyr RTOS code and testcases, follow the
   :ref:`Zephyr guide <quickstart_zephyr>`

:ref:`Contributions <tcf_contributing>` welcome!

*Playing around with targets*
=============================

Once a server is configured and logged in, list with *tcf* which
targets it gives you acces to (this list is for the targets a default
:ref:`server install provides <ttbd_guide_install_default_config>`,
*qz*\* for Zephyr OS QEMU targets, *qlf*\* for Fedora Linux targets)::

  $ tcf list 
  local/nwa           !  local/qu06b            local/qz30a-x86        local/qz33b-arm        local/qz37a-riscv32
  local/nwb              local/qu07a            local/qz30b-x86        local/qz34a-nios2      local/qz37b-riscv32
  local/qu04a            local/qu07b            local/qz31a-x86        local/qz34b-nios2      local/qz38a-xtensa 
  local/qu04b            local/qu08a            local/qz31b-x86        local/qz35a-nios2      local/qz38b-xtensa 
  local/qu05a            local/qu08b            local/qz32a-arm        local/qz35b-nios2      local/qz39a-xtensa 
  local/qu05b            local/qu09a            local/qz32b-arm        local/qz36a-riscv32    local/qz39b-xtensa 
  local/qu06a            local/qu09b            local/qz33a-arm        local/qz36b-riscv32    local/qzarm-33a    
  ...

There are two test networks defined (*nwa* and *nwb*) and targets
assigned to each network. Thus, *qu09a* is a virtual implemented by
QEMU with UEFI BIOS target, on network *a* (*192.168.97/0/24*) with IP
address *192.168.97.9*

Feel free to add `-v`\s after *tcf* (to increase *tcf*`s verbosity)
or after the *list* command (to increase the amount of information for
each target).

Before doing most operations that can modify a target, you have to
acquire it::

  $ tcf acquire qu09a

*tcf* provides primitives to (see *tcf --help*) operate on the target:

 - power control: on, off, cycle, reset

 - debugging: reset/halt/resume CPUs, attach GDB, run openocd commands

 - read/write (serial) consoles

 - deploy/flash images, roms, etc

 - ...

these are available if the targets supports the interfaces for it,
which you can find by listing it with ``-vv``::

  $ tcf list -vv SOMETARGETNAME | grep interfaces
  interfaces[0]: images
  interfaces[1]: power
  interfaces[2]: console
  interfaces_names: images power console

by convention, commands to operate on interface *NAME* are called
*NAME-\** and the APIs to access it at the script level under Python
object *target.NAME.FUNCTION()*.
  
Targets can also support one or more BSPs. A BSP in a target is
something we can use to run code on. When targets support multiple
BSPs, then we can decide to run the target in different *BSP models*,
each model determining which BSPs are used of all the ones available.


At this point you can:

- :ref:`list what OS images are available <howto_pos_list_images>`

- :ref:`How can I quickly flash a Linux target <howto_pos_list_deploy>`

See many other :ref:`ready-to-run examples <examples_script>`.
