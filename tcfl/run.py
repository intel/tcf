#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Most of this code borrows from the original tcfl/tc.py, reshaping
# how it works to be completely scalable as a remote distributed
# resource orchestrator.

"""
Execution engine
================

The following is implemented by this module:

- discovery of testcases to run

- discovery of available targets where to run testcases

- pairing of testcase/target-groups

  - axes permutation generator

  - target group permutation generator

- allocation of targets needed by each testcase

- launching the testcase as target group is allocated

- collecting and reporting results


Workflow
--------

This is done with the following processes:

- 1 main process: starts the process

- 1 allocator subprocess: allocates and keeps alive current
  allocations (taking input from the allocator_queue)

- N worker subprocesses: execute the actual testcases (taking input
  from the work_queue)

A testcase execution starts with the main process by queing in the
work_queue a request to discover the testcase's axes.

A worker subprocess will start the axes discovery process, which
iterates all the possible permutations with FIXME axes_iterate(); for
each axes permutation, the testcase object is cloned and a static run
is scheduled.

Another worker process will run the static run of each testcase. In
the static run the configure and build phases of the testcase are
executed (eg: those that do not need the targets). When those are
complete, the systems schedules N allocation of targets groups
(depending on how many concurrent executions on target groups have
been configured) [cloning the testcase for each]. If the testcase is
purely static (no execution on targets), this part is skipped.

The allocator process picks up the allocation request
(_alloc_create()) and proceeds to allocate with the servers; when the
allocation of each target group is complete, it schedules the
execution of the testcase on the testgroup just allocated
(_worker_run_tg).

This is picked up by a worker process which execute on the targets;
when complete, the targets are released.


Pending
-------

"""

import copy
import pickle
import collections
import concurrent.futures
import contextlib
import itertools
import json
import os
import pprint
import queue
import logging
import random
import time
import types
import sys


import tcfl
import commonl

log_exec = logging.getLogger("run")

