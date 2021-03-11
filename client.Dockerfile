#
# Simple dockerfile to create an image that can run the TCF client
#
# Build as:
#
#  $ buildah bud -t IMAGENAME -v /path/to/tcf.git:/home/tcf -f client.Dockerfile
#
# Push to a registry::
#
#  $ buildah push CONTAINERID REGISTRY/IMAGENAME
#
# Run under the the container::
#
#  $ podman run -e HOME=$HOME -v $HOME:$HOME localhost:50000/tcf-f33 tcf ls
#
FROM fedora:33
LABEL maintainer https://github.com/intel/tcf

# For CentOS
#RUN dnf install -y python3 epel-release git python3-pip
RUN dnf install -y python3 git python3-pip
RUN /home/tcf/setup-requirements.py /home/tcf/requirements.txt > /tmp/dependencies.list
RUN bash -c 'dnf install -y $(< /tmp/dependencies.list)'
RUN cd /home/tcf && python3 setup.py install