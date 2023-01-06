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

ROOT_DEV         force the root partition to be taken from a given
                 device name (this comes handy when the image has a
                 volume group inside, eg /dev/mapper/something)

ROOT_MOUNTOPTS   use these root mount options (default to ext*'s
                 noload; use norecovery for xfs)

BOOT_PARTITION   force the boot partition to be that number (1, 2, 3...)

BOOT_DEV         force the boot partition to be taken from a given
                 device name (this comes handy when the image has a
                 volume group inside, eg /dev/mapper/something)

BOOT_MOUNTOPTS   use these boot mount options (default to empty)

BOOT_CONF_ENTRY  if defined, this is the full file name of a file under
                 the rootfs boot/loader/entries; any file in there that
                 is not this one will be removed

See more at https://inakypg.github.io/tcf/doc/04-HOWTOs.html#pos_image_creation
EOF
}

progname=$(basename $0)
progdir=$(dirname $(readlink -e $0))

if [ $# -lt 2 -o $# -gt 3 ]; then
    help 1>&2
    exit 1
fi

setupl=${SETUPL:-}

trap cleanup EXIT

destdir=$1
tmpdir=${TMPDIR:-`mktemp -d $progname-XXXXXX`}
if echo $destdir | grep -q ".tar.xz"; then
    tarname=$destdir
    if ! [ -z "${TARDIR:-}" ]; then
        tardit=$TARDIR
        tarname=$TARDIR/$(basename $tarname)
    fi
    destdir=${destdir%%.tar.xz}
    dest_type=tar
elif echo $destdir | grep -q ".qcow2"; then
    dest_type=qcow2
    # will be handled further down
else
    dest_type=dir
fi
image_file=$2
image_type=${3:-}


function info {
    echo I: "$@" 1>&2
}

function warning {
    echo W: "$@" 1>&2
}

function error {
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
    # remove possible LVM devices hanging off NBD
    if [ -n "${nbd_dev:-}" -o -n "${loop_dev:-}" ]; then
        lsblk --raw  --noheadings ${nbd_dev:-} ${loop_dev:-} -o NAME,TYPE | while read device type; do
            ## nbd0 disk
            ## nbd0p1 part
            ## nbd0p2 part
            ## nbd0p3 part
            ## cs-swap lvm
            ## cs-root lvm
            [ "$type" != "lvm" ] && continue
            sudo dmsetup remove $device
        done

    fi
    if [ "${dest_type}" = qcow2 ]; then
        info unmounting $tmpdir/destdir
        sudo umount -l $tmpdir/destdir || true
        if ! [ -z "${nbd2_dev:-}" ]; then
            sudo qemu-nbd -d $nbd2_dev || true
        fi
    fi
    if ! [ -z "$loop_dev" ]; then
        sudo losetup -d $loop_dev
    fi
    if ! [ -z "${nbd_dev:-}" ]; then
        info QCOW2: disconnecting source $nbd_dev
        sudo qemu-nbd -d $nbd_dev || true
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
            nbd_dev=${NBD_DEV:-/dev/nbd0}
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
        *raspbian*img)
            image_type=raspbian;;

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
    raspbian)
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
    nbd_dev=$(sudo $progdir/qemu-nbd-dynamic.sh -r --fork "$image_file")
    root_part=${nbd_dev}$root_part
    if ! [ -z "${boot_part:-}" ]; then
        boot_part=${nbd_dev}$boot_part
    fi
    info source image at QCOW2 $nbd_dev
else
    loop_dev=$(sudo losetup --show -fP $image_file)
    info loop device $loop_dev
    lsblk $loop_dev
fi


assume_there=yes
case $dest_type in
    qcow2)
        # QCOW2 mode for destination container We'll create a QCOW2 image
        # file, NBD export it, create a SINGLE partition on it, mount it
        # and use that to write
        qcow2name=$destdir
        qemu-img create -f qcow2 "$qcow2name".src 20G
        qemu-img convert -O qcow2 -c "$qcow2name".src "$qcow2name"
        rm -f "$qcow2name".src
        # all this is undone in cleanup()
        nbd2_dev=$(sudo $progdir/qemu-nbd-dynamic.sh --fork "$qcow2name")
        sudo parted --align optimal --script --fix $nbd2_dev mklabel gpt mkpart primary ext4 0 100%
        sudo mkfs.ext4 -qF ${nbd2_dev}p1
        mkdir -p $tmpdir/destdir
        sudo mount ${nbd2_dev}p1 $tmpdir/destdir
        destdir=$tmpdir/destdir
        assume_there=no
        ;;
esac

info current block devices
lsblk

