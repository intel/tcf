#
# Simple dockerfile to create an image that contains all the
# dependencies needed to run TCF and:
#
# - all the dependencies needed to build the TCF packages
#
# - a prefix based installation in /opt/tcf-client.dir
#
# - a a virtual environment in /opt/tcf-client.venv
#
# - the source in /home/work/tcf.git
#
# - a root based installation in /
#
# See also ../client.Dockerfile
#
# Build as:
#
#  $ cd .../tcf.git
#  $ mkdir -p ~/tmp/cache/dnf  ~/tmp/cache/pkg
#  $ buildah bud -t tcf-nreqs  -v ~/tmp/dnf:/var/cache/dnf:rw  -v ~/tmp/pkg:/var/cache/PackageKit:rw  -v $PWD:/home/work/tcf.git:O --label version="$(git describe --always)" -f nreqs.Dockerfiler
#
# By default it bases off a Fedora version; you can force it with --build-arg setting
#
#  - fedora_version: set to whichever version you want to build off
#    (eg: --build-arg fedora_version=40,  --build-arg fedora_version=34@sha256:c7398ad5453edb06975b9b2f8e1b52c4f93c437155f3356e4ecf6140b6c69921)
#
#  - from: override the whole thing, not just the version; useful to
#    use another registry, etc
#    (eg: --build-arg from=registry.fedoraproject.org/fedora:42
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
# Notes:
#
# - don't use fedora-minimal or it'll start pruning things we need
#   (like /usr/share/zoneinfo)

ARG fedora_version=34@sha256:c7398ad5453edb06975b9b2f8e1b52c4f93c437155f3356e4ecf6140b6c69921
ARG from=registry.fedoraproject.org/fedora:${fedora_version}
FROM ${from}
LABEL maintainer https://github.com/intel/tcf

# We copy the source in the container so it is available to run from
source for different scenarios (Jenkins, unit testing, etc)
COPY . /home/work/tcf.git

# What do we install?
#
# - python3 and yaml for nreqs to work
#
# - which: needed to find stuff in PATH
#
# - all TCF's dependencies with nreqs
#
#   Note --skip-packages=tcf-client to nreqs; we try to install in this
#   container images all the deps needed to build TCF itself, but it picks
#   up  also the ones needed to run the server (the client package) so
#   when building the container we tell it to skip that.
#
# - chmod: when we run inside Jenkins, it'll use which ever UID it uses
#          (can't control it), so we need /home/work world accesible
#
# - pip3 install: our setup is a wee messed up at this point
#                 sed -> quick hack because it's late and I am done with this
#
# - rm -rf: leftover lib from pip3 removed
#
RUN \
    set -e; \
    chmod a+rwX -R /home/work; \
    dnf install -y python3-pip python3-yaml; \
    DNF_COMMAND=dnf /home/work/tcf.git/nreqs.py install --skip-package=tcf-client /home/work/tcf.git; \
    dnf install -y \
        bind-utils \
        iputils \
        strace \
        which; \
    pip3 install --root=/ --prefix=/ /home/work/tcf.git; \
    pip install --prefix=/opt/tcf-client.dir /home/work/tcf.git; \
    python3 -m venv /opt/tcf-client.venv; \
    source /opt/tcf-client.venv/bin/activate; \
    pip install /home/work/tcf.git; \

# when just running the container, run TCF off the source path so we
# don't have to add extra PATHs and stuff
ENV HOME=/home/work
WORKDIR /home/work
ENTRYPOINT [ "tcf" ]
