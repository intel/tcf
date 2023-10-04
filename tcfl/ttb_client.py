#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

#
# FIXME: cache the target list's per target broker into a pickled
#   ${TCF_CACHE:-~/.tcf/cache}/BROKER.cache; use the cache instead of
#   calling target_list(); implement cache-refresh command.
# FIXME: do a python iterator over the targets
"""
Client API for accessing *ttbd*'s REST API
------------------------------------------

This API provides a way to access teh REST API exposed by the *ttbd*
daemon; it is divided in two main blocks:

 - :class:`rest_target_broker`: abstracts a remote *ttbd* server and
   provides methods to run stuff on targets and and connect/disconnect
   things on/from targets.

 - `rest_*()` methods that take a namespace of arguments, lookup the
   object target, map it to a remote server, execute the method and
   then print the result to console.

   This breakup is a wee arbitrary, it can use some cleanup

"""
# FIXME: this is crap, need to move all the functions to core or something
import pickle
import collections
import contextlib
import errno
import getpass
import hashlib
import json
import logging
import math
import os
import pprint
import re
import requests
import requests.exceptions
import struct
import sys
import threading
import time
import urllib.parse

import requests
import commonl

logger = logging.getLogger("tcfl.ttb_client")


# We multithread to run testcases in parallel
#
# When massively running threads in production environments, we end up
# with hundreds/thousands of threads based on the setup which are just
# launching a build and waiting. However, sometimes something dies
# inside Python and leaves the thing hanging with the GIL taken and
# everythin deadlocks.
#
# For those situations, using the PathOS/pools library works better,
# as it can multithread as processes (because of better pickling
# abilities) and doesn't die.
#
# So there, the PATHOS.multiprocess library if available and in said
# case, use process pools for the testcases.

_multiprocessing_pool_c = None

def import_mp_pathos():
    import pathos.multiprocessing
    global _multiprocessing_pool_c
    _multiprocessing_pool_c = pathos.pools._ThreadPool

def import_mp_std():
    import multiprocessing.pool
    global _multiprocessing_pool_c
    _multiprocessing_pool_c = multiprocessing.pool.ThreadPool

mp = os.environ.get('TCF_USE_MP', None)
if mp == None:
    try:
        import_mp_pathos()
    except ImportError as e:
        import_mp_std()
elif mp.lower() == 'std':
    import_mp_std()
elif mp.lower() == 'pathos':
    import_mp_pathos()
else:
    raise RuntimeError('Invalid value to TCF_USE_MP (%s)' % mp)

if hasattr(requests, "packages"):
    # Newer versions of Pyython will complain loud about unverified certs
    requests.packages.urllib3.disable_warnings()

tls = threading.local()


def tls_var(name, factory, *args, **kwargs):
    value = getattr(tls, name, None)
    if value == None:
        value = factory(*args, **kwargs)
        setattr(tls, name, value)
    return value


global rest_target_brokers
rest_target_brokers = {}

# Export all SSL keys to a file, so we can analyze traffic on wireshark & friends
if 'SSLKEYLOGFILE' in os.environ:
    import sslkeylog
    sslkeylog.set_keylog(os.environ['SSLKEYLOGFILE'])


# Caching disable; causes more problems than it fixes
#@commonl.lru_cache_disk(
#    os.path.join(os.path.expanduser("~"), ".cache", "tcf", "_rts_get"),
#    3 * 60,	# refresh every three minutes? why? because until we
#                # all move to the second ls implementation, this
#                # contains power and ownership info that can change
#                # frequently...
#    500,	# keep max 500 entries (one per server)
#    key_maker = lambda rtb: rtb._url)
def _rts_get_cached(rtb):
    ts0 = time.time()
    try:
        rt_list = rtb.rest_tb_target_list(all_targets = True)
        for rt in rt_list:
            # remove 'rtb' because this (a) was a bad idea but now it
            # is everywhere and needs cleanup, which the new code
            # handles alreday; (b) we can't cache it, so we add it
            # after reading it from the cache for the benefir of the
            # code that needs it; see code that calls _rts_get_cached
            del rt['rtb']
    except requests.exceptions.RequestException as e:
        logger.error("%s: can't use: %s", rtb._url, e)
        return {}
    ts = time.time()
    logging.warning(f"{rtb}: refreshing inventory took {ts-ts0:.02f}s")
    return rtb._rt_list_to_dict(rt_list)


