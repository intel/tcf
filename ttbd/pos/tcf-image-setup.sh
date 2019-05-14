#! /bin/bash -eu
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0


function help() {
    cat <<EOF
$progname DIRECTORY IMAGEFILE [IMAGETYPE]

Clear Linux:

  $ wget https://download.clearlinux.org/releases/29390/clear/clear-29390-live.img.xz
  $ $progname clear:live:29390::x86_64 clear-29390-live.img.xz

Clear Linux Desktop:

  $ wget https://download.clearlinux.org/releases/29400/clear/clear-29400-live-desktop.iso.xz
  $ $progname clear:desktop:29400::x86_64 clear-29400-live.img.xz

Clear Linux (older versions):

  $ wget https://download.clearlinux.org/releases/25930/clear/clear-25930-live.img.xz
  $ $progname clear:live:25930::x86_64 clear-25930-live.img.xz clear

Yocto:

  $ wget http://downloads.yoctoproject.org/releases/yocto/yocto-2.5.1/machines/genericx86-64/core-image-minimal-genericx86-64.wic
  $ $progname yocto:core-image-minimal:2.5.1::x86_64 core-image-minimal-genericx86-64.wic

Fedora:

  $ https://mirrors.rit.edu/fedora/fedora/linux/releases/29/Workstation/x86_64/iso/Fedora-Workstation-Live-x86_64-29-1.2.iso
  $ $progname fedora:live:29::x86_64 Fedora-Workstation-Live-x86_64-29-1.2.iso

Ubuntu:

  $ wget http://releases.ubuntu.com/18.10/ubuntu-18.10-desktop-amd64.iso
  $ $progname ubuntu:live:18.10::x86_64 ubuntu-18.10-desktop-amd64.iso

rootfsimage:

  takes a whole image that is a single root filesystem

Using QEMU (Any other distros, Ubuntu, SLES, etc...)

1. create a 20G virtual disk:

     $ qemu-img create -f qcow2 ubuntu-18.10.qcow2 20G
     $ qemu-img create -f qcow2 Fedora-Workstation-29.qcow2 20G

2. Install using QEMU all with default options (click next). Power
   off the machine when done instead of power cycling

     $ qemu-system-x86_64 --enable-kvm -m 2048 -hdah ubuntu-18.10.qcow2 -cdrom ubuntu-18.10-desktop-amd64.iso
     $ qemu-system-x86_64 --enable-kvm -m 2048 -hda Fedora-Workstation-29.qcow2 -cdrom Fedora-Workstation-Live-x86_64-29-1.2.iso

   Key thing here is to make sure everything is contained in a
   single partition (first partition).

   For Ubuntu 18.10:
     - select install
     - select any language and keyboard layout
     - Normal installation
     - Erase disk and install Ubuntu
     - Create a user 'Test User', with any password
     - when asked to restart, restart, but close QEMU before it
       actually starts again

   For Fedora 29:
     - turn off networking
     - select install to hard drive
     - select english keyboard
     - select installation destination, "CUSTOM" storage configuration
       > DONE
     - Select Standard partition
     - Click on + to add a partition, mount it on /, 20G in size
       (the system later will add boot and swap, we only want what goes
       in the root partition).
       Select DONE
     - Click BEGIN INSTALLATION
     - Click QUIT when done
     - Power off the VM

3. Create image:

     $ $progname ubuntu:desktop:18.10::x86_64 ubuntu-18.10.qcow2

Forcing things (set environment variables)

ROOT_PARTITION   force the root partition to be that number (1, 2, 3...)
BOOT_PARTITION   force the boot partition to be that number (1, 2, 3...)

ROOT_MOUNTOPTS   use these root mount options (default to ext*'s
                 noload; use norecovery for xfs)

BOOT_MOUNTOPTS   use these boot mount options (default to empty)

EOF
}

progname=$(basename $0)

