#! /usr/bin/env python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
"""
Command Line Interface helpers
------------------------------

These are helpers to assist in common tasks when creating command line
interfaces.
"""
import argparse
import copy
import inspect
import logging
import os
import platform
import re
import shutil
import sys
import threading
import tempfile

import argcomplete
import requests

import tcfl
import tcfl.tc
import tcfl.config
import tcfl._install
import tcfl.ui_cli
import tcfl.ui_cli_targets	# needed earlier on


def join_args_for_make_shell_command(args):
    """
    Given a list of arguments to a shell command, escape them to run
    them from a Makefile
    """
    s = ""
    for arg in args:
        _arg = re.sub(r'([\'])', r'\\\1', arg)
        _arg = re.sub(r'(\$)', r'$$', _arg)
        s += " '" + _arg + "'"
    return s

def _cmdline_config(_args):
    import commonl
    print(f"""\
tcf: {sys.argv[0]}
tcf/realpath: {os.path.realpath(sys.argv[0])}
tcfl: {inspect.getfile(tcfl)}
commonl: {inspect.getfile(commonl)}
share path: {tcfl.config.share_path}
state path: {tcfl.config.state_path}
config path: {os.pathsep.join(tcfl.config.path)}""")
    count = 0
    for config_file in tcfl.config.loaded_files:
        print(f"config file {count}: {config_file}")
        count += 1
    print(f"""\
version: {tcfl.tc.version}
python: {" ".join(sys.version.splitlines())}""")
    commonl.data_dump_recursive(platform.uname()._asdict(), "uname")
    print(f"""\
servers: {len(tcfl.server_c.servers)}""")
    count = 0
    for url, server in sorted(tcfl.server_c.servers.items(),
                              key = lambda i: i[0]):
        print(f"server {server.aka}: {url} [{server.origin or 'n/a'}]")
        count += 1

    # Get resolver information to know default search domains
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                print(f"resolvconf: {line.strip()}")
    except OSError as e:
        print(f"resolvconf: skipping [{e}]")
    # FIXME: windows way to do this?
    # https://stackoverflow.com/questions/21318427/get-dns-search-suffix-in-python



def _cmdline_cache_flush(_args):
    cache_path = os.path.join(os.path.expanduser("~"), ".cache", "tcf")
    print(f"I: wiping {cache_path}")
    shutil.rmtree(cache_path, ignore_errors = True)


# used by __main__._rotator
_rotator_lock = threading.Lock()

