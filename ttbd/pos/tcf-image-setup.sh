#! /bin/bash -eu
#
# Copyright (c) 2018 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0


function help() {
    cat <<EOF
$progname DIRECTORY IMAGEFILE [IMAGETYPE]

DIRECTORY: where to expand the image to

  NAME:SPIN:VERSION:[SUBVERSION]:ARCHITECTURE

  if .tar.xz is appended to the name, the image tree will be packed in
  a tar.xz file and the directory removed which shall be extracted as root::

    # tar xf DISTRO:SPIN:VERSION:SUBVERSION:ARCH.tar.xz --numeric-owner --force-local --selinux --acls --xattrs -C /home/ttbd/images

  if copying these files around with SSH, use
  PATH/DISTRO:SPIN:VERSION:SUBVERSION:ARCH.tar.xz to avoid scp erroring
  because it considers the : host separators. Likewise for tar.

IMAGEFILE: source ISO, qcow2 or rootfs image file

IMAGETYPE: force image detection

- fedora

- debian|ubuntu

- clear

- rootfsimage: takes a whole image that is a single root filesystem

Forcing things (set environment variables)

ROOT_PARTITION   force the root partition to be that number (1, 2, 3...)
BOOT_PARTITION   force the boot partition to be that number (1, 2, 3...)

ROOT_MOUNTOPTS   use these root mount options (default to ext*'s
                 noload; use norecovery for xfs)

BOOT_MOUNTOPTS   use these boot mount options (default to empty)

See more at https://inakypg.github.io/tcf/doc/04-HOWTOs.html#pos_image_creation
EOF
}

progname=$(basename $0)

if [ $# -lt 2 -o $# -gt 3 ]; then
    help 1>&2
    exit 1
fi

setupl=${SETUPL:-}

destdir=$1
if echo $destdir | grep -q ".tar.xz"; then
    tarname=$destdir
    destdir=${destdir%%.tar.xz}
fi
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
        openSUSE-*.iso|centos-*.iso|Fedora-Workstation-Live-*.iso)
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

#
# PHASE: live OS mount
#
# Mount the live filesystem in $tmpdir/root so we can copy it verbatim
# to $destdir/; maybe we have to mount some /boot directory on top of
# $tmpdir/root/boot
#
# We have $loop_dev, $root_part and others to determine what

root_fstype=ext4
mkdir $tmpdir/root
set -e
if [ $image_type = debian ]; then

    # Debian's ISO contains in partition1 a
    # RELEASENAME/filesystem.squashfs which contains the rootfs; it
    # does not have the kernel contents in boot/, which we have to
    # lift later from the same place where the filesystem.squashfs
    # file is.
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

    root_fstype=$(lsblk -n -o fstype ${root_part})
    if [ -z ${ROOT_MOUNTOPTS:-} ]; then
        # we are mounting readonly, guess how to so it doesn't complain
        case $root_fstype in 
            xfs)
                ROOT_MOUNTOPTS=norecovery;;
            ext4)
                ROOT_MOUNTOPTS=norecovery;;
            btrfs)
                ROOT_MOUNTOPTS=noload;;
            *)
                warning "can't guess best options for read-only rootfs $root_fstype"
                warning "please export BOOT|ROOT_PARTITION"
                warning "please export BOOT|ROOT_MOUNTOPTS"
                ROOT_MOUNTOPTS=""
        esac
    fi
    sudo mount -r -o ${ROOT_MOUNTOPTS:-} ${root_part} $tmpdir/root
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

if ! [ -z "$boot_part" ]; then
    # clear does this
    # 'auto' is used this a placeholder for a default option that
    # otherwise is doing no option
    sudo mount -o ${BOOT_MOUNTOPTS:-auto} ${loop_dev}${boot_part} $tmpdir/root/boot
    mounted_dirs="$tmpdir/root/boot ${mounted_dirs:-}"
    info mounted ${loop_dev}${boot_part} in $tmpdir/root/boot
fi

#
# PHASE: Copy the live filesystem to the $destdir
#
# This assumes we have mounted the boot partition on root/boot, to get
# all the boot goodies