if [ $# -lt 2 -o $# -gt 3 ]; then
    help 1>&2
    exit 1
fi

destdir=$1
image_file=$2
image_type=${3:-}
tmpdir=${TMPDIR:-`mktemp -d $progname-XXXXXX`}

trap cleanup EXIT

function info() {
    echo I: "$@" 1>&2
}

function warning() {
    echo W: "$@" 1>&2
}

function error() {
    echo E: "$@" 1>&2
    exit 1
}

loop_dev=""
mounted_dirs=""
function cleanup() {
    for mounted_dir in $mounted_dirs; do
        info unmounting $mounted_dir
        sudo umount -l $mounted_dir
    done
    if ! [ -z "$loop_dev" ]; then
        sudo losetup -d $loop_dev
    fi
    if ! [ -z "${qemu_nbd_pid:-}" ]; then
        sudo kill $qemu_nbd_pid
        sleep 1s
        sudo kill -9 $qemu_nbd_pid 2> /dev/null || :
    fi
    if [ "$tmpdir" != "${TMPDIR:-}" ]; then
        # we made it, we wipe it
        info removing tmpdir $tmpdir
        rm -rf $tmpdir
    fi
}

if echo $image_file | grep -q \.xz$; then
    info decompressing $image_file
    xz -kd $image_file
    image_file=${image_file%%.xz}
fi

boot_part=""
root_part=""
base=$(basename $image_file)
if [ -z "$image_type" ]; then
    case "$base" in
        android-*.iso)
            image_type=android
            ;;
        *qcow2)
            image_type=qcow2
            nbd_dev=/dev/nbd0
            ;;
        tcf-live.iso)
            image_type=tcflive;;
        Fedora-Workstation-Live-*.iso)
            image_type=fedoralive;;
        ubuntu-*.iso)
            # assuming these are common
            image_type=debian;;
        clear-*-live-*.iso)
            image_type=clear_live_iso
            ;;
        # clear, yocto core image minimal
        clear*)
            image_type=clear2;;
        core*wic)
            image_type=yocto;;
        Fedora-*)
            image_type=fedora;;
        *rootfs.wic)
            image_type=rootfswic;;

        *)
            error Unknown image type for $image_file
            help 1>&2
            exit 1
    esac
fi

case "$image_type" in
    # clear, yocto core image minimal
    clear)
        boot_part=p${BOOT_PARTITION:-1}
        root_part=p${ROOT_PARTITION:-2}
        ;;
    # Newer clear versions
    clear2)
        boot_part=p${BOOT_PARTITION:-1}
        root_part=p${ROOT_PARTITION:-3}
        ;;
    clear_live_iso)
        root_part=p${ROOT_PARTITION:-1}
        ;;
    yocto)
        boot_part=p${BOOT_PARTITION:-1}
        root_part=p${ROOT_PARTITION:-2}
        ;;
    debian|fedoralive|tcflive)
        root_part=p${ROOT_PARTITION:-1}
        ;;
    rootfswic)
        boot_part=p${BOOT_PARTITION:-1}
        root_part=p${ROOT_PARTITION:-2}
        ;;
    qcow2)
        if [ -z "${BOOT_PARTITION:-}" ]; then
            boot_part=
        else
            boot_part=p${BOOT_PARTITION}
        fi
        root_part=p${ROOT_PARTITION:-1}
        ;;
    android|rootfsimage)
        ;;
    *)
        error Unknown image type for $image_file
        help 1>&2
        exit 1
esac

if [ $image_type = qcow2 ]; then
    sudo modprobe nbd
    # can't really use -P, it fails on some when doing -P2
    sudo qemu-nbd -c $nbd_dev -r $image_file &
    # Get the PID of the process run by sudo by detecting who is using
    # the lock file. Might take a while to start -- yeh, this is kinda
    # race condition
    sleep 3s
    qemu_nbd_pid=$(sudo lsof -t /var/lock/qemu-nbd-$(basename $nbd_dev))
    root_part=${nbd_dev}$root_part
    if ! [ -z "${boot_part:-}" ]; then
        boot_part=${nbd_dev}$boot_part
    fi
    info QEMU NBD at $qemu_nbd_pid
