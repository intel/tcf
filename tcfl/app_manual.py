#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import tcfl.app

class app_manual(tcfl.app.app_c):
    """
    This is an App Builder that tells the system the testcase will
    provide instructions to configure/build/deploy/eval/clean in the
    testcase methods.

    It is used when we are combining App Builders to build for some
    BSPs with manual methods. Note it can also be used to manually
    adding stubbing information with:

    >>> for bsp_stub in 'BSP1', 'BSP2', 'BSP3':
    >>>        target.stub_app_add(bsp_stub, app_manual, "nothing")

    """
    pass

    # There are no methods needed. All the functionality has to be
    # manually implemented in configure/build/deploy/eval/clean*()
    # methods by the testcase class.
