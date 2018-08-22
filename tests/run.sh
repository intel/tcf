#! /bin/sh
#
#
# See README on why
#
#
set -x
r=0
for v in ${@:-./test_*.py}; do
    [ $v = ./test_wip.py ] && continue
    $v || r=1
done
exit $r