else
    loop_dev=$(sudo losetup --show -fP $image_file)
    info loop device $loop_dev
    lsblk $loop_dev
fi

root_fstype=ext4
mkdir $tmpdir/root
set -e
if [ $image_type = debian ]; then
    mkdir -p $tmpdir/iso $tmpdir/root
    sudo mount -o loop ${loop_dev}p1 $tmpdir/iso
    mounted_dirs="$tmpdir/iso ${mounted_dirs:-}"
    info mounted ${loop_dev}${root_part} in $tmpdir/iso

    squashfs_file=$(find $tmpdir/iso -iname filesystem.squashfs)
    sudo mount -o loop $squashfs_file $tmpdir/root
    info mounted $squashfs_file in $tmpdir/root
    mounted_dirs="$tmpdir/root ${mounted_dirs:-}"

elif [ $image_type = android ]; then

    mkdir -p $tmpdir/iso
    sudo mount -o loop ${loop_dev} $tmpdir/iso
    mounted_dirs="$tmpdir/iso ${mounted_dirs:-}"
    info mounted ${loop_dev} in $tmpdir/iso

elif [ $image_type == clear_live_iso ]; then

    # Newer clear versions
    # losetup -Pf clear-live....iso
    # mount /dev/loopXp1 /mnt
    # ls -l /mnt
    #drwxr-xr-x. 1 root root 2048 May 10 14:17 EFI
    #drwxr-xr-x. 1 root root 2048 May 10 14:17 images
    #drwxr-xr-x. 1 root root 2048 May 10 14:17 isolinux
    #drwxr-xr-x. 1 root root 2048 May 10 14:17 kernel
    #drwxr-xr-x. 1 root root 2048 May 10 14:17 loader
    # no need for p0, all in p1
    # /mnt/images/rootfs.img -> image
    # mkdir ROOT/boot
    # cp /mnt/EFI ROOT/boot/EFI
    # cp /mnt/loader ROOT/boot/loader
    mkdir -p $tmpdir/iso
    sudo mount -o loop ${loop_dev}p1 $tmpdir/iso
    mounted_dirs="$tmpdir/iso ${mounted_dirs:-}"
    info mounted ${loop_dev}p1 in $tmpdir/iso

    sudo mount -r -o loop $tmpdir/iso/images/rootfs.img $tmpdir/root
    info mounted $tmpdir/iso/rootfs.img $tmpdir/root
    mounted_dirs="$tmpdir/root ${mounted_dirs:-}"

elif [ $image_type == fedoralive -o $image_type == tcflive ]; then

    mkdir -p $tmpdir/iso $tmpdir/squashfs
    sudo mount -o loop ${loop_dev}p1 $tmpdir/iso
    mounted_dirs="$tmpdir/iso ${mounted_dirs:-}"
    info mounted ${loop_dev}${root_part} in $tmpdir/iso

    sudo mount -o loop $tmpdir/iso/LiveOS/squashfs.img $tmpdir/squashfs
    mounted_dirs="$tmpdir/squashfs ${mounted_dirs:-}"
    info mounted $tmpdir/iso/LiveOS/squashfs.img in $tmpdir/squashfs

    # Mount the root fs
    # use sudo test to test because the mount point might allow no
    # access to the current user.
    if sudo test -r $tmpdir/squashfs/LiveOS/rootfs.img; then
        sudo mount -r -o loop $tmpdir/squashfs/LiveOS/rootfs.img $tmpdir/root
        info mounted $tmpdir/squashfs/LiveOS/rootfs.img in $tmpdir/root
    elif sudo test -r $tmpdir/squashfs/LiveOS/ext3fs.img; then
        # norecovery: if the ext3 fs has a dirty log, we don't want to do it now
        sudo mount -o norecovery,loop $tmpdir/squashfs/LiveOS/ext3fs.img $tmpdir/root
        info mounted $tmpdir/squashfs/LiveOS/ext3fs.img in $tmpdir/root
    else
        error "BUG! dunno how to mount the root file system (no rootfs.img or ext2fs.img)"
    fi
    mounted_dirs="$tmpdir/root ${mounted_dirs:-}"
