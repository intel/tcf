
.. _tcf_guide_configuration:
.. _tcf_configuring:

Configuring the TCF client
==========================

The client looks for configuration files named `conf_*.py` in the
following directories:

- `.tcf/` subdirectory of the current working directory
- `~/.tcf/`, a per-user configuration directory
- `/etc/tcf/`, a system wide configuration directory

The `conf_*.py` files are parsed in alphabetical order, written in
plain Python code, so you can do anything, even extend TCF from
them. The module :mod:`tcfl.config` provides access to functions to
set TCF's configuration.

.. _tcf_config_servers:

Configuring access to *ttbd* servers
------------------------------------

Each server you have access to is described by its URL
`https://HOSTNAME.DOMAIN:PORT`, which can be passed to ``tcf --url URL
<COMMAND>`` or more conveniently, set in a configuration file with
:func:`tcfl.config.url_add`:

.. code-block:: python

   tcfl.config.url_add('https://HOSTNAME.DOMAIN:PORT', ssl_ignore = True)

optionally an argument *aka = NAME* can be added to add a nickname for
the server (which defaults to *HOSTNAME*).

In multiple-instance deployments (infrastructure/production/staging),
most users only need access to the production server, so the following
AKAs are recommended:

- *HOSTNAME*: production
- *HOSTNAMEi*: infrastructure
- *HOSTNAMEs*: staging

.. _tcf_configure_zephyr:

Configuring for Zephyr OS development
-------------------------------------

.. note:: the *tcf-zephyr* RPM already provides these settings for
          *ZEPHYR_SDK_INSTALL_DIR*, *ZEPHYR_TOOLCHAIN_VARIANT* (and
          *ZEPHYR_GCC_VARIANT* for < v1.11 versions of Zephyr) in
          `/etc/tcf/config_zephyr.py`, as well as an RPM installation
          of the Zephyr SDK.

To work with Zephyr OS applications without having to set the
environment, a TCF configuration file `conf_zephyr.py` can be created
with these settings:

.. code-block:: python

  # Set Zephyr's build environment (use .setdefault() to inherit
  # existing values if present)
  import os
  os.environ.setdefault('ZEPHYR_TOOLCHAIN_VARIANT', 'zephyr')
  os.environ.setdefault('ZEPHYR_SDK_INSTALL_DIR',
                        os.path.expanduser('/opt/zephyr-sdk-0.9.5'))

.. _tcf_configure_sketch:

Configuring for Arduino Sketch development
------------------------------------------

.. note:: installing the *tcf-sketch* RPM package will bring in
          dependencies to build Arduino sketches that can be deployed
          in MCUs (such as Arduino Builder v1.6.13).

The corresponding board support packages need to be manually setup
into the system using the Arduino IDE in a location that all users who
are going to need it can access:

1. As your user, start the Arduino IDE and install the support
   packages for the boards you will build for; in this case we only do
   the Arduino Due and the Arduino 101:

   - In the menu, select `Tools > Board (ANY) > Boards Manager`
   - Search for *Arduino Due*, *Intel Curie Boards* (for *Arduino
     101*) or any other boards you need support for
   - Install

2. Packages appear in `~/.arduino15/packages`

   Any other user that needs access to those board definitions has to
   repeat those steps or copy those files. For example, for an
   autobuilder such as Jenkins, those files would have to be copied to
   the build slaves.

3. Ensure the targets are configured to expose Sketch information by
   declaring a tag:

   - `sketch_fqbn`: `sam:1.6.9:arduino_due_x_dbg` for Arduino Due

Other configuration settings
----------------------------

- Ignoring directory names when :func:`scanning for test cases
  <tcfl.tc.tc_c.dir_ignore_add_regex>`:

  .. code-block: python

     tcfl.tc.tc_dir_ignore_add_regex("^doc.*$")

  will tell the scanner to ignore any directory called *docANYTHING*
