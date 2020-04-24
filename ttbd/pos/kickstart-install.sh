#! /bin/bash -eu
#
# Automated Kickstart based installation using QEMU and ISO (no
# network access)
#
# - kickstart file is put in a vfat file drive with given label, pass
#   kernel command line to it using the LABEL= format
#
# - drive for kickstart file is created on the spot with mtools
#
# - QEMU boots the ISO's kernel/initrd, adds

progname=$(basename $0)
tmpdir=${TMPDIR:-`mktemp -d $progname-XXXXXX`}
mntdir=""

function cleanup() {
    if ! [ -z "${mntdir:-}" ]; then
        sudo umount $mntdir
    fi
    if [ "$tmpdir" != "${TMPDIR:-}" ]; then
        # wipe it only if we made it
        rm -rf $tmpdir
    fi
}

trap cleanup EXIT

function help() {
    cat <<EOF
$progname DEST.qcow2 SOURCE.iso [KICKSTARTFILE]
EOF
}

if [ $# -lt 2 -o $# -gt 3 ]; then
    help 1>&2
    exit 1
fi

qcowfile=${1}
isofile=${2}

# - autopart
if [ $# -lt 3 ]; then
    ksfile=$tmpdir/ks.cfg
    cat > $ksfile <<EOF
# Format at https://pykickstart.readthedocs.io/en/latest/

text
cdrom
auth --enableshadow --passalgo=sha512
keyboard --vckeymap=us --xlayouts='us'
lang en_US.UTF-8
eula --agreed
reboot

network  --bootproto=dhcp --device=eth0 --ipv6=auto --activate
network  --hostname=localhost.localdomain
timezone America/Pacific --isUtc

ignoredisk --only-use=sda
bootloader --location=mbr --boot-drive=sda
zerombr
clearpart --none --initlabel
autopart  --type=plain --nohome
rootpw somepassword
selinux --enforcing
firewall --enabled --http --ssh 
# Need at least one %packages section or it will die
%packages --ignoremissing
@core
@base
# Needed to manage SELinux attributes when SELinux itself is
# deactivated (tcf-image-setup.sh generates the script for this)
libselinux-utils
attr
%end
EOF
else
    ksfile=$3
fi

# Create a simple filesystem image with the kickstart file; the label
# is KS, so we can feed it to the kickstart process
dd if=/dev/zero of=$tmpdir/ks.drive bs=$((1024 * 1024)) seek=10 count=1
mkfs.vfat -n KS $tmpdir/ks.drive
mcopy -i $tmpdir/ks.drive $ksfile ::ks.cfg

# Create the destination image file
qemu-img create -f qcow2 -q $qcowfile 20G
# mount the iso to get the kernel/initird to boot -- note the EXIT
# trap above will unmount on exit
mntdir=$tmpdir/mnt
mkdir -p $mntdir
sudo mount -o loop $isofile $mntdir

# Now QEMU launch the thing
# - -no-reboot: exit when done instead of rebooting
# - 3G of memory, host CPU, etc, use KVM of course
# - kernel/initrd kidna harcoded now, might have to guess for others
# - append: serial console so we can stdio it, text installation mode;
#   ks argument tells it to find a harddrive with label KS and pull
#   the kickstart ks.cfg out of there
# - we made the drive above (tmpdir/ks.drive), labeled it KS and
#   copied the file
# - BIOS: UEFI
# - pass the ISO as hdd, the dest qcow as hda, the Kickstart drive as hdb
qemu-system-x86_64 -no-reboot \
                   -enable-kvm -cpu host -m 3072 \
                   -kernel $mntdir/isolinux/vmlinuz \
                   -initrd $mntdir/isolinux/initrd.img \
                   -append "console=ttyS0,115200n81 text ks=hd:LABEL=KS:/ks.cfg" \
                   -bios /usr/share/edk2/ovmf/OVMF_CODE.fd \
                   -cdrom $isofile \
                   -nographic \
                   -hda $qcowfile \
                   -hdb $tmpdir/ks.drive

# done -- on EXIT, everything is wiped except for the ISO and the QCOW
# unless you manually specified TMPDIR
