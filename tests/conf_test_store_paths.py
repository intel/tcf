#! /usr/bin/python2
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import os

import commonl
import ttbl.store
import ttbl.config

target = ttbl.test_target("t0")
ttbl.config.target_add(target) # store interface added automatically
ttbl.store.paths_allowed["/path1"] = os.path.join(target.state_dir, "test_path1")
ttbl.store.paths_allowed["/path2"] = os.path.join(target.state_dir, "test_path2")
ttbl.store.paths_allowed["/path3"] = os.path.join(target.state_dir, "test_path3")
ttbl.store.paths_allowed["/path4"] = os.path.join(target.state_dir, "test_path4")
commonl.makedirs_p(ttbl.store.paths_allowed["/path2"])
commonl.makedirs_p(ttbl.store.paths_allowed["/path3"])
commonl.makedirs_p(os.path.join(ttbl.store.paths_allowed["/path4"], "subdir1"))
commonl.makedirs_p(os.path.join(ttbl.store.paths_allowed["/path4"], "subdir2"))
commonl.makedirs_p(os.path.join(ttbl.store.paths_allowed["/path4"], "subdir3"))
with open(os.path.join(ttbl.store.paths_allowed["/path2"], 'fileA'),
          "w") as wf:
    wf.write("This is a test")
