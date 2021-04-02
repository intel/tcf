#! /bin/bash

# Get the options passed by the Makefile
while getopts ":d:v:t:p:i:" o; do
    case "${o}" in 
        d)
            DISTRO=${OPTARG}
            ;;
        v)
            DISTROVERSION=${OPTARG}
            ;;
        t)
            TARGET_DIR=${OPTARG}
            ;;
        p)
            RPM_DIR=${OPTARG}
            ;;
        i)
            CONTAINER=${OPTARG}
    esac
done

VERSION=${VERSION:-$(git describe | sed 's/^v\([0-9]\+\)/\1/' | sed 's/-/./g')}

# Use docker if a container is specified, otherwise just run locally
if [ "${CONTAINER}" == "None" ]; then
    BDIST_OPTS="--dist-dir=${RPM_DIR}/ --bdist-base=${PWD}/dist/"
    cd ${PWD}/${TARGET_DIR} && VERSION=${VERSION} python3 ./setup.py bdist_rpm ${BDIST_OPTS}
elif [ "${CONTAINER}" == "True" ]; then
    BUILD_DEPS="dnf install -y python3 rpm-build"

    # Add necessary dependencies depending on the distro and build target
    if [ "${TARGET_DIR}" == "" ]; then
        if [ "${DISTRO}" == "centos" ]; then 
            BUILD_DEPS="dnf install -y dnf-plugins-core && dnf config-manager --set-enabled PowerTools && ${BUILD_DEPS}"
        fi
        BUILD_DEPS="${BUILD_DEPS} python3-sphinx python3-sphinx_rtd_theme make git"
    fi
    if [ "${TARGET_DIR}" == "ttbd" ]; then
        # Find the build dependencies from the generated setup.cfg file
        BUILD_DEPS+=$(awk '/build_requires/ && \
                    !f{f=1;x=$0;sub(/[^ ].*/,"",x);x=x" ";next} \
                    f {if (substr($0,1,length(x))==x) \
                    {sub(/^[ \t]+/, "");printf " %s",$0;} else f=0}' \
                    ttbd/setup.cfg)
    fi

    BDIST_OPTS="--dist-dir=/home/rpms/ --bdist-base=/home/tcf/dist/"
    RUN_SETUP="VERSION=${VERSION} python3 ./setup.py bdist_rpm ${BDIST_OPTS}"

    docker run -i --rm \
            -v ${PWD}:/home/tcf -v ${RPM_DIR}:/home/rpms \
            --env HTTP_PROXY=${HTTP_PROXY} --env http_proxy=${http_proxy} \
            --env HTTPS_PROXY=${HTTPS_PROXY} --env https_proxy=${https_proxy} \
            ${DISTRO}:${DISTROVERSION} \
            /bin/bash -c \
            "${BUILD_DEPS} && \
            useradd -u ${UID} ${USER} && \
            su - ${USER} -c \
            'export http_proxy=${http_proxy} && export https_proxy=${https_proxy} &&\
            cd /home/tcf/${TARGET_DIR} && ${RUN_SETUP}'"
else
    BDIST_OPTS="--dist-dir=/home/rpms/ --bdist-base=/home/tcf/dist/"
    RUN_SETUP="VERSION=${VERSION} python3 ./setup.py bdist_rpm ${BDIST_OPTS}"

    docker run -i --rm --user=${USER}\
            -v ${PWD}:/home/tcf -v ${RPM_DIR}:/home/rpms \
            ${CONTAINER}:${DISTROVERSION} \
            /bin/bash -c \
            "cd /home/tcf/${TARGET_DIR} && ${RUN_SETUP}"
fi