elif [ $image_type == qcow2 ]; then

    sudo mount -r -o ${ROOT_MOUNTOPTS:-noload} ${root_part} $tmpdir/root
    info mounted ${root_part} in $tmpdir/root
    # do this after mounting works better, sometimes fails otherwise
    root_fstype=$(lsblk -n -o fstype ${root_part})
    mounted_dirs="$tmpdir/root ${mounted_dirs:-}"

elif [ $image_type == rootfsimage ]; then

    sudo mount ${loop_dev} $tmpdir/root
    info mounted ${loop_dev} in $tmpdir/root XX1
    # do this after mounting works better, sometimes fails otherwise
    root_fstype=$(lsblk -n -o fstype ${loop_dev})
    mounted_dirs="$tmpdir/root ${mounted_dirs:-}"

else

    sudo mount ${loop_dev}${root_part} $tmpdir/root
    info mounted ${loop_dev}${root_part} in $tmpdir/root XX2
    # do this after mounting works better, sometimes fails otherwise
    root_fstype=$(lsblk -n -o fstype ${loop_dev}${root_part})
    mounted_dirs="$tmpdir/root ${mounted_dirs:-}"

fi

# Need to copy the boot kernel to root/boot before we mount boot ontop
# of root/boot
if [ $image_type = debian ]; then
    dir=$(dirname $squashfs_file)
    kversion=$(file $dir/vmlinuz | sed  -e 's/^.* version //' -e 's/ .*//')
    cp $dir/initrd $destdir/boot/initramfs-$kversion
    cp $dir/vmlinuz $destdir/boot/vmlinuz-$kversion
fi

if ! [ -z "$boot_part" ]; then
    # clear does this
    # 'auto' is used this a placeholder for a default option that
    # otherwise is doing no option
    sudo mount -o ${BOOT_MOUNTOPTS:-auto} ${loop_dev}${boot_part} $tmpdir/root/boot
    mounted_dirs="$tmpdir/root/boot ${mounted_dirs:-}"
    info mounted ${loop_dev}${boot_part} in $tmpdir/root/boot
fi

