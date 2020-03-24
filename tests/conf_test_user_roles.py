#! /usr/bin/python
import ttbl.config
import ttbl.auth_localdb

ttbl.config.add_authenticator(ttbl.auth_localdb.authenticator_localdb_c(
    "Test user database",
    [
        [ 'user1', 'password', 'user', 'context1' ],
        [ 'user1d', 'password', 'user', '!context1' ],
        [ 'user2', 'password', 'user', 'context2' ],
        [ 'user2d', 'password', 'user', '!context2' ],
        [ 'user12', 'password', 'user', 'context1', 'context2' ],
        [ 'user12d', 'password', 'user', '!context2', '!context2' ],
    ]))


ttbl.config.target_add(ttbl.test_target('local_test'))

ttbl.config.target_add(ttbl.test_target('tg_req_c1'), tags = dict(
    _roles_required = [ 'context1' ],
))

ttbl.config.target_add(ttbl.test_target('tg_req_c2'), tags = dict(
    _roles_required = [ 'context2' ],
))

ttbl.config.target_add(ttbl.test_target('tg_exc_c1'), tags = dict(
    _roles_excluded = [ 'context1' ],
))

ttbl.config.target_add(ttbl.test_target('tg_exc_c2'), tags = dict(
    _roles_excluded = [ 'context2' ],
))

ttbl.config.target_add(ttbl.test_target('tg_req_c1_exc_c2'), tags = dict(
    _roles_required = [ 'context1' ],
    _roles_excluded = [ 'context2' ],
))

ttbl.config.target_add(ttbl.test_target('tg_exc_c1_req_c2'), tags = dict(
    _roles_required = [ 'context2' ],
    _roles_excluded = [ 'context1' ],
))
