#! /bin/sh -x
# TIME LENGTH USER PRIO TARGETSPEC
at "$1" <<EOF
date=`date +%Y%m%d-%H%M%S`
exec >& result-$date.log
set -x
cd ~/s/local-alloc
~/t/alloc-tcf.git/tcf alloc-targets -d "$2" -o "$3"  --priority="$4" --preempt "$5"
EOF

