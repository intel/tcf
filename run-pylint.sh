#! /bin/sh
dirname=$(dirname $(readlink -fe $0))
export PYTHONPATH=$PYTHONPATH:commonl

if [ $# -gt 0 ]; then

    for filename in "$@"; do
        readlink -fe $filename
        filedirname=$(dirname $(readlink -fe $filename))
        if echo $filedirname | grep /ttbd; then
            python_add=$PWD/ttbd/ttbl
        else
            python_add=$PWD/tcfl
        fi
        PYTHONPATH=$PYTHONPATH:$PWD/commonl:$python_add \
            pylint --rcfile=$dirname/.pylintrc $filename
    done
    exit
fi

# FIXME: figure out a way to run the ttbd and zephyr configuration
# files in the namespace they will be included on to avoid all the
# issues with undefineds

cd $dirname
# Utils
python3-pylint --rcfile=.pylintrc lint-all.py .lint.*.py
PYTHONPATH=$PYTHONPATH:$PWD/commonl:$PWD/tcfl \
    pylint --rcfile=$dirname/.pylintrc \
        conf.py \
        setup.py

# Client
PYTHONPATH=$PYTHONPATH:$PWD/commonl:$PWD/tcfl \
    pylint --rcfile=$dirname/.pylintrc \
        commonl \
        examples/*.py \
        zephyr/*.py sketch/*.py \
        tcfl
# Server
PYTHONPATH=$PYTHONPATH:$PWD/commonl:$PWD/ttbd/ttbl \
    pylint --rcfile=$dirname/.pylintrc \
        ttbd/*.py \
        ttbd/ttbl ttbd/zephyr/* ttbd/tests/*.py

# Docs
PYTHONPATH=$PYTHONPATH:$PWD/commonl:$PWD/ttbd/ttbl \
    pylint --rcfile=$dirname/.pylintrc \
        doc/training/*.py \
        tests/*.py
