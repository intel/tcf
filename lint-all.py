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
import importlib
import logging
import os
import re
import subprocess
import sys
import traceback
import typing
import urllib.parse

import git
import github
import gitlab

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
    two arguments, a Git Repo object and a changedfile
    object.

    Optionally declare a lint_SOMETHING_filter(repo, cf) that returns
    True if it will handle the file described by cf (or if None, the
    whole tree), so the lint_SOMETHING() function is only called for
    the files filtered.

    Optionally declare a variable lint_SOMETHING_name with a string
    naming the linter.

  - have the linter function call cf.warning() or cf.error() to report
    lines of concern [eg: from the output of linter programs] in the
    form FILENAME:[LINE:] MESSAGE; make filenames relative to
    os.getpwd()

    for whole tree checks (when cf == None), use repo.warning(),
    repo.error()

    each call to warning() / error(), tallies up the warnings and errors


"""

lint_functions = {}


def default_filter(_repo, _cf):
    return True

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
        spec = importlib.util.spec_from_file_location(module_name, filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.stdout.flush()
        sys.stderr.flush()
        logging.debug("%s: configuration file imported", filename)
        for symbol in module.__dict__:
            obj = module.__dict__[symbol]
            if callable(module.__dict__[symbol]) \
               and symbol.startswith("lint_") \
               and not symbol.endswith("_name") \
               and not symbol.endswith("_filter"):
                obj_filter = getattr(module, symbol + "_filter",
                                     default_filter)
                shortname =  symbol.replace("lint_run_", "")
                shortname = shortname.replace("lint_", "")
                _symbol = getattr(module, symbol + "_name", shortname)
                config = getattr(module, shortname + "_config", {})
                lint_functions[_symbol] = (obj, obj_filter, shortname, config)

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
        _repo, cf, cmdline,
        regex_error = re.compile(
            r":(?P<line_number>[0-9]+)(:(?P<column_number>[0-9]+))?:"
            r" \[(E\w+[0-9]+|error)\] "),
        regex_warning = re.compile(
            r":(?P<line_number>[0-9]+)(:(?P<column_number>[0-9]+))?: "
            r"\[([WCR]\w+[0-9]+|warning)\] "),
        log = None):
    """Run a generic linter that outputs in standarized way and report

    Most linters can be made to report in the format::

      FILENAME:LINE:COLUMN: [TAG] Message1
      FILENAME:LINE:COLUMN: [TAG] Message2
      FILENAME:LINE:COLUMN: [TAG] Message3
      ...

    Where *:COLUMN* might be optional and *TAG* usually follows something like:

    - *[EWCR]NUMBER*: pylint and co
    - *error*: yamlint...

    :param Pattern regex_error: compiled regular expression
      to match the lines reporting errors that have to be reported; it
      must contain a group match *(?P<line_number>[0-9]+)* to extract
      the line number for.

      If a line is considered as an error, it won't be considered for
      a warning -- to simplify the pattern matching

    :param Pattern regex_warning: same thing, for warnings
    """
    assert isinstance(_repo, git.Repo)
    assert isinstance(cf, changedfile_c)
    assert isinstance(cmdline, list)
    if log:
        assert isinstance(log, logging.Logger)
    else:
        log = _repo.log
    assert isinstance(regex_error, re.Pattern)
    assert isinstance(regex_warning, re.Pattern)

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
        _repo.error("Can't find linter? [%s]" % cmdline[0])
        output = ""
    except subprocess.CalledProcessError as e:
        output = e.output

    _errors = 0
    _warnings = 0
    for line in output.splitlines():
        line = line.strip()
        me = regex_error.search(line)
        mw = regex_warning.search(line)
        if me:
            cf.error(line, int(me.groupdict()["line_number"]))
        elif mw:
            cf.warning(line, int(mw.groupdict()["line_number"]))


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
        print(("W: 'Verified %d' vote skipped as some tools are missing "
              "and can't check it all" % data['labels']['Verified']))
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

def linter_config_get(lintername):
    """
    Return the configuration object for linter @lintername

    The type of this object is specific to each linter. Best thing is
    to make it a dictionary.

    To access this function from a scriptlet:

    >>> import __main__
    >>>
    >>> __main__.linter_config_get('somename')

    FIXME: yep, there have to be a better way than __main__
    """
    return lint_functions[lintername][3]

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
    gl_mr = None

    def __init__(self, repo, filename):

        self.repo = repo
        self.log = logging.getLogger(filename)

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
                self.log.info("blaming")
                output = repo.git.blame('-p', '--', self.name_rel_repo)
            else:
                output = repo.git.blame('-p', changedfile_c.gitrev_blame, '--',
                                        self.name_rel_repo)
            for line in output.splitlines():
                if line.startswith(changedfile_c.gitrev_blame):
                    _, line_start, _ = line.split(" ", 2)
                    self.lines.append(int(line_start))

        self.log.debug("binary:%s deleted:%s lines-changed:%s",
                       self.binary, self.deleted,
                       ",".join([ str(i) for i in self.lines ]))

    def __review_line_report_gitlab(self, category, line_number, message):
        # notes allow a discussion thread that has to be
        # reolved/closed to be created -- better that commit
        # comments, as it allows us to track it
        # Can't get the position thing to work, the gitlab Python
        # API is not passing it and not allowing me to create a
        # discussion object either, like the documentation says.
        color = ""
        if category == 'warning':
            color = "#FFDA02"
        elif category == 'error':
            color = "#FF0000"
        elif category == 'blockage':
            color = "#800080"
        # Can't figure out how not to have the colour code show up
        # according to the markdown spec
        # https://gitlab.devtools.intel.com/help/user/markdown#colors
        print("DEBUG discussions gl_mr id %08x" % id(self.gl_mr))
        self.gl_mr.discussions.create(dict(
            # start a discussion, body of the discussion is whatever
            # this checker said
            body = r"""
