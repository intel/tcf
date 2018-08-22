#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Run differente lint / verification steps on a git working
directory, assuming all the files necessary are checked out (so it can
be the work in progress code or HEAD).

Steps are implemented by scriptlets called .lint.NAME.py in the
current directory or any path given with -p.
"""
import tempfile
import argparse
import imp
import logging
import os
import re
import subprocess
import sys

import git

help_epilog = """
To use with git commit hook:

 - edit .git/hooks/pre-commit and add:

     [ -x lint-all.py ] && ./lint-all.py

   (if your lint-all is in a separate directory, add the full path to it).

To use with gerrit:

  - disable all Jenkins' gerrit voting (in Jenkins's job config, check
    skip vote in the advanced tab of the gerrit triggers) [otherwise,
    it won't be able to vote]

  - don't use shallow clones--otherwise we can't compare properly

To write lint integration scripts:

  - create a Python file .lint.NAME.py

  - have it declare one or more functions called lint_SOMETHING that take
    two arguments, a Git Repo object and a changedfile object.

  - have it print to stdout lines in the form FILENAME:[LINE:]
    MESSAGE, make filenames relative to os.getpwd()

    Note: only whatever the scriptlet prints with Python's print()
    will be used--if you fork a process, capture its output and print
    it with print() or sys.stdout.write()

  - return a 3-tuple NUMBER-OF-ERRORS, WARNINGS, BLOCKAGES



"""

lint_functions = {}

def config_import_file(filename, raise_on_fail = True):
    """
    Loads one configuration file
    """
    logging.log(9, "%s: configuration file being loaded", filename)
    try:
        # We make this __ separator between path and file name, and
        # will use later in the printing functions to extract the
        # module name again
        module_name = filename.translate(str.maketrans("/.", "__"))
        module = imp.load_source(module_name, filename)
        sys.stdout.flush()
        sys.stderr.flush()
        logging.debug("%s: configuration file imported", filename)
        for symbol in module.__dict__:
            if callable(module.__dict__[symbol]) \
               and symbol.startswith("lint_"):
                _symbol = symbol.replace("lint_run_", "")
                _symbol = _symbol.replace("lint_", "")
                _symbol = _symbol.replace("_py", "")
                lint_functions[_symbol] = module.__dict__[symbol]
    except Exception as e:	# pylint: disable = W0703
        # throw a wide net to catch any errors in filename
        logging.exception("%s: can't load config file: %s", filename, e)
        if raise_on_fail:
            raise

def _path_expand(path_list):
    # Compose the path list
    _list = []
    for _paths in path_list:
        paths = _paths.split(":")
        for path in paths:
            if path == "":
                _list = []
            else:
                _list.append(os.path.expanduser(path))
    return _list

def config_import(path_list, file_regex, namespace = "__main__",
                  raise_on_fail = True):
    """Import Python [configuration] files that match file_regex in any of
    the list of given paths into the given namespace.

    Any symbol available to the current namespace is available to the
    configuration file.

    :param paths: list of paths where to import from; each item can be
      a list of colon separated paths and thus the list would be further
      expanded. If an element is the empty list, it removes the
      current list.

    :param file_regex: a compiled regular expression to match the file
      name against.

    :param namespace: namespace where to insert the configuration file

    :param bool raise_on_fail: (optional) raise an exception if the
      importing of the config file fails.

    >>> config_import([ ".config:/etc/config" ],
    >>>               re.compile("conf[_-].*.py"),
    >>>               "__main__")

    """

    # Compose the path list
    _list = _path_expand(path_list)
    paths_done = set()
    # Bring in config files
    for path in _list:
        abs_path = os.path.abspath(os.path.normpath(path))
        if abs_path in paths_done:
            # Skip what we have done already
            continue
        logging.log(8, "%s: loading configuration files %s",
                    path, file_regex.pattern)
        try:
            if not os.path.isdir(path):
                logging.log(7, "%s: ignoring non-directory", path)
                continue
            for filename in sorted(os.listdir(path)):
                if not file_regex.match(filename):
                    logging.log(6, "%s/%s: ignored", path, filename)
                    continue
                config_import_file(path + "/" + filename, namespace)
        except Exception:	# pylint: disable = W0703
            # throw a wide net to catch any errors in filename
            logging.error("%s: can't load config files", path)
            if raise_on_fail:
                raise
        else:
            logging.log(9, "%s: loaded configuration files %s",
                        path, file_regex.pattern)
        paths_done.add(abs_path)

def generic_line_linter(
        _repo, cf, cmdline, log,
        regex_error = re.compile(
            r":(?P<line_number>[0-9]+)(:(?P<column_number>[0-9]+))?:"
            r" \[(E\w+[0-9]+|error)\] "),
        regex_warning = re.compile(
            r":(?P<line_number>[0-9]+)(:(?P<column_number>[0-9]+))?: "
            r"\[([WCR]\w+[0-9]+|warning)\] ")):
    """Run a generic linter that outputs in standarized way and report

    Most linters can be made to report in the format::

      FILENAME:LINE:COLUMN: [TAG] Message1
      FILENAME:LINE:COLUMN: [TAG] Message2
      FILENAME:LINE:COLUMN: [TAG] Message3
      ...

    Where *:COLUMN* might be optional and *TAG* usually follows something like:

    - *[EWCR]NUMBER*: pylint and co
    - *error*: yamlint...

    :param re._pattern_type regex_error: compiled regular expression
      to match the lines reporting errors that have to be reported; it
      must contain a group match *(?P<line_number>[0-9]+)* to extract
      the line number for.

      If a line is considered as an error, it won't be considered for
      a warning -- to simplify the pattern matching

    :param re._pattern_type regex_warning: same thing, for warnings
    """
    assert isinstance(_repo, git.Repo)
    assert isinstance(cf, changedfile_c)
    assert isinstance(cmdline, list)
    assert isinstance(log, logging.Logger)
    assert isinstance(regex_error, re._pattern_type)
    assert isinstance(regex_warning, re._pattern_type)

    try:
        if os.path.isabs(_repo.relpath):
            cwd = '/'
        else:
            cwd = os.getcwd()
        log.debug("Running %s", " ".join(cmdline))
        output = subprocess.check_output(
            cmdline, stderr = subprocess.STDOUT, universal_newlines = True,
            cwd = cwd)
    except FileNotFoundError:
        _repo.error("Can't find linter? [%s]", cmdline[0])
    except subprocess.CalledProcessError as e:
        output = e.output

    _errors = 0
    _warnings = 0
    for line in output.splitlines():
        line = line.strip()
        me = regex_error.search(line)
        mw = regex_warning.search(line)
        if me:
            cf.warning(line, int(me.groupdict()["line_number"]))
        elif mw:
            cf.error(line, int(mw.groupdict()["line_number"]))


def _gerrit_feedback(_args, _errors, _warnings, _blockage, message):
    # pylint: disable = too-many-locals
    import json
    # work around from https://github.com/paramiko/paramiko/pull/861
    # for bug https://github.com/paramiko/paramiko/issues/1068 when
    # GSSAPI is installed by Ansible
    sys.modules['gssapi'] = None
    import paramiko.client

    if _args.gerrit_from_jenkins:
        logging.info("Getting gerrit info from Jenkins environment")
        scheme = os.environ['GERRIT_SCHEME']
        if scheme != 'ssh':
            logging.error('%s: GERRIT_SCHEME unsupported', scheme)
        host = os.environ['GERRIT_HOST']
        port = int(os.environ['GERRIT_PORT'])
        change_number = int(os.environ['GERRIT_CHANGE_NUMBER'])
        patchset_number = int(os.environ['GERRIT_PATCHSET_NUMBER'])
        ssh_user = os.environ['SSH_USER']
    else:
        logging.info("Getting gerrit info from cmdline")
        host = _args.gerrit_ssh_host
        port = int(_args.gerrit_ssh_port)
        change_number = _args.gerrit_change_number
        patchset_number = _args.gerrit_patchset_number
        ssh_user = _args.gerrit_ssh_user

    params = {}
    if ssh_user:
        params['username'] = ssh_user
    client = paramiko.client.SSHClient()
    client.load_system_host_keys()
    client.connect(host, port, **params)

    data = dict(
        labels = {
        },
    )
    if _warnings > 0:
        data['labels']['Code-Review'] = -1
    if _errors == 0:
        data['labels']['Verified'] = 1
    else:
        data['labels']['Verified'] = -1
    if _blockage > 0:
        # No verification if missing tools
        print("W: 'Verified %d' vote skipped as some tools are missing "
              "and can't check it all" % data['labels']['Verified'])
        del data['labels']['Verified']

    if message and message != "":
        if _args.url:
            cut_msg = "...\n<cut oversized report, more at %s>" % _args.url
        else:
            cut_msg = "...\n<cut oversized report>"
        cut_len = len(cut_msg)
        if len(message) > _args.gerrit_message_limit:
            message = message[:_args.gerrit_message_limit - cut_len] \
                      + cut_msg
        data['message'] = message
    stdin, stdout, stderr = client.exec_command(
        'gerrit review --json %d,%d' % (change_number, patchset_number),
        bufsize = -1)
    stdin.write(json.dumps(data))
    stdin.flush()
    stdin.channel.shutdown_write()
    output = str(stdout.read(), encoding = 'utf-8') \
            + str(stderr.read(), encoding = 'utf-8')
    if output:
        logging.error("gerrit review output: %s", output)

class tee_c(object):
    """
    Duplicate stdout to a file, so we can collect that output to send
    it to review systems
    """
    def __init__(self):
        self.stdout = sys.stdout
        self.fp = tempfile.TemporaryFile(prefix = "lint-all", mode = "w+")

    def write(self, message):	# pylint: disable = missing-docstring
        self.stdout.write(message)
        self.fp.write(message)

    def flush(self):		# pylint: disable = missing-docstring
        self.stdout.flush()
        self.fp.flush()

class changedfile_c(object):	# pylint: disable = too-few-public-methods
    """
    Describes a file that changed
    """
    gitrev_blame = None
    def __init__(self, repo, filename):

        self.repo = repo

        self.name = os.path.normpath(filename)
        self.name_rel_repo = os.path.relpath(self.name, repo.working_tree_dir)
        try:
            # This is only valid for checked out
            self.stat = os.stat(filename)
            self.deleted = False
        except FileNotFoundError:
            self.deleted = True

        # Check if binary
        if not self.deleted:
            with open(filename, 'rb') as f:
                chunk = f.read(4096)
            # Same dirty check git does...bleh
            self.binary = b'\0' in chunk
        else:
            # We consider deleted files binary for simplicity
            self.binary = True

        # Check which lines were modified by the commit
        self.lines = []
        if not self.binary:
            if self.repo.is_dirty(untracked_files = True):
                logging.debug("%s: blaming", self.name)
                output = repo.git.blame('-p', '--', self.name_rel_repo)
            else:
                output = repo.git.blame('-p', changedfile_c.gitrev_blame, '--',
                                        self.name_rel_repo)
            for line in output.splitlines():
                if line.startswith(changedfile_c.gitrev_blame):
                    _, line_start, _ = line.split(" ", 2)
                    self.lines.append(int(line_start))

        logging.debug("%s: binary:%s deleted:%s lines-changed:%s",
                      self.name, self.binary, self.deleted,
                      ",".join([ str(i) for i in self.lines ]))

    @staticmethod
    def message(message):
        """
        Report a message

        :param str message: line with the message
        """
        print(message)

    def warning(self, message, line_number = None):
        """
        Report a warning line

        :param str message: line with the message, ideally in form::

          FILE:LINE[:COLUMN] MESSAGE

        :param int line_number: (optional) line where the warning was
          found; if provided and it is part of the lines the current
          changeset being verified modified, the warning will be
          reported. Otherwise, it will be ignored (unless -W was
          given).
        """
        if line_number in self.lines or self.repo.wide:
            context.warnings += 1
            self.message(message)

    def error(self, message, line_number = None):
        """
        Report an error line

        :param str message: line with the message, ideally in form::

          FILE:LINE[:COLUMN] MESSAGE

        :param int line_number: (optional) line where the error was
          found; if provided and it is part of the lines the current
          changeset being verified modified, the error will be
          reported. Otherwise, it will be ignored (unless -W was
          given).
        """
        if line_number in self.lines or self.repo.wide:
            context.errors += 1
            self.message(message)

    def blockage(self, message, line_number = None):
        """
        Report a blockage line

        :param str message: line with the message, ideally in form::

          FILE:LINE[:COLUMN] MESSAGE

        :param int line_number: (optional) line where the blockage was
          found; if provided and it is part of the lines the current
          changeset being verified modified, the blocakge will be
          reported. Otherwise, it will be ignored (unless -W was
          given).
        """
        if line_number in self.lines or self.repo.wide:
            context.blockage += 1
            self.message(message)

class _action_increase_level(argparse.Action):	# pylint: disable = too-few-public-methods
    def __init__(self, option_strings, dest, default = None, required = False,
                 nargs = None, **kwargs):
        super(_action_increase_level, self).__init__(
            option_strings, dest, nargs = 0, required = required,
            **kwargs)

    @staticmethod
    def _logging_verbosity_inc(level):
        if level == 0:
            return
        if level > logging.DEBUG:
            delta = 10
        else:
            delta = 1
        return level - delta

    # Python levels are 50, 40, 30, 20, 10 ... (debug) 9 8 7 6 5 ... :)
    def __call__(self, parser, namespace, values, option_string = None):
        if namespace.level == None:
            namespace.level = logging.ERROR
        namespace.level = self._logging_verbosity_inc(namespace.level)

ap = argparse.ArgumentParser(
    description = __doc__,
    epilog = help_epilog,
    formatter_class = argparse.RawTextHelpFormatter,
)
ap.set_defaults(
    use = None,
    scripts_path = [ os.path.dirname(__file__) ],
)
ap.add_argument(
    "path", nargs = '?',
    action = "store", default = '.',
    help = "Path where the git tree is (defaults to current "
    "working directory)")
ap.add_argument(
    "-p", "--scripts-path",
    action = "append",
    help = "Add a find where to find .lint.*.py scripts")
ap.add_argument(
    "-s", "--script",
    action = "append", default = [],
    help = "lint scripts to append")
ap.add_argument(
    "--url",
    action = "store", default = None, type = str,
    help = "URL to visit for more info")
ap.add_argument(
    "-C", "--chdir", metavar = "DIR",
    action = "store", default = None, type = str,
    help = "Change into directory before starting")
ap.add_argument(
    "-W", "--wide",
    action = "store_true", default = False,
    help = "Report on anything, not just on lines changed")
ap.add_argument(
    "--gerrit-message-limit",
    action = "store", default = 30 * 1024, type = int,
    help = "Gerrit's maximum review message size "
    "(matches Gerrit's config change.robotCommentSizeLimit "
    "and defaults to %(default)d)")
ap.add_argument(
    "-u", "--gerrit-ssh-user",
    action = "store", default = None, type = str,
    help = "Gerrit SSH user")
ap.add_argument(
    "-g", "--gerrit-ssh-host",
    action = "store", default = None, type = str,
    help = "Gerrit SSH server host")
ap.add_argument(
    "-P", "--gerrit-ssh-port",
    action = "store", default = 29418, type = int,
    help = "Gerrit SSH server port")
ap.add_argument(
    "-R", "--gerrit-change-number",
    action = "store", default = None, type = int,
    help = "Gerrit Change Number ID")
ap.add_argument(
    "-r", "--gerrit-patchset-number",
    action = "store", default = None, type = int,
    help = "Gerrit Patchset number the change")
ap.add_argument(
    "--gerrit-from-jenkins",
    action = "store_true", default = False,
    help = "Get Gerrit parameters from environment setup by Jenkins")
ap.add_argument(
    "--use-head",
    action = "store_const", const = 'HEAD', dest = 'use',
    help = "Override smart detection, use HEAD")
ap.add_argument(
    "--trace-fns",
    action = "store_true", default = False,
    help = "Print function name and line numbers in log output")
ap.add_argument(
    "--use-work-tree",
    action = "store_const", const = 'wip', dest = 'use',
    help = "Override smart detection, use the work tree")
ap.add_argument("-v", "--verbose",
                dest = "level",
                action = _action_increase_level, nargs = 0,
                help = "Increase verbosity")

args = ap.parse_args()
if args.chdir:
    os.chdir(args.chdir)
if args.trace_fns:
    logging.basicConfig(
        format = "%(levelname)s: %(name)s: %(funcName)s():%(lineno)d: " \
        "%(message)s",
        level = args.level)
else:
    logging.basicConfig(
        format = "%(levelname)s: %(name)s: %(message)s",
        level = args.level)
logging.addLevelName(50, "C")
logging.addLevelName(40, "E")
logging.addLevelName(30, "W")
logging.addLevelName(20, "I")
logging.addLevelName(10, "D")
logging.addLevelName(9, "D2")
logging.addLevelName(8, "D3")
logging.addLevelName(7, "D4")
logging.addLevelName(6, "D5")

local_path = os.path.expanduser(args.path)
logging.debug("local path: %s", local_path)
abspath = os.path.abspath(local_path)
args.scripts_path.append(abspath)
logging.debug("script paths: %s", " ".join(args.scripts_path))

# Find all lint scripts in args.path
config_import(args.scripts_path, re.compile(r"^\.lint\..*\.py$"))
# Find all lint scripts in args.script
for _filename in args.script:
    config_import_file(_filename)
# Sort on the function name, not on the function file/name/path, so
# that it is stable to the content of the file
lint_functions_sorted = sorted(lint_functions.items(), key = lambda x: x[0])
lint_function_names_sorted = [x[0] for x in lint_functions_sorted]
logging.debug("lint functions: %s", ",".join(lint_function_names_sorted))

class repo_c(git.Repo):
    def __init__(self, path):
        git.Repo.__init__(self, path)

    @staticmethod
    def message(message):
        """
        Report a message

        :param str message: line with the message
        """
        print(message)

    def warning(self, message):
        """
        Report a warning line

        :param str message: line with the message, ideally in form::

          FILE:LINE[:COLUMN] MESSAGE

        :param int line_number: (optional) line where the warning was
          found; if provided and it is part of the lines the current
          changeset being verified modified, the warning will be
          reported. Otherwise, it will be ignored (unless -W was
          given).
        """
        context.warnings += 1
        self.message(message)

    def error(self, message):
        """
        Report an error line

        :param str message: line with the message, ideally in form::

          FILE:LINE[:COLUMN] MESSAGE

        :param int line_number: (optional) line where the error was
          found; if provided and it is part of the lines the current
          changeset being verified modified, the error will be
          reported. Otherwise, it will be ignored (unless -W was
          given).
        """
        context.errors += 1
        self.message(message)

    def blockage(self, message):
        """
        Report a blockage line

        :param str message: line with the message, ideally in form::

          FILE:LINE[:COLUMN] MESSAGE
        """
        context.blockage += 1
        self.message(message)

git_repo = repo_c(abspath)
git_repo.relpath = local_path
if git_repo.bare:
    raise RuntimeError("%s: repo is bare, can't work with it")
git_cmd = git_repo.git

# work out what git revision we are dealing with and based of if we
# are using the workign tree (for committing) or a committed version,
# pull out the list of files
if args.use == None:
    if git_repo.is_dirty(untracked_files = False):
        args.use = 'wip'
    else:
        args.use = 'HEAD'

if args.use == 'HEAD':
    logging.info("using head")
    gitrev = str(git_repo.rev_parse('HEAD'))
    commit = next(git_repo.iter_commits())
    filenames = commit.stats.files.keys()
    changedfile_c.gitrev_blame = gitrev
else:
    logging.info("using work tree")
    filenames = subprocess.check_output(
        [ 'git', 'diff-index', '--name-only', 'HEAD' ],
        universal_newlines = True, cwd = git_repo.working_tree_dir)\
        .splitlines()
    changedfile_c.gitrev_blame = "0000000000000000000000000000000000000000"

git_repo.filenames = [ os.path.join(args.path, filename)
                       for filename in filenames ]

logging.debug("Files affected: %s", " ".join(git_repo.filenames))

files = {}

git_repo.wide = args.wide

if args.gerrit_ssh_host or args.gerrit_from_jenkins:
    sys.stdout = tee_c()	# capture print's output

class context_c(object):	# pylint: disable = too-few-public-methods
    inventory = {}

    def __init__(self, name):
        self.name = name
        self.errors = 0
        self.warnings = 0
        self.blockage = 0
        self.inventory[name] = self

context = None
context_global = context_c('global')

def _lint_run(_context, function, repo, _cf):
    if _cf:
        s = "%s: " % _cf.name
    else:
        s = ""
    # So we can access it from multiple places, especially for the name
    global context
    context = _context
    logging.debug("%srunning %s", s, context.name)
    try:
        r = function(repo, _cf)
        if r != None:
            context.errors += r[0]
            context.warnings += r[1]
            context.blockage += r[2]
    except Exception as e:	# pylint: disable = broad-except
        logging.exception("%s: raised exception: %s", context._name, e)
        context.blockage += 1
    context_global.errors += context.errors
    context_global.warnings += context.warnings
    context_global.blockage += context.blockage

for _name, _function in lint_functions_sorted:
    context = context_c(_name)
    # First run the checkers on each file, then later run them on the
    # commit itself
    for _filename in git_repo.filenames:
        _lint_run(context, _function, git_repo,
                  changedfile_c(git_repo, _filename))

    # Now run them on the full commit
    # We do this after the files because we might have found files that
    # activate some decissions on what to run
    _lint_run(context, _function, git_repo, None)

lst = []
if context_global.errors:
    lst.append('errors')
if context_global.warnings:
    lst.append('warnings')
if context_global.blockage:
    lst.append('blockages (some tools missing?)')
if lst:
    msg = " There are " + " and ".join(lst) + ".\n\n"
    if args.url:
        msg += " (" + args.url + ")\n\n"
else:
    msg = " All checks passed"
del files	# close/delete all tempfiles
if args.gerrit_ssh_host or args.gerrit_from_jenkins:
    # feedback via gerrit
    sys.stdout.flush()
    sys.stdout.fp.seek(0)
    _gerrit_feedback(args, context_global.errors, context_global.warnings,
                     context_global.blockage,
                     msg + sys.stdout.fp.read())
    sys.exit(0)
else:
    # Shell usage, returns something to tell what happened
    print(__file__ + ":" + msg)
    if context_global.blockage:
        sys.exit(255)
    if context_global.errors:
        sys.exit(1)
    if context_global.warnings:
        sys.exit(2)
    sys.exit(0)
