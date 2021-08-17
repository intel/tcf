#
# Simple dockerfile to create an image that can run the TCF client
#
# Build as:
#
#  # cd .../tcf.git
#  $ buildah bud -t tcf -v $PWD:/home/tcf:O --label version="$(git describe --always)" -f client.Dockerfile
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
FROM registry.fedoraproject.org/fedora-minimal:34
LABEL maintainer https://github.com/intel/tcf

RUN microdnf install -y python3 git python3-pip python3-wheel
RUN microdnf install -y `python3 /home/tcf/setup-requirements.py /home/tcf/requirements.txt`
# our setup is a wee messed up at this point
# FIXME: sed -> quick hack because it's late and I am done with this
RUN cd /home/tcf && pip3 install . --root=/ --prefix=/ &&  sed -i 's|#!python|#! /usr/bin/env python3|' /usr/bin/tcf

ENV HOME=/home/work
WORKDIR /home/work
ENTRYPOINT [ "tcf" ]
