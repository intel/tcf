#! /usr/bin/python
import ttbl.config
import ttbl.auth_localdb

ttbl.config.add_authenticator(ttbl.auth_localdb.authenticator_localdb_c(
    "Test user database",
    [
        [ 'userA', 'password', 'user', 'contextA' ],
        [ 'userB', 'password', 'user', 'contextB' ],
        [ 'userC', 'password', 'user', 'contextC' ],
        [ 'userD', 'password', 'user', 'contextD' ],
    ]))


ttbl.config.target_add(ttbl.test_target('local_test'))

for name in [ 'nwa', 'qu-90a', 'qu-91a', 'qu-92a' ]:
    ttbl.config.target_add(ttbl.test_target(name))


for n in range(30):
    ttbl.config.target_add(ttbl.test_target('target%02d' % n))
