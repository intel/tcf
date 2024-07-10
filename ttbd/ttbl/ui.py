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

- see :data:`image_suffix` for how to tweak suffixes when flashing
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
import fnmatch
import glob
import logging
import json
import os
import pathlib
import re
import time
import werkzeug

import flask
import flask_login
import packaging.version

import commonl
import ttbl
import ttbl.config
import ttbl.allocation


#FIXME unify this with ttbd
API_VERSION = 2
API_PATH = "/ttb-v"
API_PREFIX = API_PATH + str(API_VERSION) + "/"

bp = flask.Blueprint('ui', __name__, url_prefix = API_PREFIX  + '/ui')
# note we have modified in ttbd the template search to happen giving
# precedence to /etc/ttbd-INSTANCE/html and /etc/ttbd/html; search for
# jinja_template_searchpath in ../ttbd for more info

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



#: Add some descriptions for inventory items
#:
#: This allows specifying descriptions that are missing on the
#: inventory for things such as components that can be used by UIs.
#:
#: >>> ttbl.ui.inventory_descriptions = {
#: >>>     "interfaces.images.bios": (
#: >>>         "Flashes the system's BIOS"
#: >>>     ),
#: >>>     "interfaces.power.AC": (
#: >>>         "Controls main power to the SUT via PDU"
#: >>>         " '%%(instrumentation.%%(%(key)s.instrument)s.name)s'"
#: >>>     ),
#: >>>     re.compile("interfaces.power.tuntap-*"): (
#: >>>         "Controls a virtual network switch so a SUT implemented"
#: >>>         " via a virtual machine can communicate with other SUTs or VMs"
#: >>>     ),
#: >>>     "interfaces.power.ttyS0": (
#: >>>         "Serial line tape recorder for the BIOS/OS serial console;"
#: >>>         " records all output from the serial port as soon as it"
#: >>>         " is powered on so no output is lost"
#: >>>     ),
#: >>> }
#:
#: Keys can be a name of an interface entry for which the UI will ask
#: for descriptions or a regular expression.
#:
#: Descriptions are a simple text which can include *%(FIELD)[ds]*
#: from the inventory, with the special *key* string representing the
#: key that was matched. Use a double %% to delay expansion to a
#: second pass.
inventory_descriptions = {}



# FIXME: need to unify this, since ttbd uses it too
def flask_logi_abort(http_code, message, **kwargs):
    logging.info(message, **kwargs)
    response = flask.jsonify({ "_message": message })
    response.status_code = http_code
    raise werkzeug.exceptions.HTTPException(response = response)

