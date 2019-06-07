#! /usr/bin/python
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import codecs
import errno
import hashlib
import inspect
import logging
import math
import os
import re
import shutil
import subprocess

from . import commonl
from . import tc
import tcfl.app
import __main__


#: for each target type, an integer on how long we shall wait to
#: boot Zephyr
boot_delay = {}

class app_zephyr(tcfl.app.app_c):
    """
    Support for configuring, building, deploying and evaluating a Zephyr-OS
    application.

    To setup:

     - a toolchain capable of building Zephyr has to be installed in
       the system and the corresponding environment variables
       exported, such as:

       - `ZEPHYR_SDK_INSTALL_DIR` for the Zephyr SDK
       - `ISSM_INSTALLATION_PATH` for the Intel ISSM toolchain
       - `ESPRESSIF_TOOLCHAIN_PATH` for the Espress toolchain
       - `XTENSA_SDK` for the Xtensa SDK

     - environment variables set:

       - `ZEPHYR_TOOLCHAIN_VARIANT` (`ZEPHYR_GCC_VARIANT` before
         v1.11) pointing to the toolchain to use (*zephyr*, *issm*,
         *espressif*, *xcc*, etc...)
       - `ZEPHYR_BASE` pointing to the path where the Zephyr tree is located

       note these variables can be put in a :ref:`TCF configuration
       file <tcf_configure_zephyr>` or they can also be specified as
       options to *app_zephyr* (see below).

    Usage:

    - Declare in a target *app_zephyr* and point to the source tree
      and optionally, provide extra arguments to add to the Makefile
      invocation::

        @tcfl.tc.target("zephyr_board",
                        app_zephyr = 'path/to/app/source')
        class my_test(tc.tc_c):
            ...

      If extra makefile arguments are needed, a tuple that starts with
      the path and contains multiple strings can be used::

        @tcfl.tc.target("zephyr_board",
                        app_zephyr = (
                            'path/to/app/source',
                            'ZEPHYR_TOOLCHAIN_VARIANT=zephyr',
                            'ZEPHYR_BASE=some/path',
                            'OTHEREXTRAARGSTOZEPHYRMAKE'))
        class my_test(tc.tc_c):
            ...

      to build multiple BSPs of the same target::

        @tcfl.tc.target("type == 'arduino101'",
                        app_zephyr = {
                            'x86': (
                                'path/to/app/source/for/x86',
                                'ZEPHYR_TOOLCHAIN_VARIANT=zephyr',
                                'ZEPHYR_BASE=some/path',
                                 'OTHEREXTRAARGSTOZEPHYRMAKE'
                            ),
                            'arc': (
                                'path/to/app/source/for/arc',
                                'ZEPHYR_TOOLCHAIN_VARIANT=zephyr',
                                'ZEPHYR_BASE=some/path',
                                'OTHEREXTRAARGSTOZEPHYRMAKE'
                            )
                        })
        class my_test(tc.tc_c):
            ...

      furthermore, common options can be specified in
      *app_zephyr_options* (note this is just a string versus a
      tuple), so the previous example can be simplified as::

        @tcfl.tc.target("type == 'arduino101'",
                        app_zephyr = {
                            'x86': (
                                'path/to/app/source/for/x86',
                                'OTHER-X86-EXTRAS'
                            ),
                            'arc': (
                                'path/to/app/source/for/arc',
                                'OTHER-ARC-EXTRAS'
                            )
                        },
                        app_zephyr_options = \\
                          'ZEPHYR_TOOLCHAIN_VARIANT=zephyr' \\
                          'ZEPHYR_BASE=some/path' \\
                          'OTHER-COMMON-EXTRAS')
        class my_test(tc.tc_c):
            ...

    The test creator can set the attributes (in the test class or in
    the target object):

    - ``zephyr_filter``
    - ``zephyr_filter_origin`` (optional)

    to indicate a Zephyr Sanity Check style filter to apply before
    building, to be able to skip a test case if a logical expression
    on the Zephyr build configuration is not satisfied. Example:

    .. code-block:: python

       @tcfl.tc.target("zephyr_board", app_zephyr = ...)
       class my_test(tc.tc_c):
           zephyr_filter = "CONFIG_VALUE_X == 2000 and CONFIG_SOMETHING != 'foo'"
           zephyr_filter_origin = __file__

    """

    @staticmethod
    def configure(testcase, target, app_src):
        target.kws_required_verify([ 'zephyr_board', 'zephyr_kernelname' ])
        # Adds Zephyr's build zephyr_* vars to the target's keywords
        testcase_file = inspect.getfile(type(testcase))
        zephyr_extra_args = testcase._targets[target.want_name]['kws'].get(
            'app_zephyr_options', "") + " "
        if len(app_src) > 1:
            zephyr_extra_args += " ".join(app_src[1:])
        # Add tags to the target
        srcdir = tcfl.app.get_real_srcdir(testcase_file, app_src[0])
        # Decide if this is cmake style (Zephyr almost 1.10) or not
        # and store it in the keywords, as we'll use in different
        # places to make decissions on if we can run or not.
        ZEPHYR_BASE = os.environ.get('ZEPHYR_BASE',
                                     "__ZEPHYR_BASE_not_defined__")
        if os.path.exists(os.path.join(ZEPHYR_BASE, "CMakeLists.txt")):
            if not os.path.exists(os.path.join(srcdir, "CMakeLists.txt")):
                raise tc.error_e(
                    "%s: Zephyr App is not cmake based, but Zephyr @%s is"
                    % (srcdir, ZEPHYR_BASE))
            is_cmake = True
            # cmake needs the extra args in -DXXX format .. sighs this
            # will blow up at some point, because we are assuming that
            # all extra args passed are VAR=VALUE
            zephyr_extra_args = " ".join("-D" + arg
                                         for arg in zephyr_extra_args.split())
        else:
            if os.path.exists(os.path.join(srcdir, "CMakeLists.txt")):
                raise tc.error_e(
                    "%s: Zephyr App is cmake based, but Zephyr @%s is not"
                    % (srcdir, ZEPHYR_BASE))
            is_cmake = False
        target.kws_set(
            {
                'zephyr_srcdir': srcdir,
                # Place all the build output in the temp directory, to
                # avoid polluting the source directories
                'zephyr_objdir': os.path.join(
                    testcase.tmpdir,
                    "outdir-%(tc_hash)s-%(tg_hash)s-%(zephyr_board)s"
                    % target.kws),
                'zephyr_is_cmake': is_cmake,
            },
            bsp = target.bsp)

        if not target.bsp in target.bsps_stub:
            # Set arguments only for this BSP, not for all of them,
            # and only if we are not building a stub. Note we get the
            # options from app_zephyr_options + OPT1 + OPT2... added
            # after app_src in 'app_zephyr = (SRC, OPT1, OPT2...)
            target.kw_set('zephyr_extra_args', zephyr_extra_args,
                          bsp = target.bsp)
        else:
            # When we are building stubs, we do not take the options
            # from the project itself -- stub needs no options
            target.kw_set('zephyr_extra_args', "", bsp = target.bsp)


        # Do we introduce boot configuration or not?
        if not testcase.build_only:
            # If a testcase is build only, it won't run in HW so we
            # don't need to introduce a boot delay to allow serial
            # ports to be ready.
            # This is needed because build only testcases might be
            # disabling options that are needed to implement boot
            # delays, like clock stuff
            global boot_delay
            _boot_delay = boot_delay.get(target.type, 1000)
            if not target.bsp in target.bsps_stub:
                target.zephyr.config_file_write(
                    "500_boot_config",
                    """\
# Introduce a boot delay of 1s to make sure the system
# has had time to setup the serial ports and start recording
# from them
CONFIG_BOOT_BANNER=y
CONFIG_BOOT_DELAY=%d
""" % _boot_delay,
                    bsp = target.bsp)
            else:
                target.zephyr.config_file_write(
                    "500_boot_config",
                    """\
# Stubs be quiet and don't delay, ready ASAP
CONFIG_BOOT_BANNER=n
CONFIG_BOOT_DELAY=0
""",
                    bsp = target.bsp)

        # Add stubs for other BSPs in this board if there are none
        # We will run this each time we go for a BSP build, but it is fine
        for bsp_stub in list(target.bsps_stub.keys()):
            target.stub_app_add(
                bsp_stub, app_zephyr,
                os.path.join(ZEPHYR_BASE, 'tests', 'booting', 'stub'))

    @staticmethod
    def build(testcase, target, app_src):
        """
        Build a Zephyr App whichever active BSP is active on a target
        """
        # Yes, using Python-shcript so the compile output shows the
        # exact steps we followed to build that can be run by a
        # human--would be easier to run os.mkdir() and stuff, but not
        # as clear to the would-be-debugger human trying to verify what
        # happened

        # Create destination directory
        # FIXME: add notes from defaults.tc on why things are done like we
        # do them
        target.shcmd_local(
            'mkdir -p %(zephyr_objdir)s; '
            'rm -f %(zephyr_objdir)s/.config')

        # FIXME: this check should just be if the board is a Quark SE based
        if target.kws['zephyr_board'] in [ 'arduino_101',
                                           'quark_se_c1000_devboard' ]:
            # On Quark SE, when running the x86 core only we need to make sure
            # the kernel doesn't wait for the ARC to initialize.
            if target.bsp_model == 'x86':
                target.zephyr.config_file_write(
                    '500_bsp_arc_off',
                    "CONFIG_ARC_INIT=n\n",
                    bsp = 'x86')
            elif target.bsp_model == 'arc':
                target.zephyr.config_file_write(
                    '500_bsp_arc_on', "CONFIG_ARC_INIT=y\n",
                    bsp = 'x86')
        if target.kws['zephyr_board'] in [ 'arduino_101_sss',
                                           'quark_se_c1000_ss_devboard']:
            # On Quark SE, when running the arc core only, we redirect
            # console ouput to UART1, so we see the ARC doing stuff;
            # the stub in x86 will let it pass.
            if target.bsp_model == 'arc':
                target.zephyr.config_file_write(
                    '500_bsp_arc_console',
                    'CONFIG_UART_CONSOLE_ON_DEV_NAME="UART_1"\n',
                    bsp = 'arc')

        # How much paralellism?
        target.kw_set('make_j', tcfl.app.make_j_guess(), bsp = target.bsp)
        # Set MAKE to mirror environ's, in case we are being called
        # under a Makefile, so we get the right setting for jobserver
        target.kw_set('MAKE', os.environ.get('MAKE', 'make'), bsp = target.bsp)
        # Newer Zephyr SDKs provide prebuilt host tools we can use; if
        # we don't have access to it, then we re-build them
        if target.kws['zephyr_is_cmake']:
            zephyr_sdk_install_dir = os.environ.get('ZEPHYR_SDK_INSTALL_DIR', None)
            if zephyr_sdk_install_dir == None:
                raise tcfl.tc.blocked_e(
                    "Need ZEPHYR_SDK_INSTALL_DIR exported pointing to "
                    "Zephyr SDK location, to obtain kconfig tool")
            path = os.path.join(zephyr_sdk_install_dir,
                                "sysroots/x86_64-pokysdk-linux/usr/bin")
            if not os.path.exists(path):
                raise tcfl.tc.blocked_e(
                    "Can't find kconfig tool in ZEPHYR_SDK_INSTALL_DIR (%s)"
                    % zephyr_sdk_install_dir)
            # Generate initial config, so we can filter on it
            target.shcmd_local(
                'cmake'
                ' -DBOARD=%(zephyr_board)s -DARCH=%(bsp)s'
                ' -DEXTRA_CPPFLAGS="-DTC_RUNID=%(runid)s:%(tg_hash)s"'
                ' -DEXTRA_CFLAGS="-Werror -Wno-error=deprecated-declarations"'
                ' -DEXTRA_AFLAGS=-Wa,--fatal-warnings'
                ' -DEXTRA_LDFLAGS=-Wl,--fatal-warnings'
                ' %(zephyr_extra_args)s'
                ' -B"%(zephyr_objdir)s" -H"%(zephyr_srcdir)s"')
            target.shcmd_local(
                '%(MAKE)s -C %(zephyr_objdir)s'
                ' config-sanitycheck')
        else:
            target.shcmd_local(
                '%(MAKE)s -C %(zephyr_srcdir)s/'
                ' EXTRA_CFLAGS="-Werror -Wno-error=deprecated-declarations"'
                ' KCPPFLAGS=-DTC_RUNID=%(runid)s:%(tg_hash)s'
                ' BOARD=%(zephyr_board)s ARCH=%(bsp)s %(zephyr_extra_args)s'
                ' O=%(zephyr_objdir)s initconfig')

        # If we have a filter and we are not building a stub, filter
        # for config options, which define the method). Will
        # raise an skip exception if it doesn't have to be run.
        # Use getattr(), as this might be used in TCs not necessarily
        # defined after Zephyr's Sanity Check model. Try to get first
        # from the target, then from the testcase
        _filter = getattr(target, "zephyr_filter",
                          getattr(testcase, "zephyr_filter", None))
        _filter_origin = getattr(target, "zephyr_filter_origin",
                                 getattr(testcase, "zephyr_filter_origin",
                                         None))
        if _filter and not target.bsp in target.bsps_stub:
            target.zephyr.check_filter(
                target.kws['zephyr_objdir'],
                # ARCH is TCF's BSP
                target.kws.get('bsp', "ARCH_N/A"),
                # PLATFORM is TCF's BOARD -- which is pulled in from the
                target.kws.get('zephyr_board', 'BOARD_N/A'),
                _filter, _filter_origin
            )

        # Explicitly say which BSP to work with, so when building a
        # stub we don't get the config file from the non-stub BSPs
        config = target.zephyr.config_file_read(bsp = target.bsp)
        # unicode -> so weird chars don't make us panic
        kernelname = str(config['CONFIG_KERNEL_BIN_NAME'])
        # Build the kernel
        if target.kws['zephyr_is_cmake']:
            target.shcmd_local(
                '%(MAKE)s -C %(zephyr_objdir)s')
            symbols = subprocess.check_output([
                'nm',
                os.path.join(
                    target.kws['zephyr_objdir'],
                    "zephyr",
                    kernelname + ".elf")
                ])
        else:
            target.shcmd_local(
                '%(MAKE)s -C %(zephyr_srcdir)s'
                ' EXTRA_CFLAGS="-Werror -Wno-error=deprecated-declarations"'
                ' KCPPFLAGS=-DTC_RUNID=%(runid)s:%(tg_hash)s'
                ' BOARD=%(zephyr_board)s ARCH=%(bsp)s %(zephyr_extra_args)s'
                ' O=%(zephyr_objdir)s')
            symbols = subprocess.check_output([
                'nm',
                os.path.join(
                    target.kws['zephyr_objdir'],
                    kernelname + ".elf")
            ])
        for line in symbols.splitlines():
            token = line.split()
            if len(token) == 3 and token[2] == '__start':
                target.kw_set('__start', '0x' + token[0])
                break
        else:
            raise tcfl.tc.error_e("Cannot find Zephyr's __start!",
                                  { "symbols": symbols } )

    @staticmethod
    def deploy(images, testcase, target, app_src):
        if target.kws['zephyr_is_cmake']:
            images.add((
                'kernel-%(bsp)s' % target.kws,
                '%(zephyr_objdir)s/zephyr/%(zephyr_kernelname)s' % target.kws))
        else:
            images.add((
                'kernel-%(bsp)s' % target.kws,
                '%(zephyr_objdir)s/%(zephyr_kernelname)s' % target.kws))

    @staticmethod
    def setup(testcase, target, app_src):
        target.report_info("setting up", dlevel = 1)
        console = target.kws.get('console', None)
        if console == "":
            console = None
        ignore_faults_value, ignore_faults_origin = \
            testcase.tag_get('ignore_faults', False)
        if ignore_faults_value == True:
            target.report_info("Will not catch Zephyr kernel fault messages "
                               "as errors per tag ignore_faults @%s"
                               % ignore_faults_origin, dlevel = 3)
        elif ignore_faults_value == False:
            target.report_info("Will catch Zephyr kernel fault messages as "
                               "errors per tag ignore_faults @%s"
                               % ignore_faults_origin, dlevel = 3)
            faults = [
                "BUS FAULT",
                "CPU Page Fault",
                "[Ff]atal fault in",
                "FATAL EXCEPTION",
                "Kernel OOPS",
                "Kernel Panic",
                "MPU FAULT",
                "USAGE FAULT",
                "Unknown Fatal Error",
            ]

            target.on_console_rx(
                re.compile("(" + "|".join(faults) + ")"),
                console = console, timeout = False, result = "error")
        else:
            raise tcfl.tc.blocked_e(
                "Unsupported value for tag 'ignore_faults' "
                " @%s: only boolean True or False supported"
                % ignore_faults_origin)
        if getattr(testcase, "sanity_check", False) == True:
            target.on_console_rx("PROJECT EXECUTION FAILED",
                                 console = console,
                                 timeout = False, result = "fail")

    @staticmethod
    def clean(testcase, target, app_src):
        # Note we remove with a shell command, so it shows what we do
        # that an operator could repeat
        # Note also we don't use the %(board)s substitution; at this
        # point, we might not even have it, because it is BSP specific
        # --s o we clean everything related to this testcase, that is
        # represented by %(tg_hash) and includes the stubs at
        # %(zephyr_srcdir)s/outdir-%(tg_hash)s-stub-x86-%(type)s.
        if 'zephyr_objdir' in target.kws:
            # Only if configure has defined this
            target.shcmd_local('rm -rf %(zephyr_objdir)s')


