#! /bin/sh -xe
prefix=https://localhost:5001/ttb-v1

curl -c cookies.txt -k -X PUT $prefix/login \
     -d password=none -d username=local

#curl -b cookies.txt -k -X GET $prefix/targets/ | cut -b-90

#curl -b cookies.txt -k -X GET $prefix/allocation/

curl -b cookies.txt -k -X PUT $prefix/allocation \
     -d 'groups={"dd1":["NONEXISTANT1", "NONEXISTANT2", "NONEXISTANT3"],"dd2":["NONEXISTANT1", "NONEXISTANT2", "NONEXISTANT3"]}'


curl -b cookies.txt -k -X PUT $prefix/allocation \
     -d 'groups={"ddd":["T1"]}'

# fail: same targets in group
curl -b cookies.txt -k -X PUT $prefix/allocation  \
     -d 'groups={"dd1":["T1", "T2", "T3"],"dd2":["T1", "T2", "T3"]}'
# fail: duplicated targets in griup
curl -b cookies.txt -k -X PUT $prefix/allocation \
     -d 'groups={"dd1":["T1", "T2", "T2"],"dd2":["T1", "T2", "T3"]}'
# good: duplicated targets in group
curl -b cookies.txt -k -X PUT $prefix/allocation  \
     -d queue=true \
     -d 'groups={"dd1":["qu-90a", "nwa", "qu-91a"],"dd2":["nwa", "qu-91a", "qu-92a"]}' \
    | python -m json.tool | tee out
allocationid=$(python -c "import sys,json; print json.loads(sys.stdin.read())['allocationid']" < out)
# good: delete it
curl -b cookies.txt -k -X DELETE https://localhost:5001/ttb-v1/allocation/$allocationid

# good: create for another user
curl -b cookies.txt -k -X PUT $prefix/allocation \
     -d queue=true \
     -d obo_user=\"someuser@somedomain\" \
     -d 'groups={"dd1":["qu-90a", "nwa", "qu-91a"],"dd2":["nwa", "qu-91a", "qu-92a"]}' \
    | python -m json.tool | tee out
allocationid=$(python -c "import sys,json; print json.loads(sys.stdin.read())['allocationid']" < out)
curl -b cookies.txt -k -X GET https://localhost:5001/ttb-v1/allocation/$allocationid > out
python -m json.tool < out

# add guests
curl -b cookies.txt -k -X PATCH https://localhost:5001/ttb-v1/allocation/$allocationid/guest1
curl -b cookies.txt -k -X PATCH https://localhost:5001/ttb-v1/allocation/$allocationid/guest2
curl -b cookies.txt -k -X PATCH https://localhost:5001/ttb-v1/allocation/$allocationid/guest3
curl -b cookies.txt -k -X PATCH https://localhost:5001/ttb-v1/allocation/$allocationid/guest4
# list guests
curl -b cookies.txt -k -X GET https://localhost:5001/ttb-v1/allocation/$allocationid \
    | python -c "import sys,json; print ' '.join(sorted(json.loads(sys.stdin.read())['guests']))" > guests
if [ "$(< guests)" != "guest1 guest2 guest3 guest4" ]; then
    echo "ERROR: not four guests as expected" 1>&2
    exit 1
fi

# delete one
curl -b cookies.txt -k -X DELETE https://localhost:5001/ttb-v1/allocation/$allocationid/guest4
# list guests
curl -b cookies.txt -k -X GET https://localhost:5001/ttb-v1/allocation/$allocationid \
    | python -c "import sys,json; print ' '.join(sorted(json.loads(sys.stdin.read())['guests']))" > guests
if grep guest4 guests; then
    echo "ERROR: guest4 was removed, shan't be there" 1>&2
    exit 1
fi
if [ "$(< guests)" != "guest1 guest2 guest3" ]; then
    echo "ERROR: not just three guests as expected" 1>&2
    exit 1
fi

# deleting the same multiple times has no effect
curl -b cookies.txt -k -X DELETE https://localhost:5001/ttb-v1/allocation/$allocationid/guest4
curl -b cookies.txt -k -X DELETE https://localhost:5001/ttb-v1/allocation/$allocationid/guest4
# list guests
curl -b cookies.txt -k -X GET https://localhost:5001/ttb-v1/allocation/$allocationid | python -m json.tool
curl -b cookies.txt -k -X GET https://localhost:5001/ttb-v1/allocation/$allocationid \
    | python -c "import sys,json; print ' '.join(sorted(json.loads(sys.stdin.read())['guests']))" > guests
if [ "$(< guests)" != "guest1 guest2 guest3" ]; then
    echo "ERROR: not just three guests as expected" 1>&2
    exit 1
fi
echo PASS: all ran without dying