# full blown override; this comes handy when it turns out the image
# has a volume group inside, that shows up in /dev/mapper
if ! [ -z "${ROOT_DEV:-}" ]; then
    root_part="$ROOT_DEV"
    info "ROOT DEVICE is $root_part (from \$ROOT_DEV)"
else
    info "ROOT DEVICE is $root_part"
fi
if ! [ -z "${BOOT_DEV:-}" ]; then
    root_part="$BOOT_DEV"
    info "BOOT DEVICE is $boot_part (from \$BOOT_DEV)"
else
    info "BOOT DEVICE is $boot_part"
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
    info mounted ${loop_dev}${root_part} in $tmpdir/root
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

elif [ $assume_there = no ] || ! [ -d $destdir ]; then

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

# SELinux!!! -- keep track of what files need to be relabeled because
# we will modify them. Relabelling will be done in the post-setup
# script execution.
#
# This is needed because POS runs with SELinux disabled, so the
# selinux attributes are not modified, just carried over as any
# attribute. Different Linux distros, different SELinux policies.
#
# This is an associative array, just set to 1
# (selinux_relabel["FILENAME"]=1; FILENAME is the absolute filename in
# the final filesystem).
declare -A selinux_relabel

# Remove the root password and unset the counters so you are not
# forced to change it -- we want passwordless login on the serial
# console or anywhere we access the test system.
for shadow_file in \
    $destdir/usr/share/defaults/etc/shadow \
    $destdir/etc/shadow; do
    if sudo test -r $shadow_file; then
        sudo sed -i 's/root:.*$/root::::::::/' $shadow_file
        info $shadow_file: removed root password and reset counters
        selinux_relabel["${shadow_file##$destdir}"]=1
    fi
done

for file in $destdir/etc/pam.d/* $destdir/usr/share/pam.d/*; do
    [ -f $file ] || continue
    info "$file: allowing login to accounts with no password (replacing 'nullok_secure')"
    selinux_relabel["${file##$destdir}"]=1
    sudo sed -i 's/nullok_secure/nullok/g' $file
    #grep -q "pam_unix.so.*nullok" $file && continue
    # Some distros configure PAM to disallow passwordless root; we
    # change that so automation doesn't have to work through so many
    # hoops
    info "$file: allowing login to accounts with no password (adding 'nullok')"
    sudo sed -i 's/pam_unix.so *$/pam_unix.so\tnullok /' $file
done

if test -r $destdir/usr/share/defaults/etc/profile.d/50-prompt.sh; then
    # Hardcode: disable ANSI script sequences, as they make
    # scripting way harder
    sudo sed -i 's/^export PS1=.*/export PS1="\\u@\\H \\w $endchar "/' \
         $destdir/usr/share/defaults/etc/profile.d/50-prompt.sh
    selinux_relabel["usr/share/defaults/etc/profile.d/50-prompt.sh"]=1
    info $image_type: disable ANSI coloring in prompt, makes scripting harder
fi

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
            selinux_relabel["etc/gdm3/custom.conf"]=1
        fi
        ;;
    fedoralive|qcow2)
        if [ -r "$destdir/etc/gdm/custom.conf" ]; then
            sudo tee $destdir/etc/gdm/custom.conf <<EOF
[daemon]
InitialSetupEnable=false
EOF
            info $image_type: disabled GNOME initial setup
            selinux_relabel["etc/gdm/custom.conf"]=1
        fi
        ;;
esac

if test -d $destdir/etc/ssh; then
    info $image_type: SSH: enabling root and passwordless login
    # allow root passwordless login--raspberry Pi defaults to ssh0
    # console, not serial
    sudo mkdir -p $destdir/etc/ssh
    sudo tee -a $destdir/etc/ssh/sshd_config > /dev/null <<EOF
PermitRootLogin yes
PermitEmptyPasswords yes
EOF
    info $image_type: SSH: creating host keys
    for v in rsa ecdsa ed25519; do
        sudo rm -f $destdir/etc/ssh/ssh_host_${v}_key
        sudo ssh-keygen -q -f $destdir/etc/ssh/ssh_host_${v}_key -t $v -C '' -N ''
    done
    # there is no good way to list units available in a chrooted environment, so just try blindly
    if sudo systemctl --root=$destdir enable sshd; then
        # most common
        info $image_type: SSH: enabled sshd service
    elif sudo systemctl --root=$destdir enable ssh; then
        info $image_type: SSH: enabled ssh service
    elif sudo systemctl --root=$destdir enable openssh-server; then
        info $image_type: SSH: enabled openssh-server service
    else:
        warning "$image_type: SSH: did not enable (unknown service name, tried sshd ssh openssh-server)"
    fi