if [ $image_type == android ]; then
    # Android is different, since it doesn't really do linux; so we
    # copy all the Android stuff straight up to the destination    
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

    # *Linux; copy $tmpdir/root to $destdir; be careful with extended
    # labels and ACLs -- rsync has been seen to hang, so use tar and untar

    sudo install -m 0755 -d $destdir
    info created $destdir, transferring
    sudo tar c --selinux --acls --xattrs -C $tmpdir/root . \
        | sudo tar x --selinux --acls --xattrs -C $destdir/.
    info $destdir: diffing verification
    sudo diff  --no-dereference -qrN $tmpdir/root/. $destdir/. || true
    info $destdir: setting up
    if [ $image_type == clear_live_iso ]; then
        # FIXME: move this out of here to the setup phase
        sudo mkdir $destdir/boot
        sudo cp -a $tmpdir/iso/EFI $tmpdir/iso/loader $destdir/boot
        # we need to remove the initrd activation, as that's what
        # triggers the installation process 
        info $destdir: disabling installation process
        sudo sed -i "s|^initrd|# Commented by tcf-image-setup.sh\n#initrd|" \
             $destdir/boot/loader/entries/*.conf 
    fi

else

    warning assuming image already in $destdir, setting up

fi

if [ $image_type = debian ]; then
    # Need to copy the boot kernel to $destdir/boot, since *Debian
    # doesn't put it in the Live CD's root/boot/
    dir=$(dirname $squashfs_file)
    kversion=$(file $dir/vmlinuz | sed  -e 's/^.* version //' -e 's/ .*//')
    sudo install -o root -g root $dir/initrd $destdir/boot/initramfs-$kversion
    sudo install -o root -g root $dir/vmlinuz $destdir/boot/vmlinuz-$kversion
fi

#
# PHASE: Setup
#

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

for file in etc/pam.d/common-auth usr/share/pam.d/su; do
    [ -r $destdir/$file ] || continue
    grep -q "pam_unix.so.*nullok" $destdir/$file && continue
    # Some distros configure PAM to disallow passwordless root; we
    # change that so automation doesn't have to work through so many
    # hoops
    info "$file: allowing login to accounts with no password (adding 'nullok')"
    sudo sed -i 's/pam_unix.so/pam_unix.so\tnullok /' $destdir/$file
done

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
        if [ -r $destdir/etc/selinux/config ]; then
            sudo sed -i 's/SELINUX=enforcing/SELINUX=disabled/' $destdir/etc/selinux/config
            info $image_type: disabled SELinux
        fi
        ;;
    *)
        ;;
esac

case $image_type in
    # Remove the GDM initial config user, so we don't get stuck
    # trying to configure the system
    ubuntu|debian)
        if [ -r "$destdir/etc/gdm3/custom.conf" ]; then
            sudo tee $destdir/etc/gdm3/custom.conf <<EOF
[daemon]
InitialSetupEnable=false
EOF
            info $image_type: disabled GNOME initial setup
        fi
        ;;
    fedoralive|qcow2)
        if [ -r "$destdir/etc/gdm/custom.conf" ]; then
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
# .tcf.metadata.yaml generation
#
# Now generate metadata, including the setup script once the image is
# flashed.
#
# Variables in the metadat script $ROOT $ROOTDEV $BOOT_TTY
#
md=$tmpdir/.tcf.metadata.yaml
cat > $md <<EOF
# this helps setup the image in a target system, created
# by tcf-image-setup.sh on $(date), maybe hand adjusted later
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
    xfs)
        cat >> $md <<EOF
filesystems:
  /:
    fstype: xfs
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

#
# This file is
#
## NAME=Fedora
## VERSION="29 (Workstation Edition)"
## ID=fedora
## VERSION_ID=29
## VERSION_CODENAME=""
## PLATFORM_ID="platform:f29"
## PRETTY_NAME="Fedora 29 (Workstation Edition)"
## ANSI_COLOR="0;34"
## LOGO=fedora-logo-icon
## CPE_NAME="cpe:/o:fedoraproject:fedora:29"
## HOME_URL="https://fedoraproject.org/"
## DOCUMENTATION_URL="https://docs.fedoraproject.org/en-US/fedora/f29/system-administrators-guide/"
## SUPPORT_URL="https://fedoraproject.org/wiki/Communicating_and_getting_help"
## BUG_REPORT_URL="https://bugzilla.redhat.com/"
## REDHAT_BUGZILLA_PRODUCT="Fedora"
## REDHAT_BUGZILLA_PRODUCT_VERSION=29
## REDHAT_SUPPORT_PRODUCT="Fedora"
## REDHAT_SUPPORT_PRODUCT_VERSION=29
## PRIVACY_POLICY_URL="https://fedoraproject.org/wiki/Legal:PrivacyPolicy"
## VARIANT="Workstation Edition"
## VARIANT_ID=workstation
##
if [ -r $destdir/etc/os-release ]; then
    source $destdir/etc/os-release
fi

cat >> $md <<EOF
# \$ROOT    - location where rootfs is mounted
# \$ROOTDEV - device which is mounted as root
# \$BOOT_TTY - boot device without the /dev
post_flash_script: |
  cd \$ROOT
EOF

if [ "$root_fstype" == btrfs ]; then
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
    