**`%s %s`** `%s`
```
%s
```
""" % (context.shortname, category, color, message),
            position = dict(
                line_code = int(line_number),
                base_sha = self.gl_mr.diff_refs['base_sha'],
                start_sha = self.gl_mr.diff_refs['start_sha'],
                head_sha = self.gl_mr.diff_refs['head_sha'],
                new_path = self.name_rel_repo,
                old_path = self.name_rel_repo,
                new_line = int(line_number),
                position_type = 'text',
            ),
            resolvable = True,
        ))

    def _review_line_report_gitlab(self, category, line_number, message):
        try:            
            self.__review_line_report_gitlab(category, line_number, message)
        except gitlab.exceptions.GitlabCreateError as e:
            if '400 (Bad request) "Note {:line_code=>["can\'t be blank",' \
               ' "must be a valid line code"]}" not given' in str(e):
                # problem with no solution so far
                # https://www.google.com/url?sa=t&rct=j&q=&esrc=s&source=web&cd=2&ved=2ahUKEwiTvLOj4sbiAhXnCTQIHdtqCdwQFjABegQIBBAB&url=https%3A%2F%2Fgitlab.com%2Fgitlab-org%2Fgitlab-ce%2Fissues%2F24542&usg=AOvVaw18yIXYaGWmCli9QEGYkRWs
                
                self.log.error("ignoring submission error %s" % e)
                pass

        
    def _review_line_report(self, category, line_number, message):
        if self.gl_mr:
            # There is a gitlab merge request to report to
            self._review_line_report_gitlab(category, line_number, message)
        # FIXME: github must do this too

    def message(self, category, message, line_number = None):
        """
        Report a message

        :param str message: line with the message
        """
        self.repo.message(message, line_number)
        self._review_line_report(category, line_number, message)

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
        if line_number in self.lines or args.wide:
            context.warnings += 1
            self.message('warning', message, line_number)

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
        if line_number in self.lines or args.wide:
            context.errors += 1
            self.message('error', message, line_number)

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
        if line_number in self.lines or args.wide:
            context.blockage += 1
            self.message('blockage', message, line_number)

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
    help = "Add a find where to find .lint.*.py scripts; if "
    "empty, it will clear the current list and start a new one")
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
    "--github-repo",
    action = "store", default = None,
    help = "Github repository the commit we are checking is a pull request")
ap.add_argument(
    "--github-baseurl",
    action = "store", default = None,
    help = "Github API URL (will be autogenerated if based on "
    "--github-repo, but can be overriden with this")
ap.add_argument(
    "--github-commit",
    action = "store", default = None,
    help = "Github commit in --github-repo, update status")
ap.add_argument(
    "--github-token",
    action = "store", default = None,
    help = "Github token to access the API")
ap.add_argument(
    "--github-from-jenkins",
    action = "store_true", default = False,
    help = "Get github values repo and commit from Jenkins environment "
    "(from the pull request builder plugin exporting env vars "
    "ghprbActualCommit and ghprbAuthorRepoGitUrl); token still has "
    "to be passed in the command line")
ap.add_argument(
    "--gitlab-repo",
    action = "store", default = None,
    help = "Gitlab repository for the commit we are checking")
ap.add_argument(
    "--gitlab-mergerequest",
    action = "store", default = None,
    help = "Gitlab merge request in --gitlab-repo to update status")
ap.add_argument(
    "--gitlab-token",
    action = "store", default = None,
    help = "Gitlab token to access the API")
ap.add_argument(
    "--gitlab-from-jenkins",
    action = "store_true", default = False,
    help = "Get gitlab values repo and commit from Jenkins environment "
    "FIXME (from the pull request builder plugin exporting env vars "
    "ghprbActualCommit and ghprbAuthorRepoGitUrl); token still has "
    "to be passed in the command line")
ap.add_argument(
    "--status-detail-url",
    action = "store", default = None,
    help = "Provide an URL with where the user can go to get details "
    "about the execution of a scriptlet; this would be usually the "
    "full output of the scriplet stored in, for example, some jenkins "
    "artifact area. This can use %%(FIELD)s codes to replace the "
    "following fields: context_name, context_shortname, capture_path, "
    "capture_filename "
)
ap.add_argument(
    "--status-pending-url",
    action = "store", default = None,
    help = "Provide an URL with where the user can go to get details "
    "about the execution of a scriptlet; this would be usually the "
    "full output of the scriplet stored in, for example, some jenkins "
    "artifact area. This can use %%(FIELD)s codes to replace the "
    "following fields: context_name, context_shortname, capture_path, "
    "capture_filename "
)
ap.add_argument(
    "--capture",
    action = "store_true", default = False,
    help = "Capture the output of each linter in a file named "
    "by the --capture-template argument"
)
ap.add_argument(
    "--capture-path",
    action = "store", default = "output-%(context_shortname)s.txt",
    help = "Provide an path / filename to which to capture the output "
    "of each linter; the following %%(FIELD)s are available: "
    "context_name, context_shortname"
)
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
args.scripts_path.insert(0, abspath)
# iterate the scripts path and prune it; if there is an empty path,
# delete anything in the list and start fresh; used to reset the defaults
new_path = []
for path in args.scripts_path:
    if path == "" or path == None:
        new_path = []
    new_path.append(path)
args.scripts_path = new_path
logging.debug("script paths: %s", " ".join(args.scripts_path))

# Find all lint scripts in args.path
config_import(args.scripts_path, re.compile(r"^\.lint\..*\.py$"))
# Find all lint scripts in args.script
for _filename in args.script:
    config_import_file(_filename)
# Sort on the function name, not on the function file/name/path, so
# that it is stable to the content of the file
lint_functions_sorted = sorted(list(lint_functions.items()), key = lambda x: x[0])
lint_function_names_sorted = [x[0] for x in lint_functions_sorted]
logging.debug("lint functions: %s", ",".join(lint_function_names_sorted))

class repo_c(git.Repo):

    def __init__(self, path):
        git.Repo.__init__(self, path)
        self.relpath = None
        self.context = None
        self.log = None
        self.wide = None

    def message(self, message, line_number = None):
        """
        Report a message

        :param str message: line with the message
        """
        if line_number:
            line_number_s = str(line_number) + ":"
            # ok, hack, many messages already contain the line number,
            # so do a dirty check and ignore it if so
            if line_number_s in message:
                line_number_s = ""
        else:
            line_number_s = ""
        print((line_number_s + message))
        _context = self.context
        if args.capture and not _context.capturef:
            _context.capturef = open(_context.kws['capture_path'], "w")
        if _context.capturef:
            _context.capturef.write(line_number_s + message + '\n')

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
        context.warnings += 1
        self.message(message, line_number)

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
        context.errors += 1
        self.message(message, line_number)

    def blockage(self, message, line_number = None):
        """
        Report a blockage line

        :param str message: line with the message, ideally in form::

          FILE:LINE[:COLUMN] MESSAGE
        """
        context.blockage += 1
        self.message(message, line_number)

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
    filenames = list(commit.stats.files.keys())
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

# We overload the git repository structure to contain global
# parameters we'll use
git_repo.wide = args.wide
git_repo.context = None
git_repo.log = None

if args.gerrit_ssh_host or args.gerrit_from_jenkins:
    sys.stdout = tee_c()	# capture print's output

class context_c(object):	# pylint: disable = too-few-public-methods
    inventory = {}

    gh_commit = None
    gl_commit = None
    gl_mr = None

    def __init__(self, name, shortname = None):
        self.name = name
        if shortname:
            self.shortname = shortname
        else:
            self.shortname = name
        self.errors = 0
        self.warnings = 0
        self.blockage = 0
        self.inventory[name] = self
        self.capturef = None
        self.kws = dict(
            context_name = self.name,
            context_shortname = self.shortname,
        )
        self.kws['capture_path'] = args.capture_path % self.kws
        self.kws['capture_filename'] = \
            os.path.basename(self.kws['capture_path'])

    @staticmethod
    def _add_s(n):
        if n == 1:
            return ""
        return "s"

    def description(self, cfs_n = -1, cf_tree = False):
        descriptionl = []
        if cfs_n > 0:
            descriptionl.append("%d file%s checked"
                                % (cfs_n, self._add_s(cfs_n)))
        if cf_tree:
            descriptionl.append("tree checked")
        if self.blockage:
            descriptionl.append("%d error%s" %
                                (self.blockage, self._add_s(self.blockage)))
        if self.errors:
            descriptionl.append("%d failure%s" %
                                (self.errors, self._add_s(self.errors)))
        if self.warnings:
            descriptionl.append("%d warning%s" %
                                (self.warnings, self._add_s(self.warnings)))
        if not self.blockage and not self.errors and not self.warnings:
            descriptionl.append("LGTM")

        return ", ".join(descriptionl)

    def github_status_set(self, git_repo, status, description, url):
        # commit and repo, if not specified default to Jenkins'
        # environment if --github-from-jenkins was given
        if args.github_commit == None and args.github_from_jenkins:
            args.github_commit = os.environ.get('ghprbActualCommit', None)
        if args.github_repo == None and args.github_from_jenkins:
            args.github_repo = os.environ.get('ghprbAuthorRepoGitUrl', None)
        if not args.github_commit or not args.github_repo:
            git_repo.log.debug("Not reporting to github")
            return		# Nah, we don't care for it
        # Set the commit description only once, we don't need to do it for
        # every call
        cls = type(self)
        if cls.gh_commit == None:
            gh_baseurl = args.github_baseurl
            gh_url = urllib.parse.urlparse(args.github_repo)
            if not gh_baseurl:
                if gh_url.hostname == "github.com":
                    gh_baseurl = "https://api.github.com"
                else:
                    gh_baseurl = "https://" + gh_url.hostname + "/api/v3"
                git_repo.log.info("github: inferred API url %s", gh_baseurl)
            gh = github.Github(timeout = 120,
                               base_url = gh_baseurl,
                               login_or_token = args.github_token)

            gh_repo = gh.get_repo(str(gh_url.path[1:]), lazy = False)
            cls.gh_commit = gh_repo.get_commit(args.github_commit)

        if url == None:
            url = github.GithubObject.NotSet
        cls.gh_commit.create_status(status, url, description, self.name)

    def _gitlab_status_set(self, git_repo, status, description, url):
        status_map = dict(
            # only statuses known by gitlab API
            pending = 'pending',
            failure = 'failed',
            error = 'failed',
            success = 'success',
        )
        try:
            self.gl_commit.statuses.create({
                'state': status_map[status],
                'name': self.name,
                'target_url': url,
                'description': description
            })
        except gitlab.exceptions.GitlabCreateError as e:
            git_repo.log.error("gitlabCreateError %s", e)


    def status_set(self, git_repo, status, description, url):
        if url:
            git_repo.log.info("status %s: %s [%s]", status, description, url)
        else:
            git_repo.log.info("status %s: %s", status, description)

        if self.gl_commit:
            self._gitlab_status_set(git_repo, status, description, url)
        else:	# FIXME: this needs polishing
            self.github_status_set(git_repo, status, description, url)

    def status_final_set(self, git_repo, url, cfs_n, cf_tree):
        if self.name.startswith("__"):
            return

        description = context.description(cfs_n, cf_tree)
        # Github commit are pending, success, failure, error
        if context.errors:
            # First this, if there is a confirmed failure we want to
            # see it
            status = "failure"
        elif context.blockage:
            status = "error"
        elif context.warnings:
            status = "success"
        else:
            status = "success"

        self.status_set(git_repo, status, description, url)

context = None
context_global = context_c('global')

def _lint_run(function, repo, _cf):
    if _cf:
        s = "%s: " % _cf.name
    else:
        s = ""
    # So we can access it from multiple places, especially for the name
    try:
        context.errors = 0
        context.warnings = 0
        context.blockage = 0
        repo.log.debug("%srunning", s)
        r = function(repo, _cf)
        if r != None:
            context.errors += r[0]
            context.warnings += r[1]
            context.blockage += r[2]
    except StopIteration as e:
        # Doesn't apply to this one
        repo.log.info(e)
    except Exception as e:	# pylint: disable = broad-except
        repo.log.error("%s: raised exception: %s: %s", context.name, e,
                       traceback.format_exc())
        context.blockage += 1
    finally:
        context_global.errors += context.errors
        context_global.warnings += context.warnings
        context_global.blockage += context.blockage

# Are we working with gitlab?
if args.gitlab_repo:
    assert args.use == "HEAD", \
        "Gitlab can be only used with --use-head"
    gl_url = urllib.parse.urlparse(args.gitlab_repo)
    gitlab_baseurl = "https://" + gl_url.hostname
    gl = gitlab.Gitlab(gitlab_baseurl, private_token = args.gitlab_token)
    gl.auth()
    gl_project = gl.projects.get(gl_url.path[1:])
    context_c.gl_commit = gl_project.commits.get(changedfile_c.gitrev_blame)
    changedfile_c.gl_commit = context_c.gl_commit
    context_c.gl_mr = gl_project.mergerequests.get(args.gitlab_mergerequest)
    changedfile_c.gl_mr = context_c.gl_mr
    print("DEBUG discussions gl_mr id %08x" % id(context_c.gl_mr))

else:
    gl = None
    gl_commit = None
    gl_mr = None
    gl_project = None


cfs_all = {}
for _filename in git_repo.filenames:
    try:
        cfs_all[_filename] = changedfile_c(git_repo, _filename)
    except IsADirectoryError:
        logging.warning(f"{_filename}: ignored, it is a directory (submodule?)")
        # happens when we have submodules

for _name, (lint_function, lint_filter, _shortname, _config) \
    in lint_functions_sorted:
    try:
        context = context_c(_name, _shortname)
        git_repo.context = context
        git_repo.log = logging.getLogger(context.name)

        cfs = []
        for _filename in git_repo.filenames:
            if _filename not in cfs_all:
                continue	# means we skipped it because of multiple reasons
            cf = cfs_all[_filename]
            # get a logger with more context
            cf.log = logging.getLogger(git_repo.context.shortname
                                       + ":" + _filename)
            if lint_filter(git_repo, cf):
                cfs.append(cf)
        cf_tree = lint_filter(git_repo, None)

        if not cfs and not cf_tree:
            git_repo.log.info("skipping, no need")
            continue

        cfs_n = len(cfs)
        if args.status_pending_url:
            pending_url = args.status_pending_url % context.kws
        else:
            pending_url = None
        if args.status_detail_url:
            url = args.status_detail_url % context.kws
        else:
            url = None
        # Run the linter on on each file then on the full commit
        #
        # We do this after the files because we might have found files that
        # activate some decissions on what to run
        for cf in cfs:
            context.status_set(git_repo, "pending",
                               "checking file " + cf.name_rel_repo,
                               pending_url)
            _lint_run(lint_function, git_repo, cf)
        if cf_tree:
            context.status_set(git_repo, "pending", "checking tree",
                               pending_url)
            _lint_run(lint_function, git_repo, None)
        context.status_final_set(git_repo, url, cfs_n, cf_tree)

    finally:
        del context
        context = None
        git_repo.context = None
        git_repo.log = None

msg = context_global.description()
if args.url and ( context_global.errors or context_global.warnings or
                  context_global.blockage ):
    msg += " [" + args.url + "]"
del files	# close/delete all tempfiles

if args.gerrit_ssh_host or args.gerrit_from_jenkins:
    # feedback via gerrit
    sys.stdout.flush()
    sys.stdout.fp.seek(0)
    _gerrit_feedback(args, context_global.errors, context_global.warnings,
                     context_global.blockage,
                     msg + "\n" + sys.stdout.fp.read())
    sys.exit(0)
else:
    # Shell usage, returns something to tell what happened
    print((__file__ + ": " + msg))
    if context_global.blockage:
        sys.exit(255)
    if context_global.errors:
        sys.exit(1)
    if context_global.warnings:
        sys.exit(2)
    sys.exit(0)