def servers_info_get():
    # collect info about all known servers so we can pass it to the
    # client to be able to login to them if they want
    #
    # use TCFL to find the list of other servers we know about; we
    # cache it using lru_cache_disk so it is stored in disk and shared
    # amongst all processes; because state_path is not defined, we
    # need the function helper so we can use the cache decorator

    @commonl.lru_cache_disk(
        path = os.path.realpath(
            os.path.join(
                # FIXME: ugh, we need a global for daemon cache path,
                # then this can be moved up outside of here
                # Also, we need this defined here so state_path is defined
                ttbl.test_target.state_path,
                "..", "cache", "ttbd.ui.servers_info_get"
            )
        ),
        max_age_s = 10 * 60,		# refresh periodically
        max_entries = 20,
        exclude_exceptions = [ Exception ])
    def _servers_info_get():
        import tcfl.servers
        import urllib.parse
        tcfl.servers.subsystem_setup()
        tcfl.servers._discover_bare()	# rediscover if oldish
        _servers_info = dict()
        # sort the server list, so the user has a better time looking
        # for them note we sort by top level domains first and equal
        # domains will short by hostname
        for server_url, _server in sorted(tcfl.server_c.servers.items(),
                                          key = lambda k: k[0].split(".")[::-1]):
            if 'localhost' in server_url:
                continue
            url_parser_obj = urllib.parse.urlparse(server_url)
            _servers_info[server_url] = {
                'netloc': url_parser_obj.netloc,
            }
        return _servers_info

    return _servers_info_get()



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
    calling_user = flask_login.current_user._get_current_object()

    try:
        # query the user secondary db to see if he/she has preferred fields for the
        # targets table, meaning specific columns he/she want to see
        preferred_fields = \
            calling_user.fsdb_secondary.get('ui_preferred_fields_for_targets_table')
    except AttributeError:
        preferred_fields = 'type,interconnects.*.ipv4_addr,interconnects.*.mac_addr,owner'
    if preferred_fields in [None, ''] :
        # user has not created custom fields, lets add some default ones.
        preferred_fields = 'type,interconnects.*.ipv4_addr,interconnects.*.mac_addr,owner'
        calling_user.fsdb_secondary.set(
            key = 'ui_preferred_fields_for_targets_table',
            value = preferred_fields,
        )

    preferred_fields = preferred_fields.split(',')
    for targetid, target in ttbl.config.targets.items():
        if not target.check_user_allowed(calling_user):
            continue
        target = ttbl.config.targets.get(targetid, None)

        # inventory_to_display is a list of tuples that looks something like:
        # [('some_key', 'some_value'), ('other.key.name', 'value'),...  ]
        inventory_to_display = commonl.dict_to_flat(
            target.tags, preferred_fields, sort = False, empty_dict = True)
        inventory_to_display += target.fsdb.get_as_slist(*preferred_fields)

        # We now have in `inventory_to_display` all the info we will show in
        # the different columns, the thing is, we do not know on which column
        # to put each item. So we are going to use `fnmatch` to group them.  We
        # will exec the regex on the entires and group together all those that
        # match. Under a that looks like this
        # targets = {
        #   'target-1': {
        #       'some_custom_field_*_that_groups_keys': {
        #           'all_entires': [
        #               ('some_custom_field_1_that_groups_keys', 'value'),
        #               ('some_custom_field_2_that_groups_keys', 'other'),
        #               ('some_custom_field_3_that_groups_keys', 'thing'),
        #           ],
        #       },
        #       'other_field_*': {
        #           'all_entires': [
        #               ('other_field_a', 'jose'),
        #               ('other_field_c', 'pedro'),
        #           ],
        #       },
        #   },
        #   'target-2': {
        #   ...
        # }
        targets[targetid] = {}
        for key, entry in inventory_to_display:
            for preferred_field in preferred_fields:
                regex = fnmatch.translate(preferred_field)
                r = re.compile(regex)
                m = r.match(key)
                if m:
                    if preferred_field not in targets[targetid]:
                        targets[targetid][preferred_field] = {
                            'all_entries': [(key, entry)],
                        }
                        continue
                    targets[targetid][preferred_field]['all_entries'] += [(key, entry)]

        for fields_group_name, fields in targets[targetid].items():
            # if one fields_group_name has a lot of elements, the table cell
            # will look messy with a bunch on the html.
            # We want to just render the first entries and add a button to show
            # all the info if needed.
            #
            # jinja can not break out of a loop, so if a group of fields is
            # large enough (> `max_entries_to_render` entries).
            #
            # we add a new key to the dict, first_entires, we render those in
            # the table html, and add everything else to a pop up
            max_entries_to_render = 3
            if len(fields['all_entries']) > max_entries_to_render:
                targets[targetid][fields_group_name]['first_entries'] = \
                                fields['all_entries'][:max_entries_to_render]
                continue
            targets[targetid][fields_group_name]['first_entries'] = None

    return flask.render_template(
        'targets.html',
        targets = targets,
        preferred_fields = preferred_fields,
        servers_info = servers_info_get()
    )



def target_description_get(
        target: ttbl.test_target, key: str, default = None) -> str:
    """
    Find a description field for an inventory key

    If there is an inventory key named *key.description*, that will be
    returned; otherwise, if a *key* is found in
    :data:`ttbl.ui.inventory_descriptions`, that will be used.

    :param ttbl.target_c target: target for which to find the
      description

    :param str key: name of the key for which we are looking ofr a description

    :returns str: string with a description or *None* if no
      description available.
    """
    description = target.property_get(key + ".description", None)
    if description != None:
        return description
    for k, v in inventory_descriptions.items():
        if isinstance(k, re.Pattern):
            if k.match(key):
                return v
        if k == key:
            return v
    return default


