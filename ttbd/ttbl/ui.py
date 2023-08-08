#! /usr/bin/env python3
#
# Copyright (c) 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
"""
ui for ttbd

this is the blueprint for ttbd's web GUI. Here we basically define the routes
for all GUI related methods and then register the blueprint in ttbd something
like

>>> import ui
>>> app.register_blueprint(ui.bp)

Then ttbd will pick up all the routes defined here.

When defining a route, take into account that each blueprint has a url_prefix,
here we chose `ui`, so all the routes in here have `API_PREFIX + /ui` before
the actual route (when opening it on your browser or make the http request)
even if it's not specified in the actual function decorator.
"""

import logging
import json

import flask
import flask_login

import ttbl
import ttbl.config
import ttbl.allocation


#FIXME unify this with ttbd
API_VERSION = 2
API_PATH = "/ttb-v"
API_PREFIX = API_PATH + str(API_VERSION) + "/"

bp = flask.Blueprint('ui', __name__, url_prefix = API_PREFIX  + '/ui')


@bp.route('/', methods = ['GET'])
def _targets():
    '''
    index page for the website, it consists of a table with all the targets,
    and some information on each one of them, if you click on the name, you get
    to a control panel per target, where you can do actions with it.

    In order to display the table we need to query the inventory and ask for
    some of the target information. We then build a dictionary with the
    relevant info and pass it to the html jinja template for it to render
    '''
    targets = {}
    for targetid, target in ttbl.config.targets.items():

        target = ttbl.config.targets.get(targetid, None)
        d = target.to_dict(list())

        # TODO this will work once the healthcheck discovers this info
        # disks = d.get('disks', {}).get('total_gib', 'undefined?')
        # ram = d.get('ram', {}).get('size_gib', 'undefined?')
        owner = d.get('owner', 'available')

        t =  d.get('type', 'n/a')
        if t == 'ethernet':
            continue

        nw = d.get('interconnects', {})
        if not nw:
            continue

        for _, v in nw.items():
            ip = v.get("ipv4_addr")
            mac = v.get("mac_addr")

        targets[targetid] = {
            'type': t,
            'ip': ip,
            'mac': mac,
            'owner': owner,
        }

    return flask.render_template('targets.html', targets = targets)


@bp.route('/target/<targetid>', methods = ['GET'])
def _target(targetid):
    '''
    Given a targetid get all its inventory as a dict, transform it to a
    string but with json format and indentation, to then render target.html
    template sending that stringify json and the targetid.
    '''
    target = ttbl.config.targets.get(targetid, None)
    if target is None:
        flask.abort(404, "{targetid} not found in this server")
    d = target.to_dict(list())

    # get owner
    owner = d.get('owner', 'available')
    # get type
    t =  d.get('type', 'n/a')
    # get alloc info
    alloc = d.get('_alloc', {}).get('id', 'none')

    # get network info
    nw = d.get('interconnects', {})
    for _, v in nw.items():
        ip = v.get("ipv4_addr")
        mac = v.get("mac_addr")

    # get power info
    p_state, p_data, p_substate = target.power._get(target)
    state['power'] = p_state

    # parse all the inventory to str
    d = json.dumps(d, indent = 4)
    state = {
        'power': p_state
        'owner': owner,
        'type': t,
        'mac': mac,
        'ip': ip,
        'alloc': alloc,
    }

    return flask.render_template(
        'target.html', targetid = targetid, d = d, state = state,
        powerls = p_data)


@bp.route('/allocations', methods = [ 'GET' ])
@flask_login.login_required
def _allocation_ui():
    allocations = ttbl.allocation.query(
        flask_login.current_user._get_current_object())
    allocs = {}
    for k, v in allocations.items():
        allocs[k] = {
            'targetid': v.get('target_group', {}).get('targetid', 'error'),
            'state': v.get('state', 'error'),
        }
    return flask.render_template('allocations.html', allocs = allocs)


@bp.before_app_request
def load_logged_in_user():
    user = flask.session.get('user')
    if user is None:
        flask.g.user = None
    else:
        flask.g.user = user
