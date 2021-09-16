#! /bin/bash -eu
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Quick howto:
#
#   $ wget https://download.fedoraproject.org/pub/fedora/linux/releases/33/Workstation/x86_64/iso/Fedora-Workstation-Live-x86_64-33-1.2.iso
#   $ IMAGEDIR=/home/ttbd/images/tcf-live/x86_64
#   $ /usr/share/tcf/tcf-image-setup.sh $IMAGEDIR Fedora-Workstation-Live-x86_64-33-1.2.iso
#   $ /usr/share/tcf/tcf-pos-live-setup.sh $IMAGEDIR

IMAGEDIR=$1

function info {
    echo I: "$@" 1>&2
}

# tcfl.pos relies on the system priting 'TCF test node' in the serial
# console to determine we are done booting
echo "TCF test node @ \l" | sudo tee $IMAGEDIR/etc/issue > /dev/null

info "configuring password-less, auto-login"
# This is a Provisioning OS
#
# autologin as root so we can setup (without passwords) Why? because
# otherwise, we'd have to put the password somewhere everywhere in
# every single script that wants to do provisioning and it'd be
# useless, which would defeat the point of security.
#
# But security!
#
# - only the owner can access the serial console (this is what the TCF
#   server does)
#
# - SSH: we have it configured to enable SSH by default, so anyone can
#   login with root@IP; in the environment where we are, it shall be
#   configured so only the owner can access via the network.
#
#
# Other things that are done by tcf-image-setup.sh to make this work
# is
#
# - add nullok to pam_unix.so so we can login to root w/o passwd
# - replace nullok_secure with nullok so we can login w/o
#   password from USB serial ports and SSH
#
# In other words: the gates have to be before the hardware-the system
# gives you HW access to it.

sudo chroot $IMAGEDIR passwd --delete root
if ! grep -qe '--autologin root' $IMAGEDIR/usr/lib/systemd/system/serial-getty@.service;
then
    # --skip-login ensures we don't print the "login:" prompt, which
    # we don't have to, since we are autologin--it also confuses the
    # recovery code in the client side, which only expects it on the
    # actual OS.
    sudo sed -i \
        's|bin/agetty .*$|bin/agetty --skip-login --autologin root -o "-p -- \\u" 115200 %I $TERM|' \
        $IMAGEDIR/usr/lib/systemd/system/serial-getty@.service
fi

# Allow login as root with no password over SSH:
sudo tee $IMAGEDIR/etc/ssh/sshd_config.d/80-tcf-live.conf > /dev/null <<EOF
PermitRootLogin yes
PermitEmptyPasswords yes
EOF

# Pre-generate SSH keys so we don't get in trouble with the init
# sequence; at some point FIXME, we need to have the proper ordering
for v in rsa ecdsa ed25519; do
    sudo rm -f $IMAGEDIR/etc/ssh/ssh_host_${v}_key
    sudo ssh-keygen -q -f $IMAGEDIR/etc/ssh/ssh_host_${v}_key -t $v -C '' -N ''
done
sudo ln -sf /lib/systemd/system/ssh.service $IMAGEDIR/etc/systemd/system/multi-user.target.wants


info "ensuring SSHD is enabled"
# Ensure SSHD is always started when we boot--this allows us to use
# the SSH consoles (when desired), which are faster and in some cases,
# more reliable. Note tcf-image-setup.sh has done for us the SSH
# setup that allows us to login with no passwords.
sudo chroot $IMAGEDIR /bin/systemctl enable sshd

# just create a fake machine ID, otherwise the read-only NFS doesn't
# allow to initialize it properly--as it is done way early before we
# mount the overlayfs. Probably we can do a better fix, but this does
# it for now.
echo 00000000000000000000000000000001 \
    | sudo tee $IMAGEDIR/etc/machine-id > /dev/null

info "install required packages"
# install things we need in the image
#
#  - dosfstools/efibootmgr: to be able to mkfs.vfat /boot
#  - ipmitool: manage BMCs when present
#  - wget: download stuff
#  - python3-cryptography: for certain tools
#  - minicom: for serial port testing
#  - ncurses-compat-libs: for some utilities that still need this after this many years
#  - net-tools: arp and other utils
#  - statserial: for diagnosing serial ports
#  - strace: for diagnosing misc issues
#
# FIXME: run DNF inside the chroot, in case we are doing this in a non
#        DNF enabled system? this needs a lot of setup though, but
#        solve it even running on too old systems with newer RPM deps
#
# --nogpgcheck: needed so if we are adding a new repo key it doesn't
# fail. Yeah, security...hmm
. $IMAGEDIR/etc/os-release
sudo -E dnf --nogpgcheck --installroot=$IMAGEDIR --releasever=$VERSION_ID install -y \
        chntpw \
        dosfstools \
        efibootmgr \
        ipmitool \
        lshw \
        minicom \
        ncurses-compat-libs \
        net-tools \
        ntfsprogs \
        python3-cryptography \
        statserial \
        strace \
        wget \
        wimlib-utils \
        ${POS_PACKAGES:-}

# Setup the RW over RO NFS--we need to install it in the system
# slice so that we can run it as soon as we mount the local file
# systems.

# Now probably there'd be a better way to do this but with those
# remounts we have enough to be able to read-only mount and minimally
# use the system
#
# The real fix would be to pivot the root, but...this works good enough

info "setup RW overlay on the NFS read-only"
sudo tee $IMAGEDIR/etc/systemd/system/rootrw-overlay.service > /dev/null <<EOF
[Unit]
Description=NFS read-only overlayfs
DefaultDependencies=no
Conflicts=shutdown.target
After=systemd-remount-fs.service
Before=local-fs-pre.target local-fs.target shutdown.target
Wants=local-fs-pre.target

[Install]
RequiredBy=system.slice

[Service]
ExecStartPre = /usr/bin/mount -t tmpfs -o size=90%,mode=755,suid,exec tmpfs /media
ExecStartPre = /usr/bin/mkdir -p -m 755 /media/rootfs.ro /media/rootfs.rw /media/rootfs.work /media/rootfs.upper
ExecStartPre = /usr/bin/mount -n -B / /media/rootfs.ro
ExecStartPre = /usr/bin/mount -t overlay -o lowerdir=/media/rootfs.ro,upperdir=/media/rootfs.upper,workdir=/media/rootfs.work rootrw /media/rootfs.rw
ExecStartPre = /usr/bin/mount -B /media/rootfs.rw/etc/ /etc
ExecStartPre = /usr/bin/mount -B /media/rootfs.rw/var/log /var/log
ExecStart = /usr/bin/mount -B /media/rootfs.rw/var/lib /var/lib
EOF

# ensure the service is enabled and run
sudo systemctl --root $IMAGEDIR enable rootrw-overlay.service

# things we definitely do not need
sudo systemctl --root $IMAGEDIR disable firewalld.service
sudo systemctl --root $IMAGEDIR disable cups.service
sudo systemctl --root $IMAGEDIR disable ModemManager.service
sudo systemctl --root $IMAGEDIR disable flatpak-add-fedora-repos.service

# We don't need graphical, so boot only text mode, it is way faster
info "configure text-mode boot only"
sudo systemctl --root=$IMAGEDIR set-default multi-user.target

info "all done"