fi


#
# Boot stuff
#
# Leave only which ever boot config file was defined to avoid
# confusing the TCF POS client

if ! [ -z "${BOOT_CONF_ENTRY:-}" ]; then
    # verify the single entry we are asking to keep alive exists
    if ! [ -r $destdir/boot/loader/entries/"$BOOT_CONF_ENTRY" ]; then
        entries=$(cd $destdir/boot/loader/entries && echo *.conf || true)
        error "$BOOT_CONF_ENTRY: unknown BOOT_CONF_ENTRY in boot/loader/entries (I see: ${entries:-none?})"
    fi
    # delete the rest
    for entry in $destdir/boot/loader/entries/*.conf; do
        if [ "$(basename $entry)" != "$BOOT_CONF_ENTRY" ]; then
            sudo rm -f $entry
        fi
    done
                                                        
fi

if echo $image_type | grep -q 'clear'; then
    if [ -r $destdir/boot/loader/entries/iso-checksum.conf ]; then
        # we do not use this file when booting and it is confusing the
        # bootloader configurer in
        # tcf.git/tcfl/pos_uefi.py:_linux_boot_guess_from_lecs()
        sudo mv $destdir/boot/loader/entries/iso-checksum.conf \
           $destdir/boot/loader/entries/iso-checksum.conf.disabled
    fi
fi


#
# .tcf.metadata.yaml generation
#
# Now generate metadata, including the setup script once the image is
# flashed.
#
# Variables in the metadata script $ROOT $ROOTDEV $BOOT_TTY $SELINUX_RELABEL
#
# SELINUX_RELABEL are files we need to SELInux relabel when we are
# done; every file you modify needs to be listed here
# (SELINUX_RELABEl="${SELINUX_RELABEL:-} NEWFILE"; NEWFILE has to be
# absolute to the target filesystem, not relative to /mnt)
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
# Parse in the /etc/os-release file; this file is in general this
# format and can be used to make decissions:
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
    selinux_relabel["etc/fstab"]=1
fi
    
if test -r $destdir/etc/fstab && grep -q "^UUID=.*[ \t]\+/[ \t]" $destdir/etc/fstab; then
    # rootfs on UUID; generate a command in the metdata file to
    # runtime replace the UUID with the one of our rootfs
    info "fstab: replacing UUIDs for / [ setup script will fixup ]"
    cat >> $md <<EOF
  sed -i \\
      -e "/^UUID=.* \/[ \t]/s|^UUID=[-0-9a-fA-F]\+|UUID=\$(lsblk -no uuid \$ROOTDEV)|g" \\
      etc/fstab 
EOF
    selinux_relabel["etc/fstab"]=1
fi

# Similar, but mainly for raspbian
if [ $image_type == raspbian ] \
       && test -r $destdir/etc/fstab \
       && grep -q "^PARTUUID=" $destdir/etc/fstab; then
    # rootfs on UUID; generate a command in the metdata file to
    # runtime replace the UUID with the one of our rootfs
    info "fstab: replacing PARTUUIDs for / and /boot [ setup script will fixup ]"
    cat >> $md <<EOF
  sed -i \\
      -e "s|^PARTUUID=[-0-9a-fA-F]\+\s\+/boot\s\+|/dev/mmcblk0p1\t/boot\t|" \\
      -e "s|^PARTUUID=[-0-9a-fA-F]\+\s\+/\s\+|/dev/mmcblk0p2\t/\t|" \\
      etc/fstab
EOF
    selinux_relabel["etc/fstab"]=1
fi

if test -r $destdir/etc/fstab && grep -q UUID= $destdir/etc/fstab; then
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
    selinux_relabel["etc/fstab"]=1
    # /boot filesystem, we wouldn't even really want to mount it, but
    # we do so test scripts can manipulate it; we always do partition
    # one, but who knows...and this is done when the image is flashed
    # so look above at ".tcf.metadata.yaml generation"
fi


# Well, general swap fixes -- we just remove all and let the boot code
# pick up the swap devices we make
if test -r $destdir/etc/fstab && grep -q '^\s*[^#].*\sswap\s' $destdir/etc/fstab; then
    info fstab: comment swap entries, let them auto detect
    # any line that has some sort of " swap " entry and is not
    # commented, just comment it out
    sudo sed -i \
       -e '/[^#].*\sswap\s/s|^|# <commented out by tcf-image-setup.sh> \0|'  \
       $destdir/etc/fstab
    selinux_relabel["etc/fstab"]=1
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
    selinux_relabel["${systemd_libdir##$destdir}/systemd/system/serial-getty@.service"]=1
    systemd_enabled=1
done

# If there is no entry for the rootfs in /etc/fstab, bad things
# happen; ensure the post-setup script will add it
if test -r $destdir/etc/fstab && ! grep -q '[ \t]/[ \t]' $destdir/etc/fstab; then 
    cat >> $md <<EOF
  echo "\$ROOTDEV / auto defaults 1 1" >> \$ROOT/etc/fstab
EOF
    selinux_relabel["etc/fstab"]=1
fi

# If SELinux is enabled in centos/rhel, we need to make sure the console is there
if  test -r $destdir/etc/selinux/targeted/contexts/files/file_contexts \
        && grep -qi "\(centos\|rhel\|fedora\)" <<< "${ID:-}"; then
    # Some distros tighten so much the /dev/tty(USB|S0) permissions with
    # SELinux that we are not allowed to login, so as we know we are
    # login in in this BOOT_TTY, make it allowed.
    cat >> $md <<EOF
  sed -i "/ttyUSB.*usbtty_device_t/i/dev/\$BOOT_TTY -c system_u:object_r:tty_device_t:s0" \\
      \$ROOT/etc/selinux/targeted/contexts/files/file_contexts
EOF
    selinux_relabel["etc/selinux/targeted/contexts/files/file_contexts"]=1
fi

if [ $systemd_enabled = 1 ]; then
    info "systemd: forcing boot console to start (systemd not always picks up)"
    # use the path to systemctl, some PATHs not right
    cat >> $md <<EOF
  chroot \$ROOT /bin/systemctl enable serial-getty@\$BOOT_TTY
  SELINUX_RELABEL="\${SELINUX_RELABEL:-} /etc/systemd/system/getty.target.wants/serial-getty@\$BOOT_TTY.service"
EOF
elif [ -r $destdir/etc/inittab ]; then
    # Old yoctos
    cat >> $md <<EOF
  echo "U0:12345:respawn:/bin/start_getty 115200 /dev/\$BOOT_TTY vt102" >> \ROOT/etc/inittab
EOF
    selinux_relabel["etc/inittab"]=1
fi

if [ -f $destdir/etc/selinux/config ]; then
    # If this distro sports some sort of SELinux, ensure we relabel by
    # hand all files we modified--why by hand? because restorecon
    # doesn't seem to work under the POS environment [which it runs
    # with SELinux disabled to avoid it mucking the SElinux contexts].
    # ASSUMPTION: imgage has setfattr and matchpathcon from the attr
    # and libselinux-utils packages installed.
    cat >> $md <<EOF
  for file in ${!selinux_relabel[@]} \${SELINUX_RELABEL:-}; do chroot . setfattr -hn security.selinux -v \$(chroot . /sbin/matchpathcon -n \$file) \$file; done
EOF
fi

# Calculate size in GiB and post it
#
# convert du's ouput (in GiB)
#
##   14G    .
##   14G    total
#
# To
#
## 14
#
# (sed wipes anything from G to the end and just do the first line)
size_gib=$(sudo du -sc -BG $destdir | sed 's/G.*$//;q')
echo "size_gib: $size_gib" >> $tmpdir/.tcf.metadata.yaml

# move yaml to final location
sudo mv $tmpdir/.tcf.metadata.yaml $destdir

# extra setup functions
for setup in ${setupl}; do
    $setup $destdir
done
    
# If we said we wanted it in a tar file, pack it up and remove the directory
case $dest_type in
    tar)
        cd $(dirname $destdir)
        basename=$(basename $destdir)
        # --numeric-owner: so when we extract we keep exactly what we
        #                  packed in stead of trying to map to destination
        #                  system
        # --force-local: if name has :, it is still local
        # --selinux --acls --xattrs: keep all those attributes identical
        info $tarname: packing up
        # pack it with a name that is not final, so another process
        # doesn't try to pick it up until it is fully baked
        sudo XZ_OPT="--threads=0 -9e" \
             tar cJf $tarname.tmp --numeric-owner --force-local --selinux --acls --xattrs $basename
        mv -f $tarname.tmp $tarname
        sudo rm -rf $destdir
        ;;
    
    qcow2)
        # well, we're done, umount and compress the image
        info unmounting $tmpdir/destdir
        sudo umount -l $tmpdir/destdir
        sudo qemu-nbd -d $nbd2_dev
        dest_type=qcow2-no-longer   # for cleanup() not to try to cleanup
        info compressing "$qcow2name"
        # this might halve the QCOW2 image name, which is a good trade
        # for CPU when moving around network distances
        qemu-img convert -O qcow2 -c "$qcow2name" "$qcow2name".compressed
        mv -f "$qcow2name".compressed  "$qcow2name"
esac

