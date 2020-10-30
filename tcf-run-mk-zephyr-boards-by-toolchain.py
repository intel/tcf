#! /usr/bin/python3
"""Generate an expression for `tcf run`'s -t (or for tcf list) to
list Zephyr targets that support working with a given toolchain
"""
import argparse
import glob
import logging
import os
import sys
import yaml
import tcfl.config
import tcfl.ttb_client

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    # FIXME: should be in cmdline_log_options() but it does not work :/
    arg_parser.set_defaults(level = logging.ERROR)
    arg_parser.add_argument(
        "--config-file", "-c",
        action = "append", dest = "config_files", metavar = "CONFIG-FILE.py",
        # FIXME: s|/etc|system prefix from installation
        default = [ ],
        help = "Files to parse as configuration (this is used for testing, "
        "along with --config-path \"\"")
    # FIXME: change the config file looking stuff so that it looks for
    # .tcf in $PWD like git does with .git and then walks up until it
    # finds one; then it tries ~/.tcf, then /etc/tcf or whatever.
    arg_parser.add_argument(
        "--config-path",
        action = "append", dest = "config_path",
        # FIXME: s|/etc|system prefix from installation
        default = [ "/etc/tcf:~/.tcf:.tcf" ],
        help = "List of colon separated paths from where to load conf_.*.py "
        "configuration files (in alphabetic order)")
    arg_parser.add_argument(
        "--state-path", action = "store", default = "~/.tcf",
        help = "Directory where to save state")
    arg_parser.add_argument(
        "--map", action = "store", default = None,
        help = "File where to save a TCF to Zephyr target type name")
    arg_parser.add_argument("zephyrdir", action = "store", type = str,
                            default = None,
                            help = "Directory of Zephyr source")
    arg_parser.add_argument("toolchain", action = "store", type = str,
                            default = "n/a", nargs = '?',
                            help = "Name of the toolchain to use")

logging.basicConfig()
args = arg_parser.parse_args()
tcfl.config.load(config_path = args.config_path,
                 config_files = args.config_files,
                 state_path = os.path.expanduser(args.state_path))


# Calculate toolchain boards
toolchains_known = set()
toolchain_boards = set()
for fn in glob.glob(args.zephyrdir + "/boards/*/*/*.yaml"):
    with open(fn) as f:
        y = yaml.safe_load(f)
    board = os.path.basename(fn).replace(".yaml", "")
    toolchains = y.get('toolchain', [])
    toolchains_known.update(toolchains)
    if args.toolchain in toolchains:
        toolchain_boards.add(board)
logging.warning("Toolchains known: %s", ", ".join(sorted(toolchains_known)))
logging.warning("Zephyr boards for toolchain %s: %s",
                args.toolchain, ", ".join(sorted(toolchain_boards)))


rt_all = tcfl.ttb_client.rest_target_find_all()
tcf_to_zephyr = dict()
zephyr_boards_available = set()
for rt in rt_all:
    tcf_type = rt.get('type', None)
    for bsp, data in rt.get('bsps', {}).items():
        zephyr_board = data.get('zephyr_board', None)
        if zephyr_board:
            zephyr_boards_available.add(zephyr_board)
        if zephyr_board and tcf_type:
            tcf_to_zephyr[tcf_type + ":" + bsp] = zephyr_board
            # If the target is a single BSP target, also translate
            # TYPE->ZEPHYR_TYPE without the :BSP part
            if len(rt['bsps']) == 1:
                tcf_to_zephyr[tcf_type] = zephyr_board

logging.warning("Zephyr boards available: %s",
                ", ".join(sorted(zephyr_boards_available)))


if args.map:
    with open(args.map, "w") as mapf:
        mapf.write("type_map = {\n")
        for tcf_type, zephyr_type in tcf_to_zephyr.items():
            mapf.write("    '%s': '%s',\n" % (tcf_type, zephyr_type))
        mapf.write("}\n")

boards = toolchain_boards & zephyr_boards_available
# Now compute which boards we have available
if boards:
    print('(zephyr_board in [ \"' + '\", \"'.join(sorted(boards)) + '\" ])')
else:
    print('(zephyr_board in [ \"\" ])')
