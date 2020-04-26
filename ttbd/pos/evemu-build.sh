#! /bin/sh -xe
git clone git://anongit.freedesktop.org/libevdev libevdev.git
git clone -b fifo https://github.com/inakypg/evemu.git evemu.git
rm -rf root build
pwd=$PWD
mkdir -p root build/libevdev build/evemu
(
    cd libevdev.git
    NOCONFIGURE=1 ./autogen.sh
)
(
    cd build/libevdev
    ../../libevdev.git/configure --prefix=/opt/evemu LDFLAGS=-static --disable-shared --enable-static
)
make -C build/libevdev -j
make -C build/libevdev install DESTDIR=$pwd/root
(
    cd evemu.git
    NOCONFIGURE=1 ./autogen.sh
)
(
    cd build/evemu;
    ../../evemu.git/configure --prefix=/opt/evemu "LDFLAGS=-static $pwd/build/libevdev/libevdev/.libs/libevdev.a" --disable-shared --enable-static LIBEVDEV_LIBS="-L$pwd/build/libevdev/libevdev/.libs" LIBEVDEV_CFLAGS=-I/home/inaky/c/evemu/root/opt/evemu/include/libevdev-1.0
)
# don't build test since it fails with static linking, we only want the tools
make -C build/evemu/src -j
make -C build/evemu/tools -j
make -C build/evemu/tools install DESTDIR=$pwd/root
strip -g root/opt/evemu/bin/evemu-device 
strip -g root/opt/evemu/bin/evemu-event 
mkdir -p root/opt/evemu/share/doc/
cat > root/opt/evemu/share/doc/README.evemu <<EOF
The files

/opt/evemu/bin/evemu-event
/opt/evemu/bin/evemu-device

Are an static build of http://github.com/freedesktop/evemu (licensed
LGPLv3) statically linked to  http://github.com/freedesktop/libevdev
(licensed MIT).
EOF

tar czf evemu.bin.tar.gz -C root opt/evemu/bin/evemu-event opt/evemu/bin/evemu-device
