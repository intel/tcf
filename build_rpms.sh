#! /bin/bash

# this is the sourcedir
topdir=$PWD
echo I: VERSION is $VERSION

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

# Use docker if a container is specified, otherwise just run locally
# None -> Backwards compat
if [ x"${CONTAINER}" != "x" -a "${CONTAINER}" != "None" ]; then
    BUILD_DEPS="dnf install -y python3 rpm-build"

    if [ "${TARGET_DIR}" == "ttbd" ]; then
        # Find the build dependencies from the generated setup.cfg file
        BUILD_DEPS+=$(awk '/build_requires/ && \
                    !f{f=1;x=$0;sub(/[^ ].*/,"",x);x=x" ";next} \
                    f {if (substr($0,1,length(x))==x) \
                    {sub(/^[ \t]+/, "");printf " %s",$0;} else f=0}' \
                    ttbd/setup.cfg)
    fi

    BDIST_OPTS="--dist-dir=$topdir/dist/ --bdist-base=$topdir/dist/"
    RUN_SETUP="python3 ./setup.py bdist_rpm ${BDIST_OPTS}"

    # --rm
    podman run \
            -v $HOME/.cache/dnf:/var/cache/dnf -v ${PWD}:${PWD}  \
            --env VERSION="$VERSION" \
            --env HTTP_PROXY=${HTTP_PROXY} --env http_proxy=${http_proxy} \
            --env HTTPS_PROXY=${HTTPS_PROXY} --env https_proxy=${https_proxy} \
            ${DISTRO}:${DISTROVERSION} \
            /bin/bash -c "dnf install -y python-yaml rpm-build; cd $topdir/${TARGET_DIR}; $topdir/nreqs.py install build.nreqs.yaml; ${RUN_SETUP}"

else

    cd ${PWD}/${TARGET_DIR}
    $topdir/nreqs.py install build.nreqs.yaml
    python3 ./setup.py bdist_rpm --dist-dir=${RPM_DIR}/ --bdist-base=${PWD}/dist/

fi