# This assumes we have mounted the boot partition on root/boot, to get
# all the boot goodies
if [ $image_type == android ]; then

    mkdir -p $destdir/android/data $destdir/boot/loader/entries
    cp \
        $tmpdir/iso/initrd.img \
        $tmpdir/iso/kernel \
        $tmpdir/iso/ramdisk.img \
        $tmpdir/iso/system.sfs \
        $destdir/android/
    chmod 0644 $destdir/android/*
    chmod ug=rwx,o=x $destdir/android/data
    sudo chown root:root $destdir/android -R
    info android: made squashfs based root filesystem

    # Now, here we cheat a wee bit -- we make this look like a
    # traditional Linux boot environment so the code in
    # tcfl.pos.boot_config can pick it up and make it work with no changes
    (
        cd $destdir/boot
        sudo ln ../android/kernel kernel
        sudo ln ../android/initrd.img initrd.img
    )

    # Make this fake boot entries so the POS code can decide what to
    # boot and how
    cat > $destdir/boot/loader/entries/android.conf <<EOF
title Android
linux /kernel
initrd /initrd.img
options quiet root=/dev/ram0 androidboot.selinux=permissive vmalloc=192M buildvariant=userdebug SRC=/android
EOF
    info android: faked Linux-like /boot environment

elif ! [ -d $destdir ]; then

    sudo install -m 0755 -d $destdir
    info created $destdir, transferring
    sudo tar c --selinux --acls --xattrs -C $tmpdir/root . \
        | sudo tar x --selinux --acls --xattrs -C $destdir/.
    info $destdir: diffing verification
    sudo diff  --no-dereference -qrN $tmpdir/root/. $destdir/.
    info $destdir: setting up
    if [ $image_type == clear_live_iso ]; then
        sudo mkdir $destdir/boot
        sudo cp -a $tmpdir/iso/EFI $tmpdir/iso/loader $destdir/boot
        # we need to remove the initrd activation, as that's what
        # triggers the installation process 
        info $destdir: disabling installation process
        sudo sed -i 's/^initrd/# Commented by $@#initrd/' \
             $destdir/boot/loader/entries/*.conf 
    fi

else

    warning assuming image already in $destdir, setting up

fi


# Remove the root password and unset the counters so you are not
# forced to change it -- we want passwordless login on the serial
# console or anywhere we access the test system.

for shadow_file in \
    $destdir/usr/share/defaults/etc/shadow \
    $destdir/etc/shadow; do
    if sudo test -r $shadow_file; then
        sudo sed -i 's/root:.*$/root::::::::/' $shadow_file
        info $shadow_file: removed root password and reset counters
    fi
done

file=etc/pam.d/common-auth
if [ -r $destdir/$file ]; then
    # SuSE SLES seems to be configuring PAM so a passwordless root
    # acount doesn't work; tweak it
    if ! grep -q "pam_unix.so.*nullok" $destdir/$file; then
        info "$file: allowing login to accounts with no password (adding 'nullok')"
        sudo sed -i 's/pam_unix.so/pam_unix.so\tnullok /' $destdir/$file
    fi
fi

#
# Fixup / harcode serial login consoles
#
tty_devs="ttyUSB0 ttyS6 ttyS0 ${TTY_DEVS_EXTRA:-}"

# On new distros, systemd enabled
if [ -d $destdir/etc/systemd/system/getty.target.wants ] \
   || [ -d $destdir/usr/lib/systemd/system/getty.target.wants ]; then
    # Harcode enable getty on certain devices
    #
    # Disable serial-getty@.service's BindTo -- this is needed so
    # we can have a common image that works in many platforms that
    # may not have the device without waiting for ever for it as
    # it won't show up. We caannot override BindTo with # drop in files.
    #
    # Why? Because somehow systemd is not being able to auto-detect
    # all the serial ports given in the console statement to the Linux
    # kernel command line so we have to hardcode a bunch of console
    # devices for each platform.
    #
    #
    # This is a workaround until we find out why the kernel consoles
    # declared in /sys/class/tty/consoles/active are not all being
    # started or why the kernel is missing to add ttyUSB0 when
    # given.
    #
    # ALSO, force 115200 is the only BPS we support
    #
    info $image_type: systemd: hardcoding TTY console settings
    for systemd_libdir in $destdir/lib $destdir/usr/lib; do
        if ! [ -d $systemd_libdir/systemd ]; then
            # some systems have systemd in /lib, others /usr/lib...
            continue
        fi
        sudo sed -i \
             -e 's|^ExecStart=-/sbin/agetty -o.*|ExecStart=-/sbin/agetty 115200 %I $TERM|' \
             -e 's|^BindsTo=|# <commented out by tcf-image-setup.sh> BindsTo=|' \
             $systemd_libdir/systemd/system/serial-getty@.service
    done
    for tty_dev in $tty_devs; do
        info $image_type: force enabling of $tty_dev console
        sudo chroot $destdir systemctl enable serial-getty@$tty_dev
    done
fi

# Old yoctos
if [ -r $destdir/etc/inittab ]; then
    for tty_dev in $tty_devs; do
        echo "U0:12345:respawn:/bin/start_getty 115200 $tty_dev vt102" |
            sudo tee -a $destdir/etc/inittab
        info $image_type: added $tty_dev to automatic console spawn
    done
fi

if test -r $destdir/usr/share/defaults/etc/profile.d/50-prompt.sh; then
    # Hardcode: disable ANSI script sequences, as they make
    # scripting way harder
    sudo sed -i 's/^export PS1=.*/export PS1="\\u@\\H \\w $endchar "/' \
         $destdir/usr/share/defaults/etc/profile.d/50-prompt.sh
    info $image_type: disable ANSI coloring in prompt, makes scripting harder
