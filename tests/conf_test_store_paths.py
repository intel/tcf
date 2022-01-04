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
ttbl.config.target_add(target)
# store interface added automatically -- by target_add()
target.store.target_sub_paths["ro"] = False
target.store.target_sub_paths["rw"] = True
ttbl.store.paths_allowed["/path1"] = os.path.join(target.state_dir, "test_path1")
ttbl.store.paths_allowed["/path2"] = os.path.join(target.state_dir, "test_path2")
ttbl.store.paths_allowed["/path3"] = os.path.join(target.state_dir, "test_path3")
ttbl.store.paths_allowed["/path4"] = os.path.join(target.state_dir, "test_path4")
commonl.makedirs_p(ttbl.store.paths_allowed["/path1"])
commonl.makedirs_p(ttbl.store.paths_allowed["/path2"])
commonl.makedirs_p(ttbl.store.paths_allowed["/path3"])
commonl.makedirs_p(os.path.join(ttbl.store.paths_allowed["/path4"], "subdir1"))
commonl.makedirs_p(os.path.join(ttbl.store.paths_allowed["/path4"], "subdir2"))
commonl.makedirs_p(os.path.join(ttbl.store.paths_allowed["/path4"], "subdir3"))
with open(os.path.join(ttbl.store.paths_allowed["/path2"], 'fileA'),
          "w") as wf:
    wf.write("This is a test")

# create the target-specific ro and rw subpaths in TARGETSTATEDIR,
# make a file in each
ro_path = os.path.join(target.state_dir, "ro")
commonl.makedirs_p(ro_path)
with open(os.path.join(ro_path, 'file'), "w") as wf:
    wf.write("This is a test")

rw_path = os.path.join(target.state_dir, "rw")
commonl.makedirs_p(rw_path)
with open(os.path.join(rw_path, 'file'), "w") as wf:
    wf.write("This is a test")
