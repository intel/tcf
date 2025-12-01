#
# Simple dockerfile to create an image that can run the TCF client
#
# Build as:
#
#  # cd .../tcf.git
#  $ buildah bud -t tcf-client-deps-34 -v ~/tmp/dnf-40:/var/cache/dnf:rw  -v ~/tmp/pkg-40:/var/cache/PackageKit:rw -v $PWD:/home/work/tcf.git:O --label version="$(git describe --always)" -f client.Dockerfile
#
#    add --build-arg from=registry.fedoraproject.org/fedora:40
#
#  $ buildah bud --build-arg from=registry.fedoraproject.org/fedora:40 -t tcf-client-deps-40 -v ~/tmp/dnf-40:/var/cache/dnf:rw -v ~/tmp/pkg-40:/var/cache/PackageKit:rw  -v $PWD:/home/work/tcf.git:O --label version="$(git describe --always)" -f nreqs.Dockerfile
#
# Run under the container without registry::
#
#  $ podman run -v $HOME/.tcf:/home/work/.tcf:O tcf ls
#
# Push to a registry::
#
#  $ buildah push localhost/tcf REGISTRY/IMAGENAME/tcf:latest
#
# Run under the the container::
#
#  $ podman run -v $HOME/.tcf:/home/work/.tcf:O tcf tcf ls
#
# don't use fedora-minimal or it'll start pruning things we need (like /usr/share/zoneinfo)
FROM registry.fedoraproject.org/fedora:34@sha256:c7398ad5453edb06975b9b2f8e1b52c4f93c437155f3356e4ecf6140b6c69921
LABEL maintainer https://github.com/intel/tcf

COPY . /home/work/tcf.git
# We also add multiple tools for diagnosing that at the end we always need
# chmod: when we run inside Jenkins, it'll use which ever UID it uses
#        (can't control it), so we need /home/work world accesible
# pip3 install: our setup is a wee messed up at this point
#               sed -> quick hack because it's late and I am done with this
# rm -rf : leftover lib from pip3 removed
# chmod: when we run inside Jenkins, it'll use which ever UID it uses
#        (can't control it), so we need /home/work world accesible
#
# Note --skip-packages=tcf-client to nreqs; we try to install in this
# container images all the deps needed to build TCF itself, but it picks
# up also the ones needed to run the server (the client package) so
# when building the container we tell it to skip that.
RUN \
    chmod a+rwX -R /home/work && \
    dnf install -y python3-pip python3-yaml && \
    DNF_COMMAND=dnf /home/work/tcf.git/nreqs.py install --skip-package=tcf-client /home/work/tcf.git && \
    dnf install -y \
        bind-utils \
        gdb \
        iputils \
        telnet \
        strace && \
    dnf clean all && \
    cd /home/work/tcf.git && \
    python ./setup.py install --root=/ --prefix=/ && \
    sed -i 's|#!python|#! /usr/bin/env python3|' /usr/bin/tcf && \
    rm -rf lib

# we run this from the source package, we do not install it
ENV HOME=/home/work
WORKDIR /home/work
ENTRYPOINT [ "tcf" ]
