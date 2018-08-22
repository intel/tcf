#! /usr/bin/python2
from __future__ import print_function
import collections
import glob
import os

import pylint.lint
import pylint.reporters
import pylint.reporters.ureports.nodes

import tcfl.tc

@tcfl.tc.tags(report_always = True)
class _run(tcfl.tc.tc_c, pylint.reporters.BaseReporter):
    # pylint: disable = too-many-instance-attributes
    """
    Runs pylint on the code base, reporting on the issues found and
    code statistics

    The lint is done in four separate runs, grouping related code and then
    aggegating all the statistics of the four passes.

    Uses pylint as a library, providing a reporter (this same class)
    which pylint then calls :meth:handle_message: to report individual
    issues and :meth:display_reports: to display the summaries.
    """

    def __init__(self, name, tc_file_path, origin):
        tcfl.tc.tc_c.__init__(self, name, tc_file_path, origin)
        pylint.reporters.BaseReporter.__init__(self)

        self.errors = 0
        self.warnings = 0
        self.info = 0

        # display_reports() will use this to parse the tables given
        self.stats = {}
        self.current_title = None
        self.current_table = None
        self.current_table_cols = None
        self.current_table_col = None
        self.current_table = None
        self.current_table_row = None

        # This contain the final aggregated code statistics from the
        self.mbcs = collections.defaultdict(int)
        self.mbid = collections.defaultdict(int)
        self.raw_metrics = collections.defaultdict(int)

    def handle_message(self, msg):
        """
        Callback for pylint to report an issue in file/line/columnt
        """
        #print("DEBUG ", msg)
        if msg.C == "W":
            reporter = self.report_info
            level = 2
            self.warnings += 1
        elif msg.C == "E":
            reporter = self.report_fail
            level = 2
            self.errors += 1
        elif msg.C == "C":
            reporter = self.report_info
            level = 2
            self.info += 1
        else:
            reporter = self.report_info
            level = 2
            self.info += 1
        reporter("%s:%d: %s/%s: %s" % (msg.path, msg.line, msg.msg_id,
                                       msg.symbol, msg.msg), level = level)

    def _vnode_table_close(self):
        if self.current_table and self.current_table_row:
            self.current_table.append(self.current_table_row)
        self.current_table_cols = None
        self.current_table_col = None
        self.current_table = None
        self.current_table_row = None

    def _display_vnode(self, level, vnode):
        if isinstance(vnode, pylint.reporters.ureports.nodes.Text):
            #print(" " * level + "item text", vnode, vnode.data)
            if self.current_table_cols:
                if self.current_table_col < self.current_table_cols:
                    self.current_table_row.append(vnode.data)
                    #print(" " * level + "col", self.current_table_col,
                    #      "row", self.current_table_row)
                    self.current_table_col += 1
                if self.current_table_col == self.current_table_cols:
                    self.current_table.append(self.current_table_row)
                    self.current_table_row = []
                    self.current_table_col = 0
        elif isinstance(vnode, pylint.reporters.ureports.nodes.Title):
            vnode_child = vnode.children[0]
            self.current_title = vnode_child.data
            #print(" " * level + "title text", vnode, self.current_title)
            self._vnode_table_close()
        elif isinstance(vnode, pylint.reporters.ureports.nodes.Section):
            #print(" " * level + "Section", vnode)
            self._vnode_table_close()
        elif isinstance(vnode, pylint.reporters.ureports.nodes.Table):
            self._vnode_table_close()
            self.current_table_cols = vnode.cols
            self.current_table_col = 0
            self.stats[self.current_title] = []
            self.current_table = self.stats[self.current_title]
            self.current_table_row = []
            #print(" " * level + "new table", self.current_table)
        else:
            #print(" " * level + "item type", type(vnode).__name__)
            pass
        for child in vnode:
            self._display_vnode(level + 1, child)

    # Just here to fire if pylint calls it, that it shouldn't
    def _display(self, layout):
        raise NotImplementedError()

    # Parsing this report is hell --
    #
    # Really ugly parsing of the vnode tree -- I would have
    # hoped the data for the reports woudl have been reported as a
    # Python data structure...oh well
    #
    # The hierarchy is somethign like:
    #
    # Section
    #  Title
    #    Text
    #  Table
    #    Text
    #    Text
    #    ...
    #
    # From there we need to figure out how to break in proper
    # individual tables. Bleh.

    def display_reports(self, layout):
        """
        Callback for pylint to report run's summaries
        """
        # extract the data from the tree, recursively
        self._display_vnode(0, layout)
        self._vnode_table_close()
        # Ok, now let's convert those stats tables to python
        # dictionaries that are easier to work with -- only the ones
        # we care for
        for _type, number, dummy_previous, dummy_difference \
            in self.stats['Messages by category'][1:]:
            self.mbcs[_type] += int(number)
        for _id, number in self.stats['Messages'][1:]:
            self.mbid[_id] += int(number)
        for _type, number, _, _, _ in self.stats['Raw metrics'][1:]:
            self.raw_metrics[_type] += int(number)


    def eval(self):

        _src = os.path.abspath(__file__)
        _srcdir = os.path.join(os.path.dirname(_src), "..")
        _args = [ "-r", "y", "--rcfile=" + _srcdir + "/.pylintrc" ]
        _python_path = os.environ.get('PYTHONPATH', '')
        commonl_path = os.path.join(_srcdir, "commonl")
        tcfl_path = os.path.join(_srcdir, "tcfl")
        ttbl_path = os.path.join(_srcdir, "ttbl")

        for paths, files in [
                #(
                #    lint-all code, python3, so we skip it for now,
                #    as we cannot merge it in
                #    [],
                #    [ 'lint-all.py' ] + glob.glob(".lint.*.py")
                #),
                (
                    # Utilities
                    [ commonl_path, tcfl_path ],
                    [
                        _srcdir + '/conf.py', _srcdir + '/setup.py',
                        _srcdir + '/tcf-run-mk-zephyr-boards-by-toolchain.py'
                    ] + glob.glob(_srcdir + r'/test_*\.py')
                ),
                (
                    # Client code
                    [ commonl_path, tcfl_path ],
                    [ _srcdir + '/commonl', _srcdir + '/tcfl' ]
                    + glob.glob(_srcdir + r"/examples/*\.py")
                    + glob.glob(_srcdir + r"/sketch/*\.py")
                    + glob.glob(_srcdir + r"/zephyr/*\.py")
                ),
                (
                    # Server code
                    [ commonl_path, ttbl_path ],
                    [ _srcdir + '/ttbd/ttbl' ]
                    + glob.glob(_srcdir + r"/ttbd/*\.py")
                    + glob.glob(_srcdir + r"/ttbd/zephyr/*\.py")
                    + glob.glob(_srcdir + r"/ttbd/tests/*\.py")
                ),
        ]:
            os.environ['PYTHONPATH'] = ":".join([ _python_path ] + paths)
            pylint.lint.Run(_args + files, reporter = self, exit = False)

        for key, val in self.mbcs.iteritems():
            self.report_data("Code statistics", key, val)
        for key, val in self.raw_metrics.iteritems():
            self.report_data("Code statistics", key, val)
        for key, val in sorted(self.mbid.iteritems(), key = lambda x: x[1]):
            self.report_data("PYLint Messages", key, val)

        if False and self.mbcs['error'] > 0:
            # We won't error yet as we have false error negatives we
            # still haven't been able to kill and it is not
            # necessarily an error
            raise tcfl.tc.failed_e("%d errors found" % self.mbcs['error'])
        else:
            self.report_info("%d errors found" % self.mbcs['error'])

    @staticmethod
    def cleanup():	# pylint: disable = missing-docstring
        pass
