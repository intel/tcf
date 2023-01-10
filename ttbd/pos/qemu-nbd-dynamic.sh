#! /bin/sh -eu
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Connect a QEMU QCOW2 image via NBD dynamically allocating the NBD
# device (which is printed to stdout)
#
# If no available devices are found, then errors out
#
#   $ dev=$(qemu-nbd-dynamic.sh -r somefile.qcow2)
#   ...use...
#   $ qemu-nbd -d $dev
#
# Note you need membership of group disk (if not root) in most distros
# and access to /var/lock
#
#   $ ls -l /dev/nbd1
#   brw-rw----. 1 root disk 43, 32 Jan  6 18:30 /dev/nbd1


args="$@"
# List available NBDs, filtering out partition devices (eg: nbd2p3)
nbds=$(ls -1 /dev/nbd* | grep "nbd[0-9]\+$")
tried_nbds=""
for dev in $nbds; do
    size=$(lsblk --nodeps --noheading --bytes --output size $dev)
    # if used (size != 0) or already tried, skip it; if zero or empty
    # (deps on kernel version), it's available
    if [ ${size:-0} != 0 ] || echo "$tried_nbds" | grep -qw $dev; then
        continue		# if size != 0, it is being used
    fi
    echo "I: trying NBD device $dev" 1>&2
    # who is already taken? lsblk SIZE shows 0B means it is free
    if ! qemu-nbd --fork -c $dev $args; then
        tried_nbds="$dev $tried_nbds"
        echo "W: $dev: failed, trying another one" 1>&2
        continue
    fi
    echo $dev
    exit 0
done
echo "E: no free NBD devices available" 1>&2
exit 1