fi

case $image_type in
    fedora*)
        # Disable SELinux -- can't figure out how to allow it to work
        # properly in allowing ttyUSB0 access to agetty so we can have
        # a serial console.
        sudo sed -i 's/SELINUX=enforcing/SELINUX=disabled/' $destdir/etc/selinux/config
        info $image_type: disabled SELinux
        ;;
    *)
        ;;
esac

case $image_type in
    fedoralive|qcow2)
        if [ -r "$destdir/etc/gdm/custom.conf" ]; then
            # Remove the GDM initial config user, so we don't get stuck
            # trying to configure the system
            sudo tee $destdir/etc/gdm/custom.conf <<EOF
[daemon]
InitialSetupEnable=false
EOF
            info $image_type: disabled GNOME initial setup
        fi
        ;;
    *)
        ;;
esac


#
# Now generate metadata, might not be needed, but we always did it just in case
#
md=$tmpdir/.tcf.metadata.yaml
cat > $md <<EOF
# this is metadata to help setup the image in a target system
#
# The TCF POS client will look for it in IMAGEDIR/.tcf-metadata.yaml
# and (keep it) in the final image for reference.

EOF
case $root_fstype in
    btrfs)
        cat >> $md <<EOF
filesystems:
  /:
    fstype: btrfs
    mkfs_opts: -f

EOF
        ;;
    ext4)
        # let it use defaults
        cat >> $md <<EOF
filesystems:
  /:
    fstype: ext4
    mkfs_opts: -Fj
EOF
        ;;
    *)

esac

cat >> $md <<EOF
# \$ROOT    - location where rootfs is mounted
# \$ROOTDEV - device which is mounted as root
post_flash_script: |
  cd \$ROOT
EOF

if [ $root_fstype == btrfs ]; then
    # if there are volumes in a btrfs filesystem, re-create them
    volumes=""
    rename_commands=""
    sudo btrfs subvolume list -oa $tmpdir/root > $tmpdir/volumes
    while read _id id _gen gen _top _level top_level _path path; do
        path=${path#<FS_TREE>/}
        if echo $path | grep -q .snapshots/; then
            continue
        fi
        capped_path=$(echo $path | cut -b3-)
        if echo $capped_path | grep -q /; then
            # volume has subdirs, which we can't create, so rename
            renamed_path=@/${capped_path//\//_}
            rename_commands="$rename_commands -e 's|subvol=/$path|subvol=/$renamed_path|' "
            path=$renamed_path
        fi
        volumes="$volumes $path"
    done < $tmpdir/volumes

    if ! [ -z "$volumes" ]; then
        cat >> $md <<EOF
  # SuSE rootfs expects subvolumes in its btrfs filesystem; renamed the
  # /usr/local and /boot/grub2/* subvolumes to not contain an internal
  # slash  *because* the 'btrfs subvolumecreate' tool seems to be incapable of creating them
  for v in $volumes; do \\
      btrfs subvolume create \$v; \\
  done
EOF
    fi
    cat >> $md <<EOF
  sed -i \\
      -e "/^UUID=.*swap/s/^UUID=[-0-9a-fA-F]\+/LABEL=tcf-swap/g" \\
      -e "/^UUID=.*btrfs/s/^UUID=[-0-9a-fA-F]\+/UUID=\$(lsblk -no uuid \$ROOTDEV)/g" \\
      $rename_commands \\
      etc/fstab
EOF
fi
sudo mv $tmpdir/.tcf.metadata.yaml $destdir