def _target_power_get(target: ttbl.test_target, inventory: dict, kws: dict):
    '''
    Query the inventory to get the power rail/components of target WITHOUT
    their states, we will get the state using a js call, since we don't want to
    slow down the html request

    :param ttbl.target_c target: target for which to find the
      power components

    :param dict inventory: result of doing target.to_dict(list()), we could do
      it inside the function but we usually already have it at the point the
      function is called. No need on querying it again.

    :param dict kws: keywords, used to  get the description of power component

    :return dict power_component_description:
        power_component_description is a dict with the following format:
            > power_component_description = {
            >     'AC': 'AC description',
            >     'power1': 'AC description',
            >     'power2': 'AC description',
            > }
        so, key = component, value = description
    '''
    # we DO NOT want to get the power state of the components, meaning we
    # do not want to run `target.power._get(target)`, because if the
    # target has a lot of components, it will take a long way to check
    # the status of them all. This will slow the server response. Instead
    # we just get the components, and then with js do lazy loading to get
    # the state.
    power_component_description = {}
    power_components = inventory.get('interfaces', {}).get('power', None)
    for component_name, component_value in power_components.items():
        if not isinstance(component_value, dict) or \
            component_value.get('instrument', None) is None:
            # this means that the component is not really a component, but
            # info on the power interface. We do not want to have it in
            # the power rail
            continue
        path = f"interfaces.power.{component_name}"
        kws['key'] = path
        description = target_description_get(target, path)
        power_component_description[component_name] = None
        if description:
            description = commonl.kws_expand(description, kws)
            power_component_description[component_name] = description
    return power_component_description


def _target_button_get(target: ttbl.test_target, inventory: dict, kws: dict):
    '''
    Query the inventory to get the buttons jumpers and relays WITHOUT their
    states, we will get the state using a js call, since we don't want to slow
    down the html request

    :param ttbl.target_c target: target for which to find the
      buttons/relays/jumpers components

    :param dict inventory: result of doing target.to_dict(list()), we could do
      it inside the function but we usually already have it at the point the
      function is called. No need on querying it again.

    :param dict kws: keywords, used to  get the description of button component

    :return dict buttons_component_description:
        buttons_component_description is a dict with the following format:
            > buttons_component_description = {
            >     'button': 'button description',
            >     'reset': 'reset description',
            > }
        so, key = component, value = description
    '''
    # we DO NOT want to get the state of the components, meaning we do not want
    # to run `target.buttons._get(target)`, because if the target has a lot of
    # components, it will take a long way to check the status of them all. This
    # will slow the server response. Instead we just get the components, and
    # then with js do lazy loading to get the state.
    buttons_component_description = {}
    buttons_components = inventory.get('interfaces', {}).get('buttons', None)
    for component_name, component_value in buttons_components.items():
        if not isinstance(component_value, dict) or \
            component_value.get('instrument', None) is None:
            # this means that the component is not really a component, but
            # info on the power interface. We do not want to have it in
            # the power rail
            continue
        path = f"interfaces.buttons.{component_name}"
        kws['key'] = path
        description = target_description_get(target, path)
        buttons_component_description[component_name] = None
        if description:
            description = commonl.kws_expand(description, kws)
            buttons_component_description[component_name] = description
    return buttons_component_description