class _rest_target_broker_mc(type):
    """
    This metaclass is used to create the methods that are needed on
    the initialization of each instance.
    """
    @classmethod
    def _rts_get(cls, rtb):
        try:
            rt_list = rtb.rest_tb_target_list(all_targets = True)
        except requests.exceptions.RequestException as e:
            logger.error("%s: can't use: %s", rtb._url, e)
            return {}
        return rtb._rt_list_to_dict(rt_list)

    @property
    def rts_cache(cls):
        if cls._rts_cache != None:
            return cls._rts_cache
        if not rest_target_brokers:
            cls._rts_cache = {}
            return cls._rts_cache
        # Collect the targets into a list of tuples (FULLID, SUFFIX),
        # where suffix will be *! (* if powered, ! if owned)
        # Yes, there are better ways to do this, but this one
        # is simple -- just launch one thread per server and
        # then collect the data in a single cache -- shall use
        # process pool, for better performance, but can't get
        # it to serialize properly
        tp = _multiprocessing_pool_c(processes = len(rest_target_brokers))
        threads = {}
        for rtb in sorted(rest_target_brokers.keys()):
            threads[rtb] = tp.apply_async(_rts_get_cached, (rest_target_brokers[rtb],))
        tp.close()
        tp.join()
        cls._rts_cache = {}
        for rtb, thread in threads.items():
            # add back rtb bc it can't be cached, see _rts-get_cached
            try:
                rts = thread.get()
                for rt in rts.values():
                    rt['rtb'] = rest_target_brokers[rtb]
                cls._rts_cache.update(rts)
            except RuntimeError as e:
                logging.warning(f"{rtb}: skipping reading targets: {e}")
        return cls._rts_cache


