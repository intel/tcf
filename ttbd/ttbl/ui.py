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

This blueprint has the capability of listing images found in the server and
rendering them. Images can have a lot of formats, so in order to add this layer
of flexibility you can add some variables to the configuration that will help
with this.

- see :data:`image_sufix` for how to tweak suffixes when flashing
  firmwares

- see :data:`image_path_prefixes` for how to twek where to get images
  for flashing firmwares

- different versions of the same type of image:
    `ttbl.ui.keywords_to_ignore_when_path`: list
    this can get a little tricky so bear with me. The keywords defined here
    can, be found in different files for the same image type, since the way we
    know which paths contain all image types is by counting them, this will
    give false results:

    Ex: say we have 3 image types (bios, fw, img), and we count the image
    files inside the directories
    >>> /my/path
    >>>    - bios
    >>>    - bios-test
    >>>   - fw
    >>>  /my/path2
    >>>    - bios
    >>>    - fw
    >>>    - img

    here both `path` and `path2` will say they have 3 different images, but
    only path2 has the 3 correct images types.
    >>> ttbl.ui.keywords_to_ignore_when_path = [
    >>>    '-test',
    >>>    '.info',
    >>> ]

    defining these two keywords in the list will make ttbd ignore `bios-test`
    and consider `path` to only have two images types
