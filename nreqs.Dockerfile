#
# Simple dockerfile to create an image that contains all the
# dependencies needed to run TCF:
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
# - can also be used to create an image that contains just the client
#   and its dependencies (for client, we only need the dependencies in
#   ./base.nreqs.yaml)
#
# - can also be used to run builds
#
# Note this is called after nreqs so autobuilders pick it up.
#
# Building:
#
#  - Full dependency environment:
#
#     $ cd .../tcf.git
#     $ mkdir -p ~/tmp/fedora-34/dnf ~/tmp/fedora-34/packages
#     $ buildah bud -t tcf-client-34 -v ~/tmp/fedora-34/dnf:/var/cache/dnf:rw -v ~/tmp/fedora-34/packages:/var/cache/PackageKit:rw -v $PWD:/home/work/tcf.git:O --label version="$(git describe --always)" -f nreqs.Dockerfile
#
#     add --build-arg from=registry.fedoraproject.org/fedora:40
#
#     $ mkdir -p ~/tmp/fedora-40/dnf ~/tmp/fedora-40/packages
#     $ buildah bud --build-arg from=registry.fedoraproject.org/fedora:40 -t tcf-client-40 -v ~/tmp/fedora-40/dnf:/var/cache/dnf:rw -v ~/tmp/fedora-40/packages:/var/cache/PackageKit:rw -v $PWD:/home/work/tcf.git:O --label version="$(git describe --always)" -f nreqs.Dockerfile
#
#  - Full just client environment:
#
#     $ mkdir -p ~/tmp/fedora-40/dnf ~/tmp/fedora-40/packages
#     $ buildah bud --build-arg nreqs_files=/home/work/tcf.git/base.nreqs.yaml --build-arg from=registry.fedoraproject.org/fedora:40 -t tcf-client-40 -v ~/tmp/fedora-40/dnf:/var/cache/dnf:rw -v ~/tmp/fedora-40/packages:/var/cache/PackageKit:rw -v $PWD:/home/work/tcf.git:O --label version="$(git describe --always)" -f nreqs.Dockerfile
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

#
# Any variables set before the FROM seem to magically dissapear, so
# declare them here
#
# *.nreqs.yaml files to install; by default all of those found under
# /home/work/tcf.git
# say
#
#   --build-arg nreq_files /home/work/tcf.git/base.nreqs.yaml
#
# to do only the client
ARG NREQS=/home/work/tcf.git
ENV NREQS=${NREQS}

# We copy the source in the container so it is available to run from
# source for different scenarios (Jenkins, unit testing, etc)
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
    DNF_COMMAND=dnf /home/work/tcf.git/nreqs.py install ${NREQS} --skip-package=tcf-client; \
    dnf install -y \
        bind-utils \
        gdb \
        iputils \
        telnet \
        strace \
        which; \
    echo INFO: git version: $(cd /home/work/tcf.git; git describe --always); \
    echo INFO: setuptools_scm version: $(cd /home/work/tcf.git; python3 -m setuptools_scm); \
    echo INFO: ROOT: installing TCF; \
    pip3 install --root=/ --prefix=/ /home/work/tcf.git; \
    echo INFO: PREFIX /opt/tcf-client.dir: installing TCF; \
    pip install --prefix=/opt/tcf-client.dir /home/work/tcf.git; \
    python3 -m venv /opt/tcf-client.venv; \
    source /opt/tcf-client.venv/bin/activate; \
    pip install pyyaml; \
    echo INFO: VENV /opt/tcf-client.venv: installing client only nreqs; \
    /home/work/tcf.git/nreqs.py install /home/work/tcf.git/base.nreqs.yaml; \
    echo INFO: VENV /opt/tcf-client.venv: installing TCF; \
    pip install /home/work/tcf.git;

# when just running the container, run TCF off the source path so we
# don't have to add extra PATHs and stuff
ENV HOME=/home/work
WORKDIR /home/work
ENTRYPOINT [ "tcf" ]