class rest_target_broker(object, metaclass = _rest_target_broker_mc):

    # Hold the information about the remote target, as acquired from
    # the servers
    _rts_cache = None
    # FIXME: WARNING!!! hack only for tcf list's commandline
    # --projection; don't use for anything else, needs to be cleaned
    # up.
    projection = None

    API_VERSION = 2
    API_PREFIX = "/ttb-v" + str(API_VERSION) + "/"

    port_default = 5000

    def __init__(self, state_path, url, ignore_ssl = False, aka = None,
                 ca_path = None, origin = None):
        """Create a proxy for a target broker, optionally loading state
        (like cookies) previously saved.

        :param str state_path: Path prefix where to load state from
        :param str url: URL for which we are loading state
        :param bool ignore_ssl: Ignore server's SSL certificate
           validation (use for self-signed certs).
        :param str aka: Short name for this server; defaults to the
           hostname (sans domain) of the URL.
        :param str ca_path: Path to SSL certificate or chain-of-trust bundle
        :returns: True if information was loaded for the URL, False otherwise
        """
        self._url = url
        self._base_url = None
        self.cookies = {}
        self.valid_session = None
        self.origin = origin
        if ignore_ssl == True:
            self.verify_ssl = False
        elif ca_path:
            self.verify_ssl = ca_path
        else:
            self.verify_ssl = True
        self.lock = threading.Lock()
        self.parsed_url = urllib.parse.urlparse(url)
        if self.parsed_url.port == None:
            port = self.port_default
        else:
            port = self.parsed_url.port
        if aka == None:
            # hostname is something.other.whatever, so get the
            # hostname, append the port where this is probably
            # listening to make a human-friendly unique ID
            self.aka = self.parsed_url.hostname.split('.')[0] + f"_{port}"
        else:
            assert isinstance(aka, str)
            self.aka = aka
        # Load state
        url_safe = commonl.file_name_make_safe(url)
        file_name = os.path.join(state_path, "cookies-%s.pickle" % url_safe)
        try:
            with open(file_name, "rb") as f:
                self.cookies = pickle.load(f)
            logger.info("%s: loaded state", file_name)
        except pickle.UnpicklingError as e: #invalid state, clean file
            os.remove(file_name)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise e
            else:
                logger.debug("%s: no state-file, will not load", file_name)
        #: Version of the code ran by the server; filled up when we do
        #: the first target list, from the target local, metadata
        #: versions.server; done in _rts_get() _> _rt_list_to_dict()
        #:
        #: Used to adjust backwards compat for short periods of time
        self.server_version = None

        #: Major version of the server code
        self.server_version_major = None
        #: Minor version of the server code
        self.server_version_minor = None
        self.server_version_pl = 0
        #: Changes since the major/minor version tag
        self.server_version_changes = None
        
        #: Server can take all arguments JSON encoded
        #:
        #: Previous servers woul donly take as JSON things are are not
        #: strings, numbers, bools. Newer can do both, since this
        #: allows the server to also be used from curl command line
        #: with much ado.
        #:
        #: This allows us to transition the code without major changes
        #: to the code or hard dependencies.
        self.server_json_capable = True

    # Make sure we support
    # vN.N.N-N-STR[MORESTUFF]	older
    # vN.N.N.N.STR[MORESTUFF]	newer (to support RPM)
    _server_version_regex = re.compile(
        r"v?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)(\.(?P<pl>[0-9]+))?"
        r"([\.-](?P<changes>[0-9]+))?"
        r"([\.-](?P<rest>.+))?$")

    def _server_tweaks(self, version):
        if self.server_version != None:
            return	# already done
        if version == None:
            return	# can't do, no info
        self.server_version = version

        # Server version is like:
        #
        ## [v]0.13[.pl][-202[-gf361416]]
        #
        # if not, this is an implementation we know not how to handle
        m = self._server_version_regex.match(version)
        if not m:
            return
        gd = m.groupdict()

        # remove anything that wasn't found (value None) so we can get
        # defaults, because otherwise is filled as a value of None
        for k, v in list(gd.items()):
            if v == None:
                del gd[k]
        self.server_version_major = int(gd.get('major', 0))
        self.server_version_minor = int(gd.get('minor', 0))
        self.server_version_pl = gd.get('pl', 0)
        self.server_version_changes = int(gd.get('changes', 0))

        if self.server_version_major == 0:
            if self.server_version_minor == 13:
                # protocol changes
                if self.server_version_changes <= 202:
                    self.server_json_capable = False

    def __str__(self):
        return self.parsed_url.geturl()

    def _rt_list_to_dict(self, rt_list):
        rts = {}
        for rt in rt_list:
            rt_fullid = rt['fullid']
            # Introduce two symbols after the ID and fullid, so "-t
            # TARGETNAME" works
            rt[rt_fullid] = True
            rt[rt['id']] = True
            if rt['id'] == 'local':	# magic! server description
                self._server_tweaks(rt.get('versions', {}).get('server', None))
            rts[rt_fullid] = rt
        return rts

    class __metaclass__(type):
        @classmethod
        def _rts_get(cls, rtb):
            try:
                # FIXME: the projection thing is a really bad hack so
                #        that the command line 'tcf list' can use
                #        --projection, until we clean that up.
                rt_list = rtb.rest_tb_target_list(
                    all_targets = True,
                    projection = rest_target_broker.projection)
            except requests.exceptions.RequestException as e:
                logger.error("%s: can't use: %s", rtb._url, e)
                return {}
            return rtb._rt_list_to_dict(rt_list)

        @property
        def rts_cache(cls):
            if cls._rts_cache != None:
                return cls._rts_cache
            if not rest_target_brokers:
                cls._rts_cache = {}
                return cls._rts_cache
            # Collect the targets into a list of tuples (FULLID, SUFFIX),
            # where suffix will be *! (* if powered, ! if owned)
            # Yes, there are better ways to do this, but this one
            # is simple -- just launch one thread per server and
            # then collect the data in a single cache -- shall use
            # process pool, for better performance, but can't get
            # it to serialize properly
            tp = _multiprocessing_pool_c(processes = len(rest_target_brokers))
            threads = {}
            for rtb in sorted(list(rest_target_brokers.values())):
                threads[rtb] = tp.apply_async(_rts_get_cached, (rtb,))
            tp.close()
            tp.join()
            cls._rts_cache = {}
            for rtb, thread in threads.items():
                # add back rtb bc it can't be cached, see
                # _rts_get_cached
                # there is code in rest_target_broker_mc which is a
                # dup of this and needs to be purgedo
                try:
                    rts = thread.get()
                    for rt in rts.values():
                        rt['rtb'] = rest_target_brokers[rtb]
                        cls._rts_cache.update(rts)
                except RuntimeError as e:
                    logging.warning(f"{rtb}: skipping reading targets: {e}")
            return cls._rts_cache

    @classmethod
    def rts_cache_flush(cls):
        del cls._rts_cache
        cls._rts_cache = None

    # FIXME: this timeout has to be proportional to how long it takes
    # for the target to flash, which we know from the tags
    def send_request(self, method, url,
                     data = None, json = None, files = None,
                     stream = False, raw = False,
                     timeout = 160, timeout_extra = None,
                     retry_timeout = 0, retry_backoff = 0.5,
                     skip_prefix = False):
        """
        Send request to server using url and data, save the cookies
        generated from request, search for issues on connection and
        raise and exception or return the response object.

        :param str url: url to request
        :param dict data: args to send in the request. default None
        :param str method: method used to request GET, POST and
          PUT. Defaults to PUT.
        :param bool raise_error: if true, raise an error if something goes
           wrong in the request. default True

        :param int timeout_extra: extra timeout on top of the
          *timeout* variable; this is meant to add extra timeouts from
          environment.
-
          If *None*, take the extra timeout from the environment
          variable *TCFL_TIMEOUT_EXTRA*.

        :param float retry_timeout: (optional, default 0--disabled)
          how long (in seconds) to retry connections in case of failure
          (:class:`requests.exceptions.ConnectionError`,
          :class:`requests.exceptions.ReadTimeout`)

          Note a retry can have side effects if the request is not
          idempotent (eg: writing to a console); retries shall only be
          enabled for GET calls. Support for non-idempotent calls has
          to be added to the protocol.

          See also :meth:`tcfl.tc.target_c.ttbd_iface_call`

        :returns requests.Response: response object

        """
        assert not (data and json), \
            "can't specify data and json at the same time"
        assert isinstance(retry_timeout, (int, float)) and retry_timeout >= 0, \
            f"retry_timeout: {retry_timeout} has to be an int/float >= 0"
        assert isinstance(retry_backoff, (int, float)) and retry_backoff > 0
        if retry_timeout > 0:
            assert retry_backoff < retry_timeout, \
                f"retry_backoff {retry_backoff} has to be" \
                f" smaller than retry_timeout {retry_timeout}"
        if timeout == None:
            timeout = 160
        else:
            assert timeout >= 0, \
                "timeout: expected must be positive" \
                " number of seconds;  got {timeout}"
        if timeout_extra == None:
            timeout_extra = int(os.environ.get("TCFL_TIMEOUT_EXTRA", 0))
        assert timeout_extra >= 0, \
            "TCFL_TIMEOUT_EXTRA: (from environment) must be positive" \
            " number of seconds;  got {timeout_extra}"
        timeout += timeout_extra

        # create the url to send request based on API version
        if url.startswith("/"):
            url = url[1:]
        if not self._base_url:
            self._base_url = urllib.parse.urljoin(
                self._url, rest_target_broker.API_PREFIX)
        if skip_prefix:
            url_request = urllib.parse.urljoin(self.parsed_url.geturl(), url)
        else:
            url_request = urllib.parse.urljoin(self._base_url, url)
        logger.debug("send_request: %s %s", method, url_request)
        with self.lock:
            cookies = dict(self.cookies)
        # lock keep the sessions per-host/port, otherwise the cookies
        # will be messed up
        session = tls_var("session" + self.parsed_url.netloc, requests.Session)

        retry_count = -1
        retry_ts = None
        r = None
        while True:
            retry_count += 1
            try:
                if method == 'GET':
                    r = session.get(url_request, cookies = cookies, json = json,
                                    data = data, verify = self.verify_ssl,
                                    stream = stream, timeout = (timeout, timeout))
                elif method == 'PATCH':
                    r = session.patch(url_request, cookies = cookies, json = json,
                                      data = data, verify = self.verify_ssl,
                                      stream = stream, timeout = ( timeout, timeout ))
                elif method == 'POST':
                    r = session.post(url_request, cookies = cookies, json = json,
                                     data = data, files = files,
                                     verify = self.verify_ssl,
                                     stream = stream, timeout = ( timeout, timeout ))
                elif method == 'PUT':
                    r = session.put(url_request, cookies = cookies, json = json,
                                    data = data, verify = self.verify_ssl,
                                    stream = stream, timeout = ( timeout, timeout ))
                elif method == 'DELETE':
                    r = session.delete(url_request, cookies = cookies, json = json,
                                       data = data, verify = self.verify_ssl,
                                       stream = stream, timeout = ( timeout, timeout ))
                else:
                    raise AssertionError("{method}: unknown HTTP method" )
                break
            except (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout,
            ) as e:
                # Retry only these; note these cannot report
                # Report how many retries we have done, wait a backoff
                # and then loop it.
                if retry_timeout == 0:
                    raise
                ts = time.time()
                if retry_ts == None:
                    retry_ts = ts	# first one
                else:
                    if ts - retry_ts > retry_timeout:
                        raise RuntimeError(
                            f"{url_request}: giving up after {retry_timeout}s"
                            f" retrying {retry_count} connection errors") from e
                time.sleep(retry_backoff)
                # increase the backoff to avoid pestering too much,
                # but make sure it doesn't get too big so we at least
                # get 10 tries in the timeout period
                if retry_backoff < retry_timeout / 10:
                    retry_backoff *= 1.2
                continue


        #update cookies
        if len(r.cookies) > 0:
            with self.lock:
                # Need to update like this because r.cookies is not
                # really a dict, but supports items() -- overwrite
                # existing cookies (session cookie) and keep old, as
                # it will have the stuff we need to auth with the
                # server (like the remember_token)
                # FIXME: maybe filter to those two only?
                for cookie, value in r.cookies.items():
                    self.cookies[cookie] = value
        commonl.request_response_maybe_raise(r)
        if raw:
            return r
        rdata = r.json(object_pairs_hook = collections.OrderedDict)
        if '_diagnostics' in rdata:
            diagnostics = rdata.pop('_diagnostics')
            # this is not very...memory efficient
            for line in diagnostics.split("\n"):
                logger.warning("diagnostics: " + line)
        return rdata

    def login(self, email, password):
        data = {"email": email, "password": password}
        try:
            self.send_request('PUT', "login", data)
        except requests.exceptions.HTTPError as e:
            if e.status_code == 404:
                logger.error("%s: login failed: %s", self._url, e)
            return False
        return True

    def logged_in_username(self):
        """
        Return the user name logged into a server

        Based on the cookies, ask the server to translate the special name
        *self* to the currently logged in user with the cookies stored.

        :returns: name of the user we are logged in as
        """
        r = self.send_request("GET", "users/self")
        # this call returns a dictionary with the user name in the
        # key name, because we asked for "self", the server will
        # return only one, but maybe also fields with diagnostics, that
        # start with _; filter them
        for username in r:
            if not username.startswith("_"):
                break
            else:
                raise RuntimeError(
                    "server can't translate user 'self'; got '%s'" % ur)
        return username

    def validate_session(self, validate = False):
        if self.valid_session is None or validate:
            valid_session = False
            r = None
            try:
                r = self.send_request('GET', "validate_session")
                if 'status' in r and r['status'] == "You have a valid session":
                    valid_session = True
            except requests.exceptions.HTTPError:
                # Invalid session
                pass
            finally:
                with self.lock:
                    self.valid_session = valid_session
        return valid_session

    def rest_tb_target_list(self, all_targets = False, target_id = None,
                            projection = None):
        """
        List targets in this server

        :param bool all_targets: If True, include also targets that are marked
          as disabled.
        :param str target_id: Only get information for said target id
        """
        if projection:
            data = { 'projections': json.dumps(projection) }
        else:
            data = None
        if target_id:
            r = self.send_request("GET", "targets/" + target_id, data = data,
                                  # retry a few times
                                  retry_timeout = 2)
            # FIXME: imitate same output format until we unfold all
            # these calls--it was a bad idea
            if not 'targets' in r:
                target_list = [ r ]
        else:
            # force a short timeout to get rid of failing servers quick
            r = self.send_request("GET", "targets/",
                                  data = data, timeout = 20,
                                  # retry a few times
                                  retry_timeout = 2)
            if 'targets' in r:		# old version, deprecated # COMPAT
                target_list = r['targets']
            else:
                target_list = list(r.values())	# new, target dict
        _targets = []
        for rt in target_list:
            # Skip disabled targets
            if target_id != None and rt.get('disabled', None) != None \
               and all_targets != True:
                continue
            rt['fullid'] = self.aka + "/" + rt['id']
            # FIXME: hack, we need this for _rest_target_find_by_id,
            # we need to change where we store it in this cache
            rt['rtb'] = self
            _targets.append(rt)
        return _targets

    def rest_tb_target_update(self, target_id):
        """
        Update information about a target

        :param str target_id: ID of the target to operate on
        :returns: updated target tags
        """
        fullid = self.aka + "/" + target_id
        r = self.rest_tb_target_list(target_id = target_id, all_targets = True)
        if r:
            rtd = self._rt_list_to_dict(r)
            # Update the cache
            type(self)._rts_cache.update(rtd)
            return rtd[fullid]
        else:
            raise ValueError("%s/%s: unknown target" % (self.aka, target_id))

    def rest_tb_target_acquire(self, rt, ticket = '', force = False):
        return self.send_request("PUT", "targets/%s/acquire" % rt['id'],
                                 data = { 'ticket': ticket, 'force': force })

    def rest_tb_target_active(self, rt, ticket = ''):
        self.send_request("PUT", "targets/%s/active" % rt['id'],
                          data = { 'ticket': ticket })

    def rest_tb_target_release(self, rt, ticket = '', force = False):
        self.send_request(
            "PUT", "targets/%s/release" % rt['id'],
            data = { 'force': force, 'ticket': ticket })