"""

import collections
import glob
import logging
import json
import os
import packaging.version
import werkzeug

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


#: Image files can have suffixes that the image type does not include, say you
#: have a firmware binary named `bios.img` but the image type is listed as
#: `bios` in the inventory. You can create a dict in the config to solve this
#: issue. Where the key is the image type and the value is the file suffix you
#: want to add.
#:
#: >>> ttbl.ui.image_suffix = {
#: >>>     'fw': '.dd',
#: >>>     'os': '.iso',
#: >>> }
image_suffix = {}


#: Where do we find image files
#:
#: You can have your images almost anywhere in your file directory, this list
#: of paths helps ttbd daemon to know where to look. This supports keyword
#: expansion meaning you can have dynamic fields from the inventory in your
#: path string.
#:
#: >>> ttbl.ui.image_path_prefixes = [
#: >>>     '/some/path/%(type)s',
#: >>>     '/my/cool/images/of/type/%(type)s',
#: >>> ]
image_path_prefixes = []


# FIXME: need to unify this, since ttbd uses it too
def flask_logi_abort(http_code, message, **kwargs):
    logging.info(message, **kwargs)
    response = flask.jsonify({ "_message": message })
    response.status_code = http_code
    raise werkzeug.exceptions.HTTPException(response = response)



def _interconnect_values_render(d: dict, field: str,
                                separator: str = " "):
    # For network fields, collect them and if there is more than
    # one network, prefix the network name, eg:
    #
    # nw1:ipv4.1 nw2:ipv4.2...
    #
    # except if there is only one it shows no "nwX:" for simplicity
    #
    # if not available, return "-", more visually pleasing than n/a

    ic = d.get('interconnects', {})
    vl = []
    for ic_name, v in ic.items():
        vl.append(ic_name + ":" + v.get(field, "n/a"))

    if len(vl) == 1:
        # extract only the value, remove the first WHATEVER:, taking
        # into account the value itself might have colons
        return vl[0][vl[0].find(":") + 1:]
    if vl:
        return separator.join(vl)
    return "-"



def short_field_maybe_add(d: dict, fieldname: str, max_length: int):
    """
    If a field is longer than @max_length, create a version of it
    called "<fieldname>_short" that is "<first chars>...".

    The UI templates can then choose to replace the long version with
    the short and display the long version as a tooltip, eg as::

      {% if v.targets_short is defined %}  {# too long, shorten and tooltip #}
        <div class = "tooltip">
          {{v.targets_short}}
          <span class = "tooltiptext">{{v.targets}}</span>
        </div>
      {% else %}	{# entry is short, no need to tooltip it #}
        {{v.targets}}
      {% endif %}

    :param dict d: dictionary keyed by strings of fieldnames with
      string values

    :param str fieldname: name of the field to inspect

    :param int max_length: max value length
    """
    v = d[fieldname]
    # if the field is too long, add a _short version so the
    # HTML/jinja2 can decide if to add a short/long version with tooltips
    if len(v) > max_length:
        d[fieldname + "_short"] = v[:max_length] + "..."



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
        inventory = target.to_dict(list())

        # TODO this will work once the healthcheck discovers this info
        # disks = d.get('disks', {}).get('total_gib', 'undefined?')
        # ram = d.get('ram', {}).get('size_gib', 'undefined?')
        owner = inventory.get('owner', 'available')

        target_type =  inventory.get('type', 'n/a')
        if target_type == 'ethernet':
            continue

        # For network fields, collect them and if there is more than
        # one network, prefix the network name
        # FIXME: only if ipv4_addr in fields
        ipv4_addr = _interconnect_values_render(inventory, "ipv4_addr")
        mac_addr = _interconnect_values_render(inventory, "mac_addr")

        targets[targetid] = {
            'id': targetid,
            'type': target_type,
            'ip': ipv4_addr,
            'mac': mac_addr,
            'owner': owner,
        }
        # single IPs are at least 16 chars
        short_field_maybe_add(targets[targetid], 'ip', 16)
        # single MACs are at least 18 chars
        short_field_maybe_add(targets[targetid], 'mac', 18)

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
    inventory = target.to_dict(list())

    # get owner
    owner = target.owner_get()
    # get type
    target_type =  inventory.get('type', 'n/a')
    # get alloc info
    alloc = inventory.get('_alloc', {}).get('id', 'none')

    # get power info
    p_state, p_data, p_substate = target.power._get(target)

    # parse all the inventory to str
    inventory_str = json.dumps(inventory, indent = 4)
    who = ttbl.who_create(flask_login.current_user.get_id(), None)
    if who:
        acquired = target.target_is_owned_and_locked(who)
        user_is_guest = who != target.owner_get()
    else:
        acquired = False
        user_is_guest = False

    state = {
        'power': p_state,
        'owner': owner,
        'acquired': acquired,
        'user_is_guest': user_is_guest,
        'type': target_type,
        'mac': _interconnect_values_render(inventory, "mac_addr", separator = " "),
        'ip': _interconnect_values_render(inventory, "ipv4_addr", separator = " "),
        'alloc': alloc,
    }
    # single IPs are at least 16 chars
    short_field_maybe_add(state, 'ip', 16)
    # single MACs are at least 18 chars
    short_field_maybe_add(state, 'mac', 18)

    #
    # Provive button data for the UI to display, if wanted/needed
    #
    # This is formatted by jinja, taking as template
    # ui/templates/target.html, by a button that toggles the button-ls
    # table, which will be rendered by jinja2 from the template and
    # will be managed, display wise, by
    # ttbd/ui/static/js/jquery.dataTables.js
    #
    if hasattr(target, "buttons"):
        # buttons interface is the ame as the power interface...with
        # another name :) w ignore the state and substate, because
        # they make no sense here
        _state, button_data, _substate = target.buttons._get(target)
    else:
        # FIXME: this is a hack; ideally, if no button control is
        # available, it shall not even show the list
        button_data = {
            "no buttons/relays/jumpers available": None
        }

    # more info about this tuple on the docstring of the function
    # `_get_images_paths`
    images, paths_for_all_images_types = _get_images_paths(inventory)

    return flask.render_template(
        'target.html',
        targetid = targetid,
        inventory_str = inventory_str,
        state = state,
        powerls = p_data,
        images = images,
        paths_for_all_images_types = paths_for_all_images_types,
        buttonls = button_data
    )



@bp.route('/allocation/<allocid>', methods = ['GET'])
@flask_login.login_required
def _allocation(allocid):
    # render the allocation control panel
    calling_user = flask_login.current_user._get_current_object()
    with ttbl.allocation.audit("ui/allocation/get",
               calling_user = calling_user,
               request = flask.request,
               allocid = allocid):
        try:
            allocdb = ttbl.allocation.get_from_cache(allocid)
            if not allocdb.check_query_permission(calling_user):
                # FIXME: this should be a render of a template?
                flask_logi_abort(400, f"{calling_user} not allowed")

            # we'll collect stuff here to send up to the Jinja2 renderer
            state = {
                "creator": allocdb.get("creator"),
                "owner": allocdb.get("owner"),
                "user": calling_user.get_id(),
                "user_is_guest": allocdb.check_userid_is_guest(
                    calling_user.get_id()),
                "user_is_owner_creator_admin": \
                allocdb.check_user_is_user_creator(calling_user) \
                or allocdb.check_user_is_admin(calling_user),
            }
            guests = []
            for guest in allocdb.guest_list():
                if guest:
                    guests.append(guest)

            return flask.render_template(
                'allocation.html',
                allocid = allocid, state = state, guests = guests)

        except Exception as e:
            flask_logi_abort(
                400, f"exception rendering /ui/allocation/{allocid}: {e}",
                exc_info = True)



def _get_images_paths(inventory: dict):
    '''
    this function process the interfaces.images property
    from the inventory and extends on it by adding new fields:
        `suffix`:str: suffix to image file name (if any defined in config, see
            ttbl/ui docstring for more info)
        `last_short_name`:str: short version of last_name field
        `file_list`:dict: paths to images (see example for more info)

    :param:inventory:dict:
        target's inventory, usually we get it with
        >>> target = ttbl.config.targets.get(targetid, None)
        >>> inventory = target.to_dict(list())

    :returns:tuple: (images, paths_for_all_images_types)
        The first element is an extended dictonary based on interfaces.images,
        The second element is a list of dictionaries with path available for
        all images.

        images:dict: example,
        >>> {
        >>>     'bios': {
        >>>         'instrument': 'dfs',
        >>>         'estimated_duration': '123',
        >>>         'last_name': 'prefix/some/path/bios',
        >>>         'last_sha512': 'a-long-sha',
        >>>         'suffix': '.img',
        >>>         'last_short_name': '/some/path',
        >>>         'file_list': {
        >>>             '/prefix/path/bios': {
        >>>                 'short_name': 'path'
        >>>             },
        >>>             '/prefix/path2/bios': {
        >>>                 'short_name': 'path2'
        >>>             }
        >>>         },
        >>>     },
        >>>     'firmware': {
        >>>         'instrument': 'klj',
        >>>         'estimated_duration': '23',
        >>>         'last_name': 'prefix/path/image',
        >>>         'last_sha512': 'a-long-sha',
        >>>         'suffix': '',
        >>>     ...more
        >>> }

        paths_for_all_images_types:list: example,
        >>> [
        >>>     {
        >>>         'paths': '/prefix/path/'
        >>>         'short_name': 'path'
        >>>     },
        >>>     {
        >>>         'paths': '/prefix/some/path/'
        >>>         'short_name': 'some/path'
        >>>     },
        >>>     ...more
        >>> ]
    '''
    images = dict(inventory.get('interfaces', {}).get('images', {}))
    # `images_by_path` tell us the valid images types that are in each path
    # found in the server
    images_by_path = collections.defaultdict(dict)
    for image_type in images.keys():
        images[image_type]['suffix'] = ''
        # for more info on ttbl.ui.image_suffix, check file docstring
        if image_type in ttbl.ui.image_suffix:
            images[image_type]['suffix'] = ttbl.ui.image_suffix[image_type]
        # if no last_name property is set in the inventory we want to add one
        # to give info to the user in the html
        if not 'last_name' in images[image_type]:
            images[image_type]['last_name'] = 'no record of last flashed image'
            images[image_type]['last_short_name'] = '-'

        # dict that contains all paths for each image type
        file_list = dict()
        for prefix in ttbl.ui.image_path_prefixes:
            # here we allow for lazy strings, meaning we expand the string with
            # fields from the inventory,
            # ex. '/path/something/%(type)s' -> '/path/something/some_type'
            prefix_formatted = prefix % inventory
            suffix = images[image_type]['suffix']

            # we look for the prefix in the path from the last flashed image,
            # this will allow us to make a shorter verison of the path, this
            # improves the readablity of the site
            if prefix_formatted in images[image_type]['last_name']:
                short_name_formatted = \
                    images[image_type]['last_name'][len(prefix_formatted) + 1:]
                images[image_type]['last_short_name'] = \
                    short_name_formatted[:-(len(image_type) + len(suffix))]

            local_list = glob.glob(prefix_formatted + f"/*/{image_type}*" + suffix)
            for filename in sorted(local_list):
                file_data = {}
                file_data["short_name"] = os.path.dirname(filename)[len(prefix_formatted) + 1:]
                dirname, basename = os.path.split(filename)
                for keyword in ttbl.ui.keywords_to_ignore_when_path:
                    if keyword in basename:
                        basename = basename.split(keyword)[0]
                file_list[filename] = file_data
                images_by_path[dirname].setdefault("images", set())
                images_by_path[dirname]["images"].add(basename)
                images_by_path[dirname]["prefix"] = prefix_formatted

        images[image_type]['file_list'] = file_list

    paths_for_all_images_types = []
    for path, info in images_by_path.items():
        if len(info['images']) == len(images.keys()):
            tmp = {}
            tmp['paths'] = path + '/'
            tmp['short_name'] = path[len(info['prefix']) + 1:]
            paths_for_all_images_types.append(tmp)

    return images, paths_for_all_images_types



@bp.route('/allocations', methods = [ 'GET' ])
@flask_login.login_required
def _allocation_ui():
    allocations = ttbl.allocation.query(
        flask_login.current_user._get_current_object())
    allocs = {}


    def _allocs_fill(allocid: str, v: dict, server_url: str, servername: str):
        # to get the targets from the allocation we need to iterate
        # thru the target_group dict.  the targets allocated to this
        # allocation are represented in field group_allocated, a comma
        # separated string
        targets = v.get('group_allocated', "").split(",")
        allocs[allocid] = {
            # rejoin it with spaces so it is properly broken in lines
            # by the table code
            'targets': " ".join(targets),
            'target_list': targets,
            'state': v.get('state', '<unkown>'),
            'user': v.get('user', '<unkown>'),
            'priority': v.get('priority', '<unkown>'),
            'server': servername,
            'server_url': server_url,
        }
        short_field_maybe_add(allocs[allocid], 'targets', 15)


    # Get local allocations
    for k, v in allocations.items():
        _allocs_fill(k, v, "/ttb-v2/ui", "local")

    return flask.render_template('allocations.html', allocs = allocs)


@bp.before_app_request
def load_logged_in_user():
    user = flask.session.get('user')
    if user is None:
        flask.g.user = None
    else:
        flask.g.user = user