if grep -q "^UUID=.*[ \t]\+/[ \t]" $destdir/etc/fstab; then
    # rootfs on UUID; generate a command in the metdata file to
    # runtime replace the UUID with the one of our rootfs
    info "fstab: replacing UUIDs for / [ setup script will fixup ]"
    cat >> $md <<EOF
  sed -i \\
      -e "/^UUID=.* \/[ \t]/s|^UUID=[-0-9a-fA-F]\+|UUID=\$(lsblk -no uuid \$ROOTDEV)|g" \\
      etc/fstab 
EOF
fi

if grep -q UUID= $destdir/etc/fstab; then
    # aah...UUID based filesystems need love
    # - swap file systems, we know we'll create a swap partition labeled
    #   tcf-swap, so just throw that in
    # - we don't do /boot/efi, so comment it out; we put all boot stuff
    #   in a single /boot partition that the image deployment code in
    #   tcfl.pos manages
    info fstab: replacing UUIDs for swap, /boot, /boot/efi
    sudo sed -i \
       -e "/^UUID=.*swap/s/^UUID=[-0-9a-fA-F]\+/LABEL=tcf-swap/g" \
       -e 's|^UUID=.*/boot|# <commented out by tcf-image-setup.sh> \0|'  \
       -e 's|^UUID=.*/boot/efi|# <commented out by tcf-image-setup.sh> \0|'  \
       $destdir/etc/fstab
    # /boot filesystem, we wouldn't even really want to mount it, but
    # we do so test scripts can manipulate it; we always do partition
    # one, but who knows...and this is done when the image is flashed
    # so look above at ".tcf.metadata.yaml generation"
fi


#
# Fixup / harcode serial login consoles
#

# Harcode enable getty on certain devices
#
# On new distros, systemd enabled
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

systemd_enabled=0
info $image_type: systemd: hardcoding TTY console settings
# some systems have systemd in /etc ... /lib, others /usr/lib...
for systemd_libdir in $destdir/etc \
                          $destdir/lib \
                          $destdir/usr/lib;
do
    # Always enable agetty to $BOOT_TTY -- which the setup script will
    # force start (see below)
    [ -r $systemd_libdir/systemd/system/serial-getty@.service ] || continue
    sudo sed -i \
         -e 's|^ExecStart=-/sbin/agetty -o.*|ExecStart=-/sbin/agetty 115200 %I $TERM|' \
         -e 's|^BindsTo=|# <commented out by tcf-image-setup.sh> BindsTo=|' \
         $systemd_libdir/systemd/system/serial-getty@.service
    info $image_type: systemd: always enabling serial-getty@.service
    systemd_enabled=1
done

# If SELinux is enabled in centos/rhel, we need to make sure the console is there
if  test -r $destdir/etc/selinux/targeted/contexts/files/file_contexts \
        && ( [ "${ID:-}" == centos ] || [ "${ID:-}" == rhel ] ); then
    # Some distros tighten so much the /dev/ttyUSB0 permissions with
    # SELinux that we are not allowed to login, so as we know we are
    # login in in this BOOT_TTY, make it allowed.
    cat >> $md <<EOF
  grep -q USB <<< \$BOOT_TTY && sed -i "/ttyUSB.*usbtty_device_t/i/dev/\$BOOT_TTY -c system_u:object_r:tty_device_t:s0" \\
      \$ROOT/etc/selinux/targeted/contexts/files/file_contexts
EOF
fi

if [ $systemd_enabled = 1 ]; then
    info "systemd: forcing boot console to start (systemd not always picks up)"
    cat >> $md <<EOF
  chroot \$ROOT systemctl enable serial-getty@\$BOOT_TTY
EOF
elif [ -r $destdir/etc/inittab ]; then
    # Old yoctos
    cat >> $md <<EOF
  echo "U0:12345:respawn:/bin/start_getty 115200 /dev/\$BOOT_TTY vt102" >> \ROOT/etc/inittab
EOF
fi

sudo mv $tmpdir/.tcf.metadata.yaml $destdir

for setup in ${setupl}; do
    $setup $destdir
done
    
# If we said we wanted it in a tar file, pack it up and remove the directory
if ! [ -z "${tarname:-}" ]; then
    cd $(dirname $destdir)
    basename=$(basename $destdir)
    # --numeric-owner: so when we extract we keep exactly what we
    #                  packed in stead of trying to map to destination
    #                  system
    # --force-local: if name has :, it is still local
    # --selinux --acls --xattrs: keep all those attributes identical
    info $tarname: packing up
    sudo XZ_OPT="--threads=0 -9e" \
         tar cJf $tarname --numeric-owner --force-local --selinux --acls --xattrs $basename
    sudo rm -rf $destdir
fi