def rest_init(path, url, ignore_ssl = False, aka = None, origin = None):
    """
    Initialize access to a remote target broker.

    :param state_path: Path prefix where to load state from
    :type state_path: str
    :param url: URL for which we are loading state
    :type url: str
    :returns: True if information was loaded for the URL, False otherwise
    """
    rtb = rest_target_broker(path, url, ignore_ssl, aka, origin = origin)
    # ensure the URL is normalized
    # FIXME: move this to the constructor
    rest_target_brokers[rtb.parsed_url.geturl()] = rtb
    return rtb



def rest_target_print(rt, verbosity = 0):
    """
    Print information about a REST target taking into account the
    verbosity level from the logging module

    :param rt: object describing the REST target to print
    :type rt: dict

    """
    if verbosity == 0:
        print("%(fullid)s" % rt)
    elif verbosity == 1:
        # Simple list, just show owner and power state
        if 'powered' in rt:
            # having that attribute means the target is powered; otherwise it
            # is either off or has no power control
            power = " ON"
        else:
            power = ""
        allocid = rt.get('_alloc', {}).get('id', None)
        owner = rt.get('owner', None)
        if allocid or owner:
            ownerl = []
            if owner:
                ownerl.append(owner)
            if allocid:
                ownerl.append(allocid)
            owner_s = "[" + ":".join(ownerl) + "]"
        else:
            owner_s = ""
        print("%s %s%s" % (rt['fullid'], owner_s, power))
    elif verbosity == 2:
        print(rt['fullid'])
        commonl.data_dump_recursive(rt, prefix = rt['fullid'])
    elif verbosity == 3:
        pprint.pprint(rt)
    else:
        print(json.dumps(rt, skipkeys = True, indent = 4))