@bp.route('/target/<targetid>', methods = ['GET'])
@flask_login.login_required
def _target(targetid):
    '''
    Given a targetid get all its inventory as a dict, transform it to a
    string but with json format and indentation, to then render target.html
    template sending that stringify json and the targetid.
    '''
    target = ttbl.config.targets.get(targetid, None)
    if target is None:
        flask.abort(404, f"{targetid} not found in this server")

    calling_user = flask_login.current_user._get_current_object()
    if not target.check_user_allowed(calling_user):
        flask.abort(404, f"{targetid}: access not allowed")

    # FIXME: these two are always the same, we shall be able to
    # coalesce them
    inventory = target.to_dict(list())
    kws = target.kws_collect()

    # get owner
    owner = target.owner_get()
    # get type
    target_type =  inventory.get('type', 'n/a')

    # parse all the inventory to str
    inventory_str = json.dumps(inventory, indent = 4)
    who = ttbl.who_create(flask_login.current_user.get_id(), None)
    if who:
        acquired = target.target_is_owned_and_locked(who)
    else:
        acquired = False

    state = {
        'owner': owner,
        "user": calling_user.get_id(),
        'acquired': acquired,
        'type': target_type,
        'mac': _interconnect_values_render(inventory, "mac_addr", separator = " "),
        'ip': _interconnect_values_render(inventory, "ipv4_addr", separator = " "),
    }

    # get alloc info
    with target.lock:
        allocdb = target._allocdb_get()
        if allocdb == None:	# allocation was removed...shrug
            state["creator"] = "n/a"
            state['alloc'] = "n/a"
            state['user_is_admin'] = None
            state['user_is_guest'] = None
        else:
            state["creator"] =  allocdb.get("creator")
            state['alloc'] = allocdb.allocid
            state['user_is_admin'] = allocdb.check_user_is_admin(calling_user)
            state['user_is_guest'] = \
                allocdb.check_userid_is_guest(calling_user.get_id())

    # single IPs are at least 16 chars
    short_field_maybe_add(state, 'ip', 16)
    # single MACs are at least 18 chars
    short_field_maybe_add(state, 'mac', 18)

    if hasattr(target, "power"):
        power_component_description = _target_power_get(target, inventory, kws)
    else:
        power_component_description = {}

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
        # buttons interface is the same as the power interface...with
        # another name :)
        buttons_component_description = _target_button_get(target, inventory, kws)
    else:
        # we send an empty dict to the template, there we will check the
        # length. If zero we will disable the button for showing the
        # buttons/relays/jumpers table
        buttons_component_description = {}

    # more info about this tuple on the docstring of the function
    # `_get_images_paths`
    images, paths_for_all_images_types = \
        _get_images_paths(target, inventory, kws)

    # get console information for target.html to render
    # example:
    # consoles = {
    #   'ttyS0': {
    #       'instrument': 'hbq4',
    #       'check_ts': '1702313360.2028477',
    #       'crlf':  '\r ',
    #       'generation': '1702312127 ',
    #       'state':  True,
    #   },
    #   'other_console': {
    #   ...more
    consoles = dict(inventory.get('interfaces', {}).get('console', {}))

    return flask.render_template(
        'target.html',
        targetid = targetid,
        inventory_str = inventory_str,
        state = state,
        powerls = power_component_description,
        images = images,
        consoles = consoles,
        paths_for_all_images_types = paths_for_all_images_types,
        buttonls = buttons_component_description,
        servers_info = servers_info_get(),
    )

@bp.route('/targets/customize', methods = ['GET', 'POST'])
@flask_login.login_required
def _target_customize():
    '''
    This view will manage the customization of the targets table. If you do a
    GET it will render a table with the possible fields to choose as columns.

    If you do a POST it will record those fields in the user state directory
    secondary database
    '''
    if flask.request.method == 'GET':
        calling_user = flask_login.current_user._get_current_object()
        # query the user secondary db to see if he/she has preferred fields for the
        # targets table, meaning specific columns he/she want to see
        preferred_fields = \
            calling_user.fsdb_secondary.get('ui_preferred_fields_for_targets_table')
        preferred_fields = preferred_fields.split(',')

        # `all_fields` is a set that contains all the keys in inventory every
        # target has found. Not all targets have the same.
        all_fields = set()
        for targetid, target in ttbl.config.targets.items():
            if not target.check_user_allowed(calling_user):
                continue
            target = ttbl.config.targets.get(targetid, None)

            # we get all the keys from the target inventory flatten.
            # flatten_keys_w_values = [('a.b.c', 5), ('x.y', True), ('q', 'smth')]
            flatten_keys_w_values = commonl.dict_to_flat(target.tags, add_dict = False)
            flatten_keys_w_values += target.fsdb.get_as_slist()
            # we do not care about the value just the keys, it is a list of
            # tuples, so we can just do this.
            flatten_keys = [ full_value[0] for full_value in flatten_keys_w_values ]
            all_fields.update(flatten_keys)

        # remove `id` from the set since it will always display, also remove
        # any empty string
        all_fields = all_fields - {'id', ''}

        return flask.render_template(
            'custom_fields.html',
            servers_info = servers_info_get(),
            all_fields = all_fields,
            preferred_fields = preferred_fields,
        )

    if flask.request.method == 'POST':
        # the json expected has the following format
        # {"ui_preferred_fields_for_targets_table":
        #   "some,comma,separated,fields"
        #}
        try:
            posted_content = flask.request.get_json()
            # fields_to_store is a string with the fields separated by commas
            # something like 'id,type,ip,mac'
            # IMPORTANT assuming we do not have any fields in the inventory
            # with `,` in the name.
            fields_to_store = \
                posted_content.get('ui_preferred_fields_for_targets_table', '')
        except Exception as e: # make exception more specific
            return f'bad request {e}', 400 # FIXME improve response

        # we will be using calling_user.fsdb_secondary to interact with the db
        # fsdb_secondary. Go to `commonl/__init__.py:class:fsdb_symlink_c` for
        # more info
        calling_user = flask_login.current_user._get_current_object()
        calling_user.fsdb_secondary.set(
            key = 'ui_preferred_fields_for_targets_table',
            value = fields_to_store,
        )
        return flask.jsonify({ '_message': "the entry has been updated" })


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
                return flask.render_template(
                    'forbidden.html', servers_info = servers_info_get()), 403

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
                "user_is_owner_creator": \
                    allocdb.check_user_is_user_creator(calling_user),
                "user_is_admin": allocdb.check_user_is_admin(calling_user),
            }
            guests = []
            for guest in allocdb.guest_list():
                if guest:
                    guests.append(guest)

            return flask.render_template(
                'allocation.html',
                allocid = allocid, state = state, guests = guests,
                servers_info = servers_info_get(),
            )

        except commonl.fsdb_symlink_c.invalid_e as e:
            # lets not crash if the user is trying to access an allocation
            # that does not exist. We can just redirect him to the
            # allocations table
            return flask.redirect(flask.url_for('ui._allocation_ui'))
        except Exception as e:
            flask_logi_abort(
                400, f"exception rendering /ui/allocation/{allocid}: {e}",
                exc_info = True)


