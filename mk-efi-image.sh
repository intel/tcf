#! /bin/bash -eu
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# Needs mtools and ed2k-tools installed (for Shell.efi)
#

if [ $# -lt 1 ]; then
    cat 1>&2 <<EOF
E: not enought arguments

Usage: $(basename $0) IMAGENAME [FILE [FILE [...]]]

Generates an EFI system image in a disk called IMAGENAME which at
least will contain an EFI boot shell in efi/boot. Any extra files
added in the command line will be also copied to the root directory of
the image.

Requires the mtools and EDKII packages installed in your system.
EOF
fi

imgfile=${1}
shift

function do_exit()
{
    true
    #rm -rf $tmpdir
}

function do_error()
{
    cat 1>&2 <<EOF
W: ensure you have the mtools and EDKII packages installed in your system

EOF
}

trap 'do_exit' EXIT

trap 'do_error' ERR

#cp efi-hello-world.git/hello.efi $tmpdir/root/efi/boot/bootx64.efi
#for content_dir in ${@:-}; do


# min size
megs=$(
    du -msc $@  /usr/share/edk2/ovmf/Shell.efi /usr/share/edk2/ovmf/Shell.efi \
        | grep total | sed 's/[[:space:]]\+total//'
    )
echo "I: image size ${megs}MB" 1>&2
if [ "$megs" -lt 105 ]; then
    # apparently mininum ~100MiB
    megs=105;
fi
rm -f $imgfile
echo "I: image size estimated at ${megs}MB" 1>&2
dd  if=/dev/zero of=$imgfile bs=$((1024 * 1024)) count=$megs > /dev/null
mkfs.fat -F16 -n "SYSTEM" $imgfile
echo "I: mounting creating drive image" 1>&2

echo "I: copying EFI shell to efi/boot/" 1>&2
mmd -i $imgfile ::efi
mmd -i $imgfile ::efi/boot
dmcopy -i $imgfile /usr/share/edk2/ovmf/Shell.efi ::efi/boot/bootx64.efi
mcopy -i $imgfile /usr/share/edk2/ovmf/Shell.efi ::efi/boot/shellx64.efi
for content in "$@"; do
    echo "I: copying $content to root of image" 1>&2
    mcopy -D oO -i $imgfile -nspb "$content" ::
done
cat 1>&2 <<EOF
I: all done, use

     $ mdir -i $imgfile -/ ::

   to see the image's contents

   Boot in QEMU with:

     $ qemu-system-x86_64 -hda kk.efi  -bios /usr/share/edk2/ovmf/OVMF_CODE.fd

   Tell the EFI BIOS to switch to fs0 and you will find your content there:

     Shell> fs0:
     FS0:\\> dir
     ...

   in there you can run/access your content

EOF