def _rest_target_find_by_id(_target):
    """
    Find a target by ID.

    Ignores if the target is disabled or enabled.

    :param str target: Target to locate; it can be a *name* or a full *url*.
    """
    # Try to see if it is cached by that ID
    rt = rest_target_broker.rts_cache.get(_target, None)
    if rt != None:
        return rt['rtb'], rt
    # Dirty messy search
    for rt in rest_target_broker.rts_cache.values():
        if rt['id'] == _target:
            return rt['rtb'], rt
    raise IndexError("target-id '%s': not found" % _target)

def _rest_target_broker_find_by_id_url(target):
    # Note this function finds by ID and does nt care if the target is
    # disabled or enabled
    if target in rest_target_brokers:
        return rest_target_brokers[target]
    rtb, _rt = _rest_target_find_by_id(target)
    return rtb


def _target_select_by_spec( rt, spec, _kws = None):
    if not _kws:
        _kws = {}
    origin = "cmdline"
    # FIXME: merge with tcfl.tc.t_c._targets_select_by_spec()
    # We are going to modify the _kws dict, so make a copy!
    kws = dict(_kws)
    # We don't consider BSP models, just iterate over all the BSPs
    bsps = list(rt.get('bsps', {}).keys())
    kws['bsp_count'] = len(bsps)
    kws_bsp = dict()
    commonl.kws_update_from_rt(kws, rt)
    rt_full_id = rt['fullid']
    rt_type = rt.get('type', 'n/a')

    for bsp in bsps:
        kws_bsp.clear()
        kws_bsp.update(kws)
        kws_bsp['bsp'] = bsp
        commonl.kws_update_type_string(kws_bsp, rt['bsps'][bsp])
        logger.info("%s/%s (type:%s): considering by spec",
                    rt_full_id, bsp, rt_type)
        if commonl.conditional_eval("target selection", kws_bsp,
                                    spec, origin, kind = "specification"):
            # This remote target matches the specification for
            # this target want
            logger.info("%s/%s (type:%s): candidate by spec",
                        rt_full_id, bsp, rt_type)
            return True
        else:
            logger.info(
                "%s/%s (type:%s): ignoring by spec; didn't match '%s'",
                rt_full_id, bsp, rt_type, spec)
    if bsps == []:
        # If there are no BSPs, just match on the core keywords
        if commonl.conditional_eval("target selection", kws,
                                    spec, origin, kind = "specification"):
            # This remote target matches the specification for
            # this target want
            logger.info("%s (type:%s): candidate by spec w/o BSP",
                        rt_full_id, rt_type)
            return True
        else:
            logger.info("%s (type:%s): ignoring by spec w/o BSP; "
                        "didn't match '%s'", rt_full_id, rt_type, spec)
            return False