def __main__():
    import tcfl
    import tcfl.tc
    import commonl
    tcfl.tc.version = commonl.version_get(tcfl, "tcf")

    if "TCF_NEW_COMMANDS" in os.environ:
        tcfl.ui_cli.commands_old_suffix = "-old"
        tcfl.ui_cli.commands_new_suffix = ""
    else:
        tcfl.ui_cli.commands_old_suffix = ""
        tcfl.ui_cli.commands_new_suffix = "2"

    # set @ so we can get args from a file
    arg_parser = argparse.ArgumentParser(fromfile_prefix_chars = '@')
    commonl.cmdline_log_options(arg_parser)
    # FIXME: should be in cmdline_log_options() but it does not work :/
    arg_parser.set_defaults(level = logging.ERROR)
    arg_parser.add_argument(
        "--config-file", "-c",
        action = "append", dest = "config_files", metavar = "CONFIG-FILE.py",
        # FIXME: s|/etc|system prefix from installation
        default = [ ],
        help = "Files to parse as configuration (this is used for testing, "
        "along with --config-path \"\"")
    arg_parser.add_argument(
        "--as-admin",
        action = "store_true", default = False,
        help = "run command gaining admin role first, then dropping it")
    arg_parser.add_argument(	# same as tcfl.ui_cli.args_targetspec_add()
        "--help-fieldnames",
        action = tcfl.ui_cli_targets.argparser_action_help_fieldnames, nargs = 0,
        help = "Display all fields in the inventory")
    arg_parser.add_argument(	# same as tcfl.ui_cli.args_targetspec_add()
        "--help-targetspec",
        action = tcfl.ui_cli_targets.argparser_action_help_targetspec, nargs = 0,
        help = "Display information about the target query language")
    arg_parser.add_argument(
        "-p", "--config-path",
        action = "append", dest = "config_path",
        default =  [
            ".tcf", os.path.join(os.path.expanduser("~"), ".tcf"),
        ] + tcfl._install.sysconfig_paths,
        help = f"List of '{os.pathsep}' separated paths from where"
        " to load conf_.*.py configuration files in alphabetic order"
        " (%(default)s)")
    arg_parser.add_argument(
        "--state-path", action = "store",
        default = os.path.join(os.path.expanduser("~"), ".tcf"),
        help = "Directory where to save state (%(default)s)")
    arg_parser.add_argument(
        "-u", "--url", action = "append", default = [],
        help = "URL to the test broker (multiple may be specified)")
    arg_parser.add_argument(
        "--servers-discover", action = "store_true", default = True,
        help = "Force discovering more servers")
    arg_parser.add_argument(
        "--no-servers-discover", action = "store_false",
        dest = "servers_discover",
        help = "Do not discover servers, use only those given with --url")
    arg_parser.add_argument(
        "--servers-cache", action = "store_true", default = True,
        dest = "servers_cache",
        help = "Use the servers previosuly discovered (cached)")
    arg_parser.add_argument(
        "--no-servers-cache", action = "store_false",
        dest = "servers_cache",
        help = "Ignore previosuly discovered servers")
    arg_parser.add_argument(
        "-d", "--debug", action = "store_true", default = False,
        help = "Enable internal debug prints and checks and"
        " extra logging info")
    arg_parser.add_argument(
        "-x", "--traces", action='store_true', default = False,
        help = "Print exception traces")
    arg_parser.add_argument(
        "--log-functions", action='store_true', default = False,
        help = "Log function names")
    arg_parser.add_argument(
        "-i", "--ignore-ssl", action='store_true', default = False,
        help = "Ignore server SSL certificate")

    arg_parser.add_argument(
        "-e", "--environment", metavar = "KEY[=VALUE]", action='append',
        default = [],
        help = "add an environment variable to execution;"
        " if VALUE is omitted, it defaults to 'true'")
    arg_parser.add_argument(
        "--environment-password", metavar = "KEY[=VALUE]", action = 'append',
        default = [],
        help = "add an environment variable to execution"
        " that might contain password (KEY=KEYRING[:DOMAIN[:USER]] and"
        " KEY=FILE:FILENAME are expanded")
    # This is made a global argument, even if only 'run' uses it
    # because it makes it easier to generate the sub-command without
    # having to muck with 'run's sub-arguments
    arg_parser.add_argument(
        "--make-jobserver", action = "store", default = False,
        help = "[internal] used to re-execute under a make jobserver.")
    arg_parser.add_argument(
        "--no-make-jobserver", action = "store_false",
        dest = "make_jobserver",
        help = "[internal] do not re-run under a make jobserver.")
    # Do it like this insead of adding a version to the main parser
    # because it will by default add adds -v as shortcut (when everyone and their grandma
    # knows -V is vor --version, -v for --verbose)
    arg_parser.add_argument(
        '-V', '--version',
        action = 'version', default = argparse.SUPPRESS,
        version = tcfl.tc.version,
        help = "show program's version number and exit")

    arg_parser.add_argument(
        "-t", "--ticket", metavar = "TICKET",
        action = "store", default = '',
        help = "DEPRECATED & IGNORED")

    arg_parser.add_argument(
        "-a", "--allocid", metavar = "ALLOCATIONID",
        action = "store", default = None,
        help = "Use this allocid to access targets")

    arg_parser.add_argument(
        "-A",
        action = "store_const", dest = "allocid", const = "any",
        help = "Use any existing allocation")

    arg_parser.add_argument(
        "-C", action = "store", default = None, metavar = "DIR",
        dest = "chdir",
        help = "Change to DIR before starting")
    arg_subparsers = arg_parser.add_subparsers(help = "commands")

    arg_parser.add_argument(
        "--server-age", action = "store", type = int,
        default = 10 * 60,
        help = "time in (seconds) after which a server is re-discovered"
        " for fresh information (%(default)s); set to zero to force"
        " rediscovery")

    arg_group = arg_parser.add_argument_group('Log control options')

    arg_group.add_argument(
        "--log-bare-level", action = "store",
        type = int, default = logging.DEBUG,
        help = "When logging to a file (see --logfile-maxbyte), minimum"
        " log level we capture [logging.DEBUG %(default)d]")

    arg_group.add_argument(
        "--logfile-maxbytes", action = "store",
        type = int, default = 5 * 1024 * 1204,
        help = "Maximum size of the log files before we rotate [%(default)dB];"
        " set to zero to disable logging to a file")

    arg_group.add_argument(
        "--logfile-backupcount", action = "store",
        type = int, default = 5,
        help = "Number of copies of old log files we keep around [%(default)d]")

    arg_group.add_argument(
        "--logfile-name", action = "store",
        default = "~/tcf.log",
        help = "Name of the file where we log details [%(default)s]")

    ap = arg_subparsers.add_parser(
        "config", help = "Print information about configuration")
    ap.set_defaults(func = _cmdline_config)

    import tcfl.ui_cli_servers
    tcfl.ui_cli_servers.cmdline_setup(arg_subparsers)

    import tcfl.ui_cli_users
    tcfl.ui_cli_users.cmdline_setup(arg_subparsers)

    import tcfl.ui_cli_targets
    tcfl.ui_cli_targets._cmdline_setup(arg_subparsers)

    import tcfl.ui_cli_alloc
    tcfl.ui_cli_alloc.cmdline_setup(arg_subparsers)

    tcfl.ui_cli_alloc.cmdline_setup(arg_subparsers)
    tcfl.tc.target_ext_alloc._cmdline_setup(arg_subparsers)



    import tcfl.ui_cli_power
    tcfl.ui_cli_power._cmdline_setup(arg_subparsers)

    import tcfl.ui_cli_images
    tcfl.ui_cli_images._cmdline_setup(arg_subparsers)
    import tcfl.ui_cli_console
    tcfl.ui_cli_console._cmdline_setup(arg_subparsers)


    # Semi advanced commands

    tcfl.ui_cli_targets._cmdline_setup_advanced(arg_subparsers)

    tcfl.tc.argp_setup(arg_subparsers)

    import tcfl.ui_cli_buttons
    tcfl.ui_cli_buttons.cmdline_setup_intermediate(arg_subparsers)

    import tcfl.ui_cli_capture
    tcfl.ui_cli_capture.cmdline_setup_intermediate(arg_subparsers)

    import tcfl.ui_cli_console
    tcfl.ui_cli_console._cmdline_setup_advanced(arg_subparsers)

    import tcfl.ui_cli_store
    tcfl.ui_cli_store.cmdline_setup_intermediate(arg_subparsers)
    import tcfl.ui_cli_tunnel
    tcfl.ui_cli_tunnel.cmdline_setup(arg_subparsers)

    tcfl.ui_cli_alloc.cmdline_setup_intermediate(arg_subparsers)

    import tcfl.ui_cli_certs
    tcfl.ui_cli_certs.cmdline_setup(arg_subparsers)

    import tcfl.ui_cli_testcases
    tcfl.ui_cli_testcases._cmdline_setup(arg_subparsers)

    # advanced commands
    tcfl.ui_cli_servers.cmdline_setup_advanced(arg_subparsers)

    import tcfl.ui_cli_users
    tcfl.ui_cli_users.cmdline_setup_advanced(arg_subparsers)

    ap = arg_subparsers.add_parser("cache-flush",
                                   help = "wipe all caches")
    ap.set_defaults(func = _cmdline_cache_flush)

    tcfl.ui_cli_alloc.cmdline_setup_advanced(arg_subparsers)

    import tcfl.ui_cli_debug
    tcfl.ui_cli_debug.cmdline_setup_advanced(arg_subparsers)

    tcfl.ui_cli_images._cmdline_setup_advanced(arg_subparsers)

    import tcfl.ui_cli_pos
    tcfl.ui_cli_pos._cmdline_setup_advanced(arg_subparsers)

    import tcfl.ui_cli_fastboot
    tcfl.ui_cli_fastboot.cmdline_setup_advanced(arg_subparsers)

    import tcfl.ui_cli_things
    tcfl.ui_cli_things.cmdline_setup_intermediate(arg_subparsers)

    # extra stuff that is not adding to the API, just to the command
    # line interface
    import tcfl.ui_cli_alloc_monitor
    tcfl.ui_cli_alloc_monitor._cmdline_setup(arg_subparsers)

    import commonl.ui_cli
    commonl.ui_cli._cmdline_setup_advanced(arg_subparsers)
    tcfl.ui_cli_testcases._cmdline_setup_advanced(arg_subparsers)

    argcomplete.autocomplete(arg_parser)
    global args
    args = arg_parser.parse_args()
    log_format = "%(levelname)s: %(name)s"
    if args.debug or args.log_functions:
        log_format += "::%(module)s.%(funcName)s():%(lineno)d"
    log_format += ": %(message)s"
    log_format = commonl.log_format_compose(log_format, args.log_pid_tid,
                                            args.log_time, args.log_time_delta)

    #
    # Configure always logging lots of details to a log file
    #
    # We always get reports about issues and they never captured, so
    # we end up crying that we have no info; capture it all, compress
    # and rotate older stuff
    #
    # We need to setup the engine to log to the minimum log level and
    # then set the console logger to what the user wants in the console
    #
    # Credit
    #
    # https://docs.python.org/3/howto/logging-cookbook.html#using-a-rotator-and-namer-to-customize-log-rotation-processing
    # https://docs.python.org/3/library/logging.html#logger-objects

    def _namer(name):
        return name + ".gz"

    def _rotator(source, dest):
        import gzip
        import shutil
        with _rotator_lock:
            # don't log here, it'll recurse and splat
            #print("DEBUG rotating")
            with open(source, 'rb') as f_in:
                # this might have been preempted, so do a safety check
                stat_info = os.fstat(f_in.fileno())
                if stat_info.st_size < args.logfile_maxbytes:
                    # another thread got to it before we did
                    #print("DEBUG not rotating, preempted")
                    return
                with gzip.open(dest, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                    os.remove(source)
                #print("DEBUG rotated")

    if args.logfile_maxbytes > 0:
        logging.basicConfig(format = log_format, level = args.log_bare_level)
    else:
        logging.basicConfig(format = log_format, level = args.level)

    # set the console logger level
    root = logging.getLogger()
    root.handlers[0].setLevel(args.level)

    if args.logfile_maxbytes > 0:
        # configure the logfile rotator
        logfile_handler = logging.handlers.RotatingFileHandler(
            os.path.expanduser(args.logfile_name),
            maxBytes = args.logfile_maxbytes,
            backupCount = args.logfile_backupcount)
        logfile_handler.rotator = _rotator
        logfile_handler.namer = _namer

        root.addHandler(logfile_handler)
        logfile_handler.setLevel(logging.DEBUG)
        logfile_handler.setFormatter(
            # add hella details so we can track it all
            logging.Formatter(
                "%(levelname)s[%(process)d]/%(asctime)s+%(relativeCreated)dms"
                " %(name)s::%(module)s.%(funcName)s():%(lineno)d: %(message)s"))

    for environment in args.environment:
        if '=' in environment:
            key, val = environment.split("=", 1)
        else:
            key = environment
            val = "true"
        os.environ[key] = val

    for environment in args.environment_password:
        key, val = environment.split("=", 1)
        os.environ[key] = commonl.password_get(None, None, val)

    if args.debug:
        import http.client
        # Debug logging
        http.client.HTTPConnection.debuglevel = 1
        logging.getLogger().setLevel(logging.DEBUG)
        req_log = logging.getLogger('requests.packages.urllib3')
        req_log.setLevel(logging.DEBUG)
        req_log.propagate = True
    else:
        # we don't need all the warnings from urllib
        import urllib3
        urllib3.disable_warnings()

    if args.traces or args.debug:
        # I mean, this is ugly, but simple
        commonl.debug_traces = True
    else:
        commonl.debug_traces = False

    tcfl.server_c.max_cache_age = args.server_age

    if args.chdir:
        os.chdir(args.chdir)

    # No command specified
    # Rather than a cryptic error, print usage
    if 'func' not in args:
        arg_parser.print_help()
        retval=1
        sys.exit(retval)

    if args.func == tcfl.tc._run:
        if args.make_jobserver == None:
            # Okie, notice the hack! When doing the 'run' command, we may be
            # building *a lot* of stuff, in parallel, most likely using
            # make. To reap paralellism benefits, we will do it in parallel,
            # but not to over do it, we'll use a make jobserver to streamline
            # and coordinate.
            #
            # For that, we will re-run this command under a 'make -jN
            # tcf-jobserver-run' line:
            #
            # - This way make(1) will start a jobserver with N parallelism
            #   and run our tcf-command under it
            #
            # - (+) indicates to export the the jobserver specs (MAKEFLAGS
            #   has a commandline with he file descriptors to use for
            #   comms, which must be kept open) -- thus the
            #   tcfl.tc_action_c.run_one() function, when running, has
            #   to maintain FDs open and keep the environment.
            with tempfile.NamedTemporaryFile(suffix = '.mk', prefix = 'tcf-',
                                             delete = False) as tf:
                logging.debug("%s: creating makefile for jobserver run"
                              % tf.name)
                tf.write(("""\
tcf-jobserver-run:
\t+@%s --make-jobserver=%s %s
""" % (sys.argv[0], tf.name,
       join_args_for_make_shell_command(sys.argv[1:]))).encode('utf-8'))
                tf.flush()
                tf.seek(0)
                logging.debug("%s: makefile:\n%s" % (tf.name, tf.read()))
                logging.info("%s: executing makefile jobserver that will"
                             " re-run this command" % tf.name)
                os.execvp("make", [ "make", "-s", "-f", tf.name, "-j%s" %
                                    args.make_j, "tcf-jobserver-run" ])
        elif args.make_jobserver == False:
            logging.info("%s: not re-running under make-jobserver"
                         % (args.make_jobserver))
            pass	# No jobserver wanted
        else:		# We running under the jobserver, remove the makefile
            logging.debug("%s: removing make-jobserver makefile"
                          % (args.make_jobserver))
            # Wipe the makefile we used to run tcf/run under a make
            # jobserver, not needed anymore.
            os.unlink(args.make_jobserver)

    for url in args.url:	# Expand the list of URLs
        if url == "":	# Cleanup list if there is an empty url
            tcfl.config.urls = []
        else:
            tcfl.config.url_add(url, args.ignore_ssl, origin = "command line")

    # ugly hack--if we are disabling server discovery, we need to set
    # it in tcfl.servers--defaults to True--so that it can be
    # acknowledged
    if not args.servers_discover:
        import tcfl.servers
        tcfl.servers.servers_discover = False

    if not args.servers_cache:
        import tcfl.servers
        tcfl.servers.servers_cache = False

    tcfl.config.load(config_path = args.config_path,
                     config_files = args.config_files,
                     state_dir = args.state_path,
                     ignore_ssl = args.ignore_ssl)
    logging.info("state path: %s" % tcfl.config.state_path)
    logging.info("share path: %s" % tcfl.config.share_path)


    if 'func' in args:
        _args = copy.copy(args)
        _args.username = "self"
        _args.role = "admin"
        _args.verbosity = getattr(args, "verbosity", 0)
        _args.quietosity = getattr(args, "quietosity", 0)
        _args.parallelization_factor = getattr(args, "parallelization_factor", -4)
        if args.as_admin:
            # FIXME: This has to be replaced, since it is not
            # reentrant; need to move it to the protocol so we can
            # tell it "run this call with these roles enabled, those
            # roles disabled".
            import tcfl.ui_cli_users
            # this is quite dirty, but it'll do until we add this to
            # the protocol
            try:
                logging.info("gaining admin role per --as-admin")
                tcfl.ui_cli_users._cmdline_role_gain(_args)
                logging.info("gained admin role per --as-admin")
            except Exception as e:
                logging.exception("can't get admin role per --as-admin")
                raise
        try:
            retval = args.func(args)
        except Exception as e:
            # note Exception always have a list of args and the first
            # one is commonly the message, the rest are details
            if args.traces:
                logging.exception(e.args[0])
            else:
                rep = str(e)
                if rep == "":
                    logging.error(
                        "%s exception raised with no description "
                        "(run with `--traces` for more info)"
                        % type(e).__name__)
                else:
                    logging.error(e.args[0])
            retval = 1
        finally:
            if args.as_admin:
                logging.info("dropping admin role per --as-admin")
                tcfl.ui_cli_users._cmdline_role_drop(_args)
    else:
        logging.exception("No command specified")
        retval = 1

    # Hack the different return values we can get from the APIs to a
    # simple success/failure
    if isinstance(retval, requests.Response):
        if retval.status_code == 200:
            retval = 0
        else:
            retval = 1
    elif isinstance(retval, bool):
        if retval == True:
            retval = 0
        else:
            retval = 1
    elif isinstance(retval, int):
        pass
    elif isinstance(retval, dict):
        # This usually means we got all the info we needed
        retval = 0
    elif retval == None:
        # This usually means things that don't return anything and
        # just fail with exceptions
        retval = 0
    else:
        logging.warning("Don't know how to interpret retval %s (%s) as"
                        " exit code" % (retval, type(retval)))
        retval = 1
    sys.exit(retval)