def _image_display_text_default_maker(path: pathlib.Path, info: dict = {}) -> str:
    '''
    Return a string that will be displayed in the dropdown menu where the
    firmwares available for flashing are.

    You can overwrite this function by setting a different one to the variable
    `image_display_text_maker`, for example, in a config file you could do:

    >>> import ttbl.ui
    >>>
    >>> def custom_display_text_func(path, info):
    >>>     return 'hello world' + path.split()[-1]
    >>>
    >>> ttbl.ui.image_display_text_maker = custom_display_text_func
    >>>

    And then in the dropdown you would see all the entries starting with 'hello
    world'

    param:path:pathlib.Path|str:
        full path to fw file

    param:info:dict:
        dictionary that contains information on the fw, BUT, for this use case,
        as long as you send a dict with the 'prefix' key (the path prefix that
        is) it will work
    '''
    if 'prefix' in info:
        return path[len(info['prefix']) + 1:]

    # not enough context for generating a short name to display, defaulting to
    # the whole path
    return path

image_display_text_maker = _image_display_text_default_maker

def _get_images_paths(target: ttbl.test_target, inventory: dict, kws: dict):
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

        # let's add description, if present
        path = f"interfaces.images.{image_type}"
        kws['key'] = path
        description = target_description_get(target, path)
        if description:
            description = commonl.kws_expand(description, kws)
            images[image_type]['description'] = description

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
            for full_path in sorted(local_list):
                file_data = {}
                directory, filename = os.path.split(full_path)

                # short_name is the string that will be displayed in the ui
                # dropdown
                # format for short_name: 'directory - filename'
                #
                # we add the name of the filename at the end because you could
                # have multiple fw in the same directory and it becomes
                # confusing which is which to the user
                info = {'prefix': prefix_formatted}
                short_name = image_display_text_maker(directory, info)
                file_data['short_name'] = f'{short_name} - {filename}'

                if hasattr(ttbl.ui,'keywords_to_ignore_when_path'):
                    for keyword in ttbl.ui.keywords_to_ignore_when_path:
                        if keyword in filename:
                            filename = filename.split(keyword)[0]
                file_list[full_path] = file_data
                images_by_path[directory].setdefault("images", set())
                images_by_path[directory]["images"].add(filename)
                images_by_path[directory]["prefix"] = prefix_formatted

        images[image_type]['file_list'] = file_list

    # we need a list of the paths that can flash all target's images.
    # we identify which paths contain all the images types and append it to the
    # list.
    # you now could render a dropdown menu with the paths that could flash
    # all fw in a target
    paths_for_all_images_types = []
    for path, info in images_by_path.items():
        count = 0
        for image_type in images.keys():
            # let's append the image suffix (if any) to match the file name
            image_type = image_type + images[image_type].get('suffix', '')
            if image_type in info['images']:
                count += 1

        # not found all fw in the path, let's continue and try with the next
        # one
        if count != len(images.keys()): continue

        # found all fw in the path
        list_item = {}
        list_item['paths'] = path + '/'
        list_item['short_name'] = image_display_text_maker(path, info)
        paths_for_all_images_types.append(list_item)

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

    return flask.render_template(
        'allocations.html',
        allocs = allocs,
        servers_info = servers_info_get()
    )


@bp.before_app_request
def load_logged_in_user():
    user = flask.session.get('user')
    if user is None:
        flask.g.user = None
    else:
        flask.g.user = user