def rest_target_list_table(targetl):
    """
    List all the targets in a table format, appending * if powered
    up, ! if owned.
    """

    # Collect the targets into a list of tuples (FULLID, SUFFIX),
    # where suffix will be *! (* if powered, ! if owned)

    l = []
    # this is a weird hack to only print short IDs when the target
    # name is not duplicated, since otherwise it can get too long if
    # both the server and the target are long and the target name has
    # enough info--needs something much more generic and centralized
    # in general for any user-facing ID reporting.
    targetl_counts = collections.Counter(rt['id'] for rt in targetl)
    for rt in targetl:
        suffix = ""
        if rt.get('owner', None):	# target might declare no owner
            suffix += "@"
        if 'powered' in rt:
            # having that attribute means the target is powered;
            # otherwise it is either off or has no power control
            suffix += "!"
        if targetl_counts[rt['id']] > 1:
            target_id = rt['fullid']
        else:
            target_id = rt['id']
        l.append(( target_id, suffix ))
    if not l:
        return

    # Figure out the max target name length, so from there we can see
    # how many entries we can fit per column. Note that the suffix is
    # max two characters, separated from the target name with a
    # space and we must leave another space for the next column (hence
    # +4).
    ts = os.get_terminal_size()
    display_w = ts.columns

    maxlen = max([len(i[0]) for i in l])
    columns = int(math.floor(display_w / (maxlen + 4)))
    if columns < 1:
        columns = 1
    rows = int((len(l) + columns - 1) / columns)

    # Print'em sorted; filling out columns first -- there might be a
    # more elegant way to do it, but this one is quite simple and I am
    # running on fumes sleep-wise...
    l = sorted(l)
    for row in range(rows):
        for column in range(columns):
            index = rows * column + row
            if index >= len(l):
                break
            i = l[index]
            sys.stdout.write("{fullid:{column_width}} {suffix:2} ".format(
                fullid = i[0], suffix = i[1], column_width = maxlen))
        sys.stdout.write("\n")

