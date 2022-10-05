#
# Simple dockerfile to create an image that can run the TCF client
#
# Build as:
#
#  # cd .../tcf.git
#  $ buildah bud -t tcf -v $PWD:/home/work/tcf.git:O --label version="$(git describe --always)" -f client.Dockerfile
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
FROM registry.fedoraproject.org/fedora:34
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
RUN \
    chmod a+rwX -R /home/work && \
    dnf install -y python3-pip python3-yaml && \
    DNF_COMMAND=dnf /home/work/tcf.git/nreqs.py install /home/work/tcf.git && \
    dnf install -y \
        bind-utils \
        iputils \
        strace && \
    dnf clean all && \
    cd /home/work/tcf.git && \
    pip3 install . --root=/ --prefix=/ && \
    sed -i 's|#!python|#! /usr/bin/env python3|' /usr/bin/tcf && \
    rm -rf lib

ENV HOME=/home/work
WORKDIR /home/work
ENTRYPOINT [ "tcf" ]
