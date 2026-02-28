import commonl

import tcfl.tc

class _test(tcfl.tc.tc_c):
    """

    Check if simple static test case with no axis defaults to
    defaults axis an runs ok

    """

    def eval(self):

        import tcfl.orchestrate		# lazy imports on demand
        tcfl.orchestrate.subsystem_setup()

        tmpdir = self.report_file_prefix + "log"
        logdir = self.report_file_prefix + "tmp"
        commonl.makedirs_p(logdir)
        commonl.makedirs_p(tmpdir)
        executor = tcfl.orchestrate.executor_c(
            logdir = logdir, tmpdir = tmpdir, remove_tmpdir = False,
            testcase_paths = [
                "tests/collateral/test_orchestrate_static_no_axes.py",
                #"tests/collateral/test_orchestrate_static_with_axes_pass.py",
            ])
        executor.run()

        # note this executor will have completed and have a top level
        # result; we are NOT passing that to the executor that ran
        # this, so the output might be a wee confusing

        if executor.testcases_pending:
            self.report_fail(
                "after completion, tests are still pending",
                {
                    "test_completed": [
                        tci.name for tci in executor.testcases_completed ],
                    "test_running": [
                        tci.name for tci in executor.testcases_running ],
                    "test_pending": [
                        tci.name for tci in executor.testcases_pending ],
                }, subcase = "pending")
        else:
            self.report_pass(
                "after completion, tests are not pending",
                subcase = "pending")

        if executor.result_discovery:
            self.report_fail(
                "something failed in discovery",
                {
                    "test_completed": executor.testcases_completed,
                    "test_running": executor.testcases_running,
                    "test_pending": executor.testcases_pending,
                }, subcase = "discovery")
        elif executor.result_discovery.passed \
           + executor.result_discovery.errors \
           + executor.result_discovery.failed \
           + executor.result_discovery.blocked \
           + executor.result_discovery.skipped == 0:
            self.report_error(
                "0 testcases report result_discovery; something is wrong",
                subcase = "discovery")

        else:
            self.report_pass("discovery went ok",
                             subcase = "discovery")

        if executor.result.passed \
           + executor.result.errors \
           + executor.result.failed \
           + executor.result.blocked \
           + executor.result.skipped == 0:
            self.report_error(
                "0 testcases report execution; something is wrong",
            subcase = "execution")
        else:
            self.report_pass(
                "execution went ok",
            subcase = "execution")

        self.report_info(f"result discovery: {executor.result_discovery}")
        self.report_info(f"result: {executor.result}")


        with self.subcase("executor_delete"):
            executor.stop()
            self.report_pass("executor deleted")
