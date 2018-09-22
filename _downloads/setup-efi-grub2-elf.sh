#! /bin/bash -eu
#
# Setup a USB Drive or file-backed hard drive image to Bios/EFI boot
# into Grub2 which will boot an ELF kernel.
#
# This is done as a separate script as it will need sudo permissions
# to run; which are configured with the file ttbd_sudo dropped in
# /etc/sudoers.d/ttbd_sudo.
#
# For extra safety and because we chicken, we refuse to run if certain
# conditions are not met (USB drive and matches the serial number we
# gave it or we can see the backing-file for the HD image).
#
# WARNING! Will destroy the contents of the given drive/image and
#          overwrite with grub and our files.
#
# dependencies:
# - parted
# - dosfstools
# - grub2-efi-x64-cdboot-2.02-22.fc27.x86_64
# - losetup
# - lsblk
# - util-linux
#

# Debugging permissions? do yourself a favour
#id -a
#grep ^Cap /proc/self/status
#strace -fo /tmp/file.strace ... comman

serial=$1
kernel=$2
arch="${3:-$HOSTTYPE}"
loopdev=""

function cleanup
{
    umount -l $mntdir
    rm -rf $tmpdir
    if ! [ -z "${loopdev:-}" ]; then
        # if the image path losetup'ed anything, undo it.
        losetup -d $loopdev
    fi
}


count=0
if [ -f "$serial" ]; then
    # If $serial is a regular readable file, then it is a disk image
    # We are supposed to be ran as sudo, but we won't want a hole that
    # allows an eighteen wheeler to pull through, so check if the
    # SUDO_USER is allowed to go in there
    if [ "${SUDO_USER:-}" != "" ] && ! sudo -u "$SUDO_USER" test -w "$serial"; then
        echo "E: $serial: cannot be written to by user $SUDO_USER"
        exit 1
    fi
    # losetup will print the canonical filename, so canonicalize it
    if ! _serial="$(readlink -e "$serial")"; then
        echo "E: $serial: some paths in the filename do not exist?"
        exit 1
    fi
    # A image file to do loopback
    losetup -Pvf "$_serial"
    dev=$(losetup --all -n --output NAME,BACK-FILE \
              | awk "\$2 == \"$_serial\" {print \$1; exit(0); }")
    part=${dev}p1
    loopdev=$dev
    if [ -z "${dev:-}" ]; then
        # final protection check, we don't want the flimsy thing down
        # there to umount the system
        echo "BUG: dev is empty, something failed"
        exit 1
    fi
else
    while true; do
        # If we just plug it, the block layer might still be
        # enumerating it, so give it a few tries
        #
        # lsblk list the device name, transport and serial #; select
        # only USB drives and if we don't find the serial number for
        # ours, then error out.
        if ! dev=$(lsblk -nro NAME,TRAN,SERIAL \
                       | awk "\$2 == \"usb\" && \$3 == \"$serial\" { print \$1;}") \
                || [ -z "$dev" ]; then
            count=$(($count + 1))
            if [ $count -lt 5 ]; then
                echo "W: $serial: can't find USB drive for serial #, retrying in 1s"
                sleep 1s
                continue
            fi
            echo "E: $serial: can't find USB drive for serial #"
            exit 1
        fi
        break
    done
    dev=/dev/$dev
    part=${dev}1
fi

echo "$serial: maps to device $dev"

if [ -z "${dev:-}" ]; then
    # final protection check, we don't want the flimsy thing down
    # there to umount the system
    echo "BUG: dev is empty, something failed"
    exit 1
fi

# FIXME: this is kinda flimsy
# Unmount anything that mite be mounted
for umountpart in ${dev}*; do
    if ! echo $umountpart | grep -q ^/dev; then
        echo "W: $umountpart: not /dev, skipping umount"
    elif grep -q ^$umountpart /proc/mounts; then
        umount --verbose -Rfl $umountpart || true
    else
        echo "W: $umountpart: not mounted, skipping umount"
    fi
done

trap cleanup EXIT
tmpdir=$(mktemp -d)
mntdir=$tmpdir/mnt

mkdir -p $mntdir

# note this is max 11 chars
label_name=TCF-GRUB2

# Now install grub2 in our device, need the multiboot module to load
# the ELF. Minnowboard/EFI loads as 64 bits, so target x86_64.
case $arch in
    x86_64)
        part_type=gpt
        target=x86_64-efi;;
    i386)
        part_type=msdos
        target=i386-pc;;
    *)
        echo "E: unknown architecture $arch"
        exit 1;;
esac


if ! label="$(dosfslabel $part | sed 's/ *$//')" || [ "$label" != "$label_name" ]; then
    echo "$dev: partitioning (unitialized drive or bad label ${label:-n/a})"
    # Make a fresh MSDOS or GPT partition table -- need the || true because if
    # it fails to re-read the partition table, it will fail and there
    # is no way to ask him to be quiet about it
    parted -s $dev mklabel $part_type
    # Make a fresh primary partition, no need for it to be bigger than
    # 100MB, which in any case is the size we make in other places
    # - start on sector 2048 or minnoboards have a hard time
    #   recognizing it
    parted -s $dev -a cyl mkpart primary fat32 2048s 95MB
    # mark it bootable
    parted -s $dev set 1 boot on
    # Ensure the partition table is read
    partprobe $dev
    echo "$dev: formatting"
    mkfs.vfat -F32 -n "$label_name" $part

    echo "$part: setting grub up"
    mount $part $mntdir	    # mount and make the basic dir tree
    if [ $part_type == gpt ]; then
        mkdir -p $mntdir/EFI/BOOT

        # Put grub as the default boot (hence the bootx64.efi name)
        # FIXME: hardwired to fedora
        cp /boot/efi/EFI/fedora/gcdx64.efi $mntdir/EFI/BOOT/BOOTX64.EFI
    fi

    # Now install grub2 in our device, need the multiboot module to load
    # the ELF. Minnowboard/EFI loads as 64 bits, so target x86_64.
    grub2-install --modules="multiboot terminal" --target=$target --removable \
                  --boot-directory=$mntdir --efi-directory=$mntdir/ \
                  $dev
else
    mount $part $mntdir
fi

echo "$part: copying kernel $kernel"
# be anal about names. Rename to something unique to this file.
# Why? because we want to make sure if it fails, it doesn't work
rm -f $mntdir/kernel*
id=$(md5sum $kernel | cut -b-10)
cp $kernel $mntdir/kernel-$id.elf

# Set the default grub configuration to launch the kernel, from
# ROOT/grub2, where grub boots from, that launches the kernel.elf file
# as soon as grub starts
# the 'echo' message is there so we can use it to verify grub got to
# execute it, we look for that.
# We don't specify paths, as the boot device by default is the root
# device and that way we don't have to distinguish partition types etc
# Stick to serial only -- if we enable both (console and serial), in
# some platforms, like Minnowboard, they conflict
cat > $mntdir/grub2/grub.cfg <<EOF
serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1
terminal_output serial
#terminal_output --append console
terminal_input  serial
#terminal_input --append console
echo TCF Booting kernel-$id.elf from root device \$root
multiboot /kernel-$id.elf
boot
EOF
# umount done by the cleanup() handler