class zephyr(tc.target_extension_c):
    """
    Extension to :py:class:`tcfl.tc.target_c` to add Zephyr specific
    APIs; this extension is activated *only* if any BSP in the target
    is to be loaded with Zephyr.
    """

    def __init__(self, target):
        # We only do this if any of the BSPs of the BSP-Model in this
        # target has been set to use Zephyr
        self.bsps = []
        for bsp in target.bsps:
            app = target.app_get(bsp, noraise = True)
            if app == app_zephyr:
                self.bsps.append(bsp)
        if not self.bsps:
            raise self.unneeded

    @staticmethod
    def sdk_keys(arch, variant):
        """
        Figure out the architecture, calling convention and SDK
        prefixes for this target's current BSP.
        """
        # FIXME: validate the format of the table
        # Translate Zephyr's concept/name architecture / calling
        # convention and SDK location to something the SDK
        # understands.
        assert isinstance(variant, str) or variant == "", (
            "SDK variant not defined (usually from the environment "
            "variable ZEPHYR_TOOLCHAIN_VARIANT); "
            "app_zephyr needs that to build Zephyr applications. "
            "Please set on environment or in a configuration file "
            "{/etc/tcf,~/.tcf,.tcf}/conf_*.py")
        assert isinstance(arch, str)

        # This translation dictionary has to be defined in a config
        # file in {/etc/tcf,~/.tcf,.tcf}/conf_*.py; the initial
        # version is set in zephyr/conf_zephyr.py; because we parse it
        # into the __main__ namespace, that's how we have to access it.
        if not hasattr(__main__, 'zephyr_sdks'):
            raise tcfl.tc.blocked_e(
                "MISSING CONFIG? Please define in "
                "{/etc/tcf,~/.tcf,.tcf}/conf_*.py the "
                "`zephyr_sdks` configuration dictionary to allows the "
                "`app_zephyr` application builder to understand how the "
                "SDK used to build Zephyr works.")
        # Syntatic sugar for pylint
        __main__.zephyr_sdks = getattr(__main__, 'zephyr_sdks')
        if not variant in __main__.zephyr_sdks:
            raise tcfl.tc.blocked_e(
                "Zephyr's variant (ZEPHYR_TOOLCHAIN_VARIANT) `%s` not known; "
                "Please ensure it is defined in the `zephyr_sdks` "
                "configuration dictionary in any config file "
                "{/etc/tcf,~/.tcf,.tcf}/conf_*.py."
                % variant)
        assert isinstance(__main__.zephyr_sdks[variant], dict), (
            "SDK information in `zephyr_sdks` for variant `%s` has "
            "to be a dictionary (currently a %s). Please ensure it "
            "is properly defined any config file "
            "{/etc/tcf,~/.tcf,.tcf}/conf_*.py."
            % (variant, type(__main__.zephyr_sdks[variant]).__name__))
        variant_table = __main__.zephyr_sdks[variant]

        # Get defaults (if any), or let them set as None
        sdk_arch = variant_table.get("default", {}).get("arch", None)
        sdk_call_conv = variant_table.get("default", {}).get("call_conv", None)
        sdk_prefix = variant_table.get("default", {}).get("prefix", None)

        # Now get settings for the architecture we are calling (the
        # architecture is in TCF terms, the bsp).
        sdk_arch = variant_table.get(arch, {}).get("arch", arch)
        sdk_call_conv = variant_table.get(arch, {}).get("call_conv",
                                                        sdk_call_conv)
        sdk_prefix = variant_table.get(arch, {}).get("prefix", sdk_prefix)
        sdk_prefix = sdk_prefix % dict(arch = sdk_arch,
                                       call_conv = sdk_call_conv)
        return sdk_arch, sdk_call_conv, sdk_prefix


    def _bsp_select(self, target, bsp):
        # Note we allow selecting a BSP that is not active in the
        # current model, in case we need to set things in there for
        # stubs
        if bsp == None:
            if len(self.bsps) > 1:
                # More than one BSP
                if target.bsp and target.bsp in target.bsps_all:
                    # There is an active BSP and it is one of the
                    # Zephyr ones, take that
                    bsp = target.bsp
                else:
                    raise ValueError(
                        "Need to specify a BSP to use as current " \
                        "model (%s) has multiple Zephyr BSPs in use " \
                        "(%s)" % (target.bsp_model, " ".join(target.bsps)))
            else:
                # We select the BSP that matches the model, not just
                # the first BSP -- by definition, if we are running in
                # a single BSP, the name of the BSP model has to match
                # the BSP's name.
                bsp = target.bsp_model
        else:
            assert bsp in target.bsps_all, \
                "selected BSP %s is none of the ones supported " \
                "by the target (%s)" % (bsp, " ".join(target.bsps_all))
        return bsp

    def config_file_read(self, name = None, bsp = None):
        """
        Open a config file and return its values as a dictionary

        :param str name: (optional) name of the configuration file,
          default to *%(zephyr_objdir)s/.config*.

        :param str bsp: (optional) BSP on which to operate; when the
          target is configured for a :term:`BSP model` which contains
          multiple Zephyr BSPs, you will need to specify which one to
          modify.

          This parameter can be omitted if only one BSP is available
          in the current BSP Model.

        :returns: dictionary keyed by CONFIG\_ name with its value.
        """
        target = self.target
        bsp = self._bsp_select(target, bsp)
        if name == None:
            outdir = target._kws_bsp[bsp]['zephyr_objdir']
            if target.kws['zephyr_is_cmake']:
                name = os.path.join(outdir, "zephyr", ".config")
            else:
                name = os.path.join(outdir, ".config")
        config = {}
        config_re = re.compile('(?P<key>CONFIG_[A-Z0-9_]+)[=](?P<value>.+)$')
        with codecs.open(name, "r", encoding = 'utf-8',
                         errors = 'ignore') as fp:
            for line in fp.readlines():
                m = config_re.match(line)
                if not m:
                    continue
                d = m.groupdict()
                value = d['value'].strip()
                # note strings will have "" wrapping them, which we want
                # to avoid.
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                config[d['key']] = value
        return config

    def config_file_write(self, name, data, bsp = None):
        """\
        Write an extra config file called *NAME*.conf in the Zephyr's
        App build directory.

        Note this takes care to only write it if the data is new or
        the file is unexistant, to avoid unnecesary rebuilds.

        :param str name: Name for the configuration file; this has to
          be a valid filename; *.conf* will be added by the function.

        :param str data: Data to include in the configuration file;
          this is (currently) valid kconfig data, which are lines of
          text with # acting as comment character; for example::

            CONFIG_UART_CONSOLE_ON_DEV_NAME="UART_1"

        :param str bsp: (optional) BSP on which to operate; when the
          target is configured for a :term:`BSP model` which contains
          multiple Zephyr BSPs, you will need to specify which one to
          modify.

          This parameter can be omitted if only one BSP is available
          in the current BSP Model.

        *Example*

        >>> if something:
        >>>     target.zephyr.conf_file_write("mytweaks",
        >>>                                   'CONFIG_SOMEVAR=1\\n'
        >>>                                   'CONFIG_ANOTHER="VALUE"\\n')
        """
        target = self.target
        bsp = self._bsp_select(target, bsp)

        # Ensure the config directory is there
        outdir = target._kws_bsp[bsp]['zephyr_objdir']
        try:
            os.makedirs(outdir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise RuntimeError("%s: Cannot create outdir directory: %s"
                                   % (outdir, e.message))

        # Now create a .new file
        if not name.endswith(".conf"):
            name += ".conf"
        existing_filename = os.path.join(outdir, name)
        new_filename = existing_filename + ".new"
        with codecs.open(new_filename, "w+", encoding = 'utf-8',
                         errors = 'ignore') as f:
            f.write("""\
# Config file automatically generated by TCF's:
#
#   %s
#
# because of instructions from
#
#   %s
#
# Do not edit by hand

""" % (commonl.origin_get(), commonl.origin_get(2)))
            f.write(data)
            # report the config file we wrote, so reproduction
            # instructions will carry it in the report file; we report
            # the data without the header to make it easier -- note we
            # use report_pass() [vs report_info()] as _info might get
            # filtered as too verbose info, where as pass is
            # information important for passing.
            target.report_pass("enabled Zephyr config file %s at %s"
                               % (name, outdir),
                               { 'config file': data })
        if not os.path.exists(existing_filename):
            shutil.move(new_filename, existing_filename)
        else:
            # Check if there are changes before updating it, to avoid
            # unnecesary rebuilds
            _new_hash = hashlib.sha256()
            new_hash = commonl.hash_file(_new_hash, new_filename)
            _old_hash = hashlib.sha256()
            old_hash = commonl.hash_file(_old_hash, existing_filename)
            if new_hash.digest() != old_hash.digest():
                shutil.move(new_filename, existing_filename)
            else:
                os.unlink(new_filename)

    def check_filter(self, _objdir, arch, board, _filter, origin = None):
        """
        This is going to be called by the App Builder's build function
        to evaluate if we need to filter out a build of a testcase. In
        any other case, it will be ignored.

        :param str objdir: name of the Zephyr's object directory
          where to find configuration files
        :param str arch: name of the architecture we are building
        :param str board: Zephyr's board we are building
        :param str _filter: Zephyr's sanity Check style filter
          expression
        :param str origin: where does this come from?
        """
        if not origin:
            origin = commonl.origin_get()

        if _filter == None or _filter == "":
            return

        self.target.report_info("filter: processing '%s' @%s"
                                % (_filter, origin), dlevel = 1)
        self.target.report_info("filter: reading defconfig", dlevel = 2)

        _defconfig = self.config_file_read()
        defconfig = {}
        for key, value in _defconfig.items():
            # The testcase.ini filter language doesn't prefix the
            # CONFIG_ stuff, so we are going to strip it with [7:]
            if key.startswith("CONFIG_"):
                defconfig[key[7:]] = value
            # The testcase.yaml filter language prefixes with
            # CONFIG_ stuff, so we don't strip it
            defconfig[key] = value
        self.target.report_info("filter: evaluating", dlevel = 2)
        try:
            res = commonl.expr_parser.parse(_filter, defconfig)
            self.target.report_info("filter: evaluated defconfig: %s" % res,
                                    dlevel = 1)
            if res == False:
                raise tc.skip_e("filter '%s' @ %s causes TC to be skipped"
                                % (_filter, origin))
            else:
                self.target.report_info(
                    "filter '%s' @ %s causes TC to be continued"
                    % (_filter, origin), dlevel = 2)
        except SyntaxError as se:
            raise tc.error_e("filter: failed processing '%s' @ %s: %s"
                             % (_filter, origin, se))

_pytc = re.compile("^test_.*.yaml$")

def _zephyr_components_from_path(filename, roots):
    """
    Given a filename to some zephyr testcase, try to guess components
    based on its location with regards to the different top-level trees
    given in @roots.

    Note this is a fallback from a more deterministic
    component-guessing based on tags or testcase name or manually
    assignment. Also, there are special cases hardcoded in.
    """
    for index, value in enumerate(roots):
        roots[index] = os.path.realpath(os.path.abspath(value))
    basename = os.path.basename(filename)
    if basename in [ 'testcase.yaml', 'testcase.ini', 'sample.yaml' ]:
        path = os.path.dirname(filename)
    elif _pytc.match(basename):
        path = os.path.dirname(filename)
    else:
        path = filename
    if isinstance(roots, str):
        roots = [ roots ]
    else:
        assert all(isinstance(root, str) for root in roots)
    # remove the prefix ZEPHYR_BASE/tests and the left over is our
    # component path
    components = []
    for root in roots:
        relpath = os.path.relpath(path, root)
        if relpath.startswith(os.path.pardir + os.path.sep) \
           or relpath == os.path.pardir:
            # not relative to root, can't use
            continue
        if not os.path.sep in relpath:	# at root, no component info
            if os.path.sep + 'samples' in root:
                # Special cases: top level samples
                return [ 'samples' ]
            if filename.endswith(os.path.join("tests", "shell",
                                              "testcase.yaml")):
                # Special case: this shell testcase at the top level
                return [ 'shell' ]
            return []
        if os.path.join("samples", "basic") in filename \
           or os.path.join("samples", "grove") in filename:
            # Special case: samples/{basic,grove} are driver samples
            return [ 'drivers' ]

        # Zephyr hacked transformations
        try:
            parts = relpath.split(os.path.sep)
            if parts[0] == 'subsys':
                parts.pop(0)
            if parts[0] == 'boards':	# convert to board/BOARDNAME/STH
                parts.pop(0)
                parts[0] = 'board/' + parts[0]
        except IndexError as e:
            # Uh, we ran out of parts? print who that was
            logging.error(
                "BUG? ran out of parts: relpath %s filename %s roots %s",
                relpath, filename, roots)
            raise
        # pure samples will have samples in root and only one part
        # (the name of the directory); override it
        if parts == [] and os.path.sep + 'samples' + os.path.sep in path:
            parts = [ 'samples' ]
        if parts:
            part = parts[0]
            if part == 'driver':
                part = 'drivers'
            if part == 'kerne':
                part = 'kernel'
            components.append(part)
    return components


def _zephyr_testcase_patcher_for_components(testcase):
    for tag in testcase._tags:
        if tag.startswith('component/'):
            # there are already assigned components
            testcase.log.debug("component info found, no need to guess")
            return

    # Is this a Zephyr related testcase? Does it declare any target
    # that will run Zephyr?
    # yeah, wouldn't cover all the basis, but then properly tag the
    # components in your testcase, this is just a guesser for backward
    # compat
    for _target_name, target_data in testcase._targets.items():
        kws = target_data.get('kws', {})
        if 'app_zephyr' in kws:
            # yay, at least one Zephyr target, we takes
            break
    else:
        # of all the targets in this testcase (if any), none declares
        # an App Zephyr, so we can't be sure this is a Zephyr-related
        # testcase
        return

    # There are not assigned components, so let's guess based on paths
    ZEPHYR_BASE = os.environ.get('ZEPHYR_BASE', None)
    ZEPHYR_TESTS_BASE = os.environ.get('ZEPHYR_TESTS_BASE', None)

    roots = []
    if ZEPHYR_BASE:
        roots += [
            os.path.join(ZEPHYR_BASE, "tests"),
            os.path.join(ZEPHYR_BASE, "samples"),
        ]
    if ZEPHYR_TESTS_BASE:
        roots += [
            os.path.join(ZEPHYR_TESTS_BASE, "tests"),
            os.path.join(ZEPHYR_TESTS_BASE, "testlib"),
        ]

    origin = commonl.origin_get()
    filename = testcase.kws.get('thisfile', None)
    if filename == None:
        testcase.log.debug("component info n/a, can't find source file")
        return
    filename = os.path.normpath(os.path.realpath(filename))
    componentl = _zephyr_components_from_path(os.path.abspath(filename), roots)
    for component in componentl:
        component_tag = "component/" + component
        testcase.tag_set(component_tag, component, origin)

    components = " ".join(componentl)
    testcase.log.info("component info guessed: %s", components)

tcfl.tc.tc_c.testcase_patchers.append(_zephyr_testcase_patcher_for_components)
