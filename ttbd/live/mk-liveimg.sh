#! /bin/bash -eux
#
# Usage:
#
# /PATH/mk-liveimg.sh [EXTRACONFIGDIRS]
#
# Makes a live image for installing in a USB key connected to a
# physical computer.
#
# This live image will always boot to the same SW, the
# testcase can do whatever it wants but on power cycle, it will
# restore to what it was.
#
# See the notes on tcf-live.ks for details on how this is implemented.
#
# This script is meant to be run in a work directory MYWORKDIR:
#
# - In MYWORKDIR (or other config dirs CFGDIR1 CFGDIR2) create extra
#   configuration files, if needed:
#
#   - tcf-live-*.pkgs files, containing packages to install (one per
#     line)
#
#   - tcf-live-extra-*.ks files, containing extra kickstarter
#     configuration, used for example, to generate systemd network
#     configuration files for known physical machines (see example
#     file tcf-live-extra-network.ks)
#
#   Invoke as:
#
#   $ /usr/share/tcf/live/mk-imglive.sh MYWORKDIR CFGDIR1 CFGDIR2
#
#   Config files are included in alphabetical order of the file name
#   filename alphabetical order (/path1/tcf-live-02-something.pkgs
#   after /path2/tcf-live-01-otherthing.pkgs) and generate
#   tcf-live-packages.ks and tcf-live-extras.ks in the work directory
#   MYWORKDIR/tcf-live.
#
# - it will create a subdirectory called 'MYWORKDIR/tcf-live' where a
#   cache of downloaded packages will be mainainted; will be re-used
#   on subsequent invocations.
#
# - it will create MYWORKDIR/tcf-live/tcf-live.iso with the iso image
#
#   This image can be burnt to a USB dongle with:
#
#     $ livecd-iso-to-disk --format --reset-mbr ISOFILE DESTDEV
#
# - the image can be booted as a CDROM in QEMU
#
#   $ qemu-img create -q -f qcow2 -o size=10G file.qcow2
#   # qemu-system-x86_64 \
#        -enable-kvm \
#        -m 2048 \
#        -usb \
#        -drive file=tcf-live/tcf-live.iso,if=virtio,aio=threads,media=cdrom \
#        -drive file=file1.qcow2,serial=TCF-home,if=virtio,aio=threads
#        -drive file=file2.qcow2,serial=TCF-swap,if=virtio,aio=threads
#
# - the image will mount a disk with serial number "TCF-home" or a
#   partition with label name "TCF-home" to /home after formatting it
#   to btrfs.
#
#   For doing it the fist time in a physical target, just boot and use
#   parted to carve out a partition:
#
#     $ parted DEVICE -s mklabel gpt	             # make a new partition table
#     $ parted DEVICE -s mkpart logical linux-swap 0% 10G # make a partition
#     $ parted DEVICE -s name 1 TCF-swap             # name it
#     $ parted DEVICE -s mkpart logical btrfs 10G 100% # make a partition
#     $ parted DEVICE -s name 2 TCF-home             # name it
#
#   On virtual machines, create a physical disk and attach it named
#   TCF-home:
#
#     $ qemu-img create -q -f qcow2 -o size=10G file.qcow2
#
#   and pass to QEMU:
#
#     ... \
#     -drive file=tcf-live/tcf-live.iso,if=virtio,aio=threads,media=cdrom \
#     -drive file=file.qcow2,serial=TCF-home,if=virtio,aio=threads \
#     ...
#
#   - Swap will be added if it has TCF-swap as a serial-number/label
#

dirname=$(dirname $(readlink -e $0))

if ! [ -d tcf-live ]; then
    echo "W: $PWD/tcf-live cache non-existing, recreating" 1>&2
    mkdir -p tcf-live
fi
cd tcf-live


ks_files=
for dir in $dirname $@; do
    ks_files="$ks_files $dir/tcf-live-repos*.ks"
done
sorted_ks_files=$(\
    python3 \
      -c"import os, sys; print(' '.join(sorted(sys.argv[1:], key = os.path.basename)))" \
      $ks_files)
rm -f tcf-live-repos.ks
touch tcf-live-repos.ks
for file in $sorted_ks_files; do
    [ -r $file ] || continue
    echo "I: $file: reading for extra config"
    echo "# from $file" >> tcf-live-repos.ks
    cat $file >> tcf-live-repos.ks
done



# Sort the list of files describing packages by file name, so they are
# properly ordered
pkgs_files=
for dir in $dirname $@; do
    pkgs_files="$pkgs_files $dir/tcf-live-*.pkgs"
done
sorted_pkg_files=$(\
    python3 \
      -c"import os, sys; print(' '.join(sorted(sys.argv[1:], key = os.path.basename)))" \
      $pkgs_files)
rm -f tcf-live-packages.ks
echo %packages > tcf-live-packages.ks
for file in $sorted_pkg_files; do
    [ -r $file ] || continue
    echo "I: $file: reading for extra packages"
    echo "# from $file"  >> tcf-live-packages.ks
    sed 's/#.*$//g' $file >> tcf-live-packages.ks
done
echo %end >> tcf-live-packages.ks


ks_files=
for dir in $dirname $@; do
    ks_files="$ks_files $dir/tcf-live-extra*.ks"
done
sorted_ks_files=$(\
    python3 \
      -c"import os, sys; print(' '.join(sorted(sys.argv[1:], key = os.path.basename)))" \
      $ks_files)
rm -f tcf-live-extras.ks
touch tcf-live-extras.ks
for file in $sorted_ks_files; do
    [ -r $file ] || continue
    echo "I: $file: reading for extra config"
    echo "# from $file" >> tcf-live-extras.ks
    cat $file >> tcf-live-extras.ks
done

rm -f tcf-live.iso
# note tcf-live.ks will include the files we created here
# give -E to sudo so the proxy environment we have set is included
sudo -E livecd-creator -vvv --config=$dirname/tcf-live.ks --fslabel=tcf-live \
     --cache=$PWD/cache --tmpdir=$PWD/tmp