def cmdline_list(spec_strings, do_all = False):
    """
    Return a list of dictionaries representing targets that match the
    specification strings

    :param list(str) spec_strings: list of strings that put together
      with a logical *and* bring the logical specification

    :param bool do_all: (optional) include also disabled targets
      (defaults to *False*)
    """
    specs = []
    # Bring in disabled targets? (note the field is a text, not a
    # bool, if it has anything, the target is disabled
    if do_all != True:
        specs.append("( not disabled )")
    # Bring in target specification from the command line (if any)
    if spec_strings:
        specs.append("(" + ") or (".join(spec_strings) +  ")")
    spec = " and ".join(specs)

    targetl = []
    for _fullid, rt in sorted(rest_target_broker.rts_cache.items(),
                              key = lambda x: x[0]):
        # add the remote target info as a dictionary and ...
        kws = dict(rt)
        #  ... as a flattened dictionary
        for key, val in commonl.dict_to_flat(rt,
                                             sort = False, empty_dict = True):
            kws[key] = val
        if spec and not _target_select_by_spec(kws, spec):
            continue
        targetl.append(rt)
    return targetl


def rest_target_list(args):

    if args.projection:
        rest_target_broker.projection = args.projection

    targetl = cmdline_list(args.target, args.all)
    if args.verbosity < 1 and sys.stderr.isatty() and sys.stdout.isatty():
        rest_target_list_table(targetl)
        return
    else:
        if  args.verbosity == 4:
            # print as a JSON dump
            for rt in targetl:
                rtb = rt.pop('rtb')
                rt['rtb'] = str(rtb)
            print(json.dumps(targetl, skipkeys = True, indent = 4))
        else:
            for rt in targetl:
                rest_target_print(rt, args.verbosity)


def rest_target_find_all(all_targets = False):
    """
    Return descriptors for all the known remote targets

    :param bool all_targets: Include or not disabled targets
    :returns: list of remote target descriptors (each being a dictionary).
    """
    if all_targets == True:
        return list(rest_target_broker.rts_cache.values())
    targets = []
    for rt in list(rest_target_broker.rts_cache.values()):
        if rt.get('disabled', None) != None:
            continue
        targets.append(rt)
    return targets
