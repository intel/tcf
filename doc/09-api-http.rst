.. _ttbd_api_http:

The HTTP API exported by *ttbd* is a basic REST model.

This API is designed to manage resources that require access to them
from a remote location, interactively (by humans doing operations) or
by scripts/automation frameworks following a sequence of steps.

The API is broken up in four general sections:

- user management (login, logout, roles)

- inventory handling (discovery of targets)

- allocation handling (allocate one or more targets for exclusive
  user, management of allocations, etc)

- instrumentation (observe and manipulate target state, eg: power on,
  off, flash, screenshots, etc...)


General API design considerations
---------------------------------

The API is rooted at::

  http[s]://SERVERNAME:PORT/ttb-vVERSION]/

Servers are configured by default to listen on port 5000, although
others are possible. All endpoints are prefixed by */ttb-v2* (v2 being
the current version of the protocol). Thus endpoint *login* would
be referred to as::

  http://SERVERNAME:PORT/ttb-v2/login

when a target is affected, it is referred with *targets/TARGETNAME*;
thus the endpoint to power on a target *power/on*

  http://SERVERNAME:PORT/ttb-v2/targets/TARGETNAME/power/on

In the documentation, the term *http://SERVER* will refer to
*http[s]://SERVERNAME:PORT*.

Arguments are encoded as HTTP form fields with non escalar arguments
(lists, dictionaries) are JSON encoded. Arguments can also be passed
as a JSON dictionary in the request body.

Except when called out, calls return a JSON dictionary in the body
with result data in the dictionary keys. It might also include some of
the following standard fields:

- *_message*: a message explaining the error or success condition

- *_diagnostics*: diagnostics information (in the form of string, list
  of strings or others). This information might be restricted to users
  with *admin* roles.

A succesful call returns an HTTP status code 200; any other denotes an
error and the dictionary keys *_message* and *_diagnostics* (when
present) provides more information.

Conventions for examples
------------------------

This document will use the *curl* command line to tool to showcase
calls to the API, in the form::

  $ curl -c cookies.txt -k -X PUT https://SERVERNAME:5000:PORT/ttb-v2/login \
  -d password=PASSWORD -d username=USERNAME

The command line options used are:

- *-i*: to show the response headers, like the HTTP code
- *-c cookies.txt*: save the cookies to a file called cookies.txt
- *-k*: do not do SSL certificate verification (this depends on your
  client machine having certificates installed or not)
- *-X PUT*: place an HTTP PUT request (or GET, PATCH...)
- *-d KEY=VAL*: means pass an HTTP argument to the call in the body as
  form or json.
- *-s*: silent, skip printing progress information

optionally the output of *curl* will be piped through *python -m
json.tool* to pretty-format the JSON output for clarity.


User management (login, logout, roles)
--------------------------------------

Any agent needing to use the API needs to first authenticate by
calling the login method. This returns cookies that then need to be
passed to any other calls to the system for authenticated acces.

Users are assigned roles by the authentication mechanism configured in
the server; these are names (short strings) which which can be used to
control access to the system. A user has one or more roles at any
given time and at least it must have one role: *user*. The following
roles are predefined:

- user: a normal user with non-privileged access to the system

- admin: a user with access to non-privileged and privileged areas of
  the system

other roles are created and given at the system administrators
discretion to use for access control to targets (see
:ref:`roles_required <roles_required>` and :ref:`roles_excluded
<roles_excluded>`).


PUT /login username=USERNAME password=PASSWORD -> DICTIONARY + COOKIES
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Authenticate a user to be able to use the system.

Login is implemented by *ttbd.login()* and if successful, it will
return a set of cookies which are later to be used to authenticate
with the system.

Cookies are returned by the call with a *Set-Cookie* header and they
need to be provided by any further call to the API with a *Cookie*
header to identify as a logged in user.

**Access control**

- Any user with a valid username and password can call to login

**Arguments**

- *username*: name of the user

- *password*: authentication token for *username*

Note in both of these fields, any special character must be properly
HTTP encoded

**Returns**

- on success, a 200 HTTP code and a JSON dictionary, or optionally
  with diagnostics fields.

- on error, a non 200 error code and a JSON dictionary with details,
  which will vary with the cause of the error.

**Example** success case::

  $ curl -k -X PUT -c cookies.txt https://SERVERNAME:5000/ttb-v2/login \
    -d username=USERNAME -d password=PASSWORD
  { "_message":"user USERNAME: authenticated with roles: admin user" }

error case::

  $ curl -k -X PUT -c cookies.txt https://SERVERNAME:5000/ttb-v2/login \
    -d username=baduser -d password=badpassword
  {"_message":"user baduser: not allowed"}

(in this example, curl saves the cookies to file cookies.txt which we
will use on ongoing example commands)

With TCF client, use *tcf login*.

GET /users + COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Get information about all the users known to the system (users that
are logged in).

**Access control**

- Any logged in user can call to get only their information

- Any *admin* user can call to get all user's

**Returns** dictionary of users information

- If the calling user has administrative privilege: a list of users
  known to the server (that have logged in) with information about
  each

- If the calling user has no administrative privilege: a list of one
  user with information about the calling user.

The return value is a JSON dictionary in the form::

  {
    "USERNAME": {
        "roles": {
            # list of roles, with a boolean that indicates the role is
            # gained (actively recognized) or dropped (ignored by the
            # system).
            "admin": true,
            "user": true,
            # ... other roles
        },
        "name": "UNIQUEID",	# internal ID
        "userid": "USERNAME" ,
      },
      ... # other users
  }

See :class:`ttbl.user_control.User` for a deeper description of
*roles*.

**Example**::

  $ curl -sk -b cookies.txt -X GET https://SERVERNAME:5000/ttb-v2/users/ \
    | python -m json.tool
  {
      "USERNAME": {
          "name": "_user_qvrpvsin2t",
          "roles": {
              "admin": true,
              "user": true
          },
          "userid": "USERNAME"
      },
      "local": {
          "name": "_user_n4a2sb2rhz",
          "roles": {
              "admin": true
          },
          "userid": "local"
      }
  }

With TCF client, use *tcf user-ls*.

GET /users/USERNAME + COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Get information about a specific user


**Access control**

- Any logged in user can call to get their information

- Any *admin* user can call to get other user's

**Arguments**

If *USERNAME* is *self*, then the server will return the information
for the currently logged in user according to the *COOKIES*. This is
useful for the clients to find which user their cookies loged them
as.

**Returns** JSON dictionary with user information

- if the calling user has administrative privilege: information about
  the user

- if the calling user has no administrative privilege and the userid
  is theirs, their user information, otherwise an error message

The return value is a JSON dictionary in the in the format listed for
the call *GET /users*

**Example**::

  $ curl -sk -b cookies.txt \
    -X GET https://SERVERNAME:5000/ttb-v2/users/USERNAME \
    | python -m json.tool
  {
      "USERNAME": {
          "name": "_user_qvrpvsin2t",
          "roles": {
              "user": true
          },
          "userid": "USERNAME"
      }
  }

  $ curl -sk -b cookies.txt \
    -X GET https://SERVERNAME:5000/ttb-v2/users/OTHERUSER \
    | python -m json.tool
  {
      "USERNAME": {
          "_message": "user 'USERNAME' needs admin role to query users other than themselves"
      }
  }

With TCF client, use *tcf user-ls USERNAME*.


DELETE /users[/USERNAME] COOKIES, PUT /logout COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Deauthenticate a user from the system, removing their *COOKIES* and
their validity, so if anyone attempts to use those *COOKIES* to access
the system they will be refused.

- User with administrative privilege can specify a *USERNAME* other
  than themselves to logout another user. Otherwise they will be
  rejected.

- Users without administrative privilege can only logout themselves.

HTTP 403 return values are returned if the calling user has no
priviledge to logout another user or the user does not exist.

**Access control**

- Any logged in user can call to log themselves out

- Any *admin* user can call logout other user's

**Returns** JSON dictionary

**Example** to logout the currently logged in user::

  $ curl -sk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/logout \
  {"_message":"session closed"}

or also::

  $ curl -sk -b cookies.txt \
    -X DELETE https://SERVERNAME:5000/ttb-v2/users/ \
  {"_message":"session closed"}

or also, which can be used to login another user (only users with
*admin* role)::

  $ curl -sk -b cookies.txt \
    -X DELETE https://SERVERNAME:5000/ttb-v2/users/USERNAME \
  {"_message":"session closed"}

With TCF client, use *tcf logout [USERNAME]*.


PUT /users/USERID/drop/ROLENAME + COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Have a user drop a role.

A user’s role can be dropped so the system does not consider it (eg: a
user with *admin* privilege drops it for normal use of the system).

The user can later gain back that role by calling *PUT
/users/USERID/gain/ROLENAME*.

For the user to call this API for a user other that themselves, they
have to have *admin* role, otherwise a 403 error code will be
returned.

If the *USERID* is *self*, it is meant to refer to the logged in user
the cookies refer to.

**Access control**

- Any logged in user can call

- Any *admin* user can call modify other user's roles

**Returns** a JSON dictionary with optionally a message or empty::

  {"_message":"user 'USERNAME' dropped role 'admin'"}

In case of error, a non-200 error code will be returned (invalid user,
or lack of permission::

  {"_message":"user 'USERNAME' has no access to role 'ROLENAME'"}

**Example**::

  $ curl -sk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/users/USERNAME/drop/admin
  {"_message":"user 'USERNAME' dropped role 'admin'"}


With the TCF client, use *tcf role-drop [-u USERNAME] ROLENAME*.

PUT /users/USERID/gain/ROLENAME + COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Have a user gain a role.

A user’s role can be gained so the system considers it (eg: an
administrator gaining the *admin role for administrative use of the
system). The user can drop it again by calling *PUT
/users/USERID/drop/ROLENAME*.

A user cannot gain a role that has not been listed by the
authentication mechanism. No user, including any user with *admin*
role, can give extra roles to users if the authorization system has
not listed them.

If the *USERID* is *self*, it is meant to refer to the logged in user
the cookies refer to.

If the calling user is not *USERNAME*, it needs *admin* role to change
other user’s roles, otherwise a 403 error code will be returned.

**Access control**

- Any logged in user can call

- Any *admin* user can call modify other user's roles

**Returns** a JSON dictionary with optionally a message or empty::

  {"result":"user 'USERNAME' dropped role 'admin'"}

**Example**::

  $ curl -sk -b cookies.txt \
    -X GET https://SERVERNAME:5000/ttb-v2/users/USERNAME/gain/admin
  {"result":"user 'USERNAME' gained role 'admin'"}

asking for an unexistant role::

  $ curl -isk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/users/self/gain/badrole
  HTTP/1.1 403 FORBIDDEN
  ...

  {"_message":"user 'USERNAME' has no access to role badrole"}

With the TCF client, use *tcf role-gain [-u USERNAME] ROLENAME*.


Inventory handling
------------------

The inventory service retains the properties of each target the system
knows about. It can be used to list known targets to the server and
the data for each.

The inventory data is a nested tree of key/values; values can be
strings, integers, floats, booleans or nested dictionaries.

.. _ttbd_api_http_inventory_key_name:

- Key names can contain only characters from the set [_0-9a-zA-Z]; a
  period cannot be used since it is used to specify nested
  dictionaries.

- There is no mandatory topology tree; each target only is mandated to
  have a key *id* describing its name.

  However, the service will publish information in the inventory
  regarding the target's capacity and state in the following subtrees:

  - *interfaces.INTERFACENAME.INSTANCENAME*: information of
    instrumentation capabilities

  - *instrumentation.INSTRUMENTID*: informatoin regarding specific instruments

  - *_alloc*: information regarding current allocation

  The convention for the topology tree is work in progress (FIXME).

Inventory data can be:

- queried

- modified/deleted (given the right permissions)

**Implicit vs Explicit key trees**

When querying the inventory service with defaul parameters, the
service can hide some nested key trees unless they are explicitly
asked for; this is meant to reduce the amount of data that has to be
transmitted when not necessary.

.. admonition:: Example

   There can be a tree of information related to each OS (eg:
   *linux.\**, or *windows.\** that describe how each OS sees
   different HW in a computer).

   When automation knows it is working with a certain OS, it can query
   for the inventory data specific to such OS and thus not need to
   transfer the others that won't be used.

The definition of which trees are explicit (always sent by default)
versus implicit will be defined in the topology specification and is
still WIP.


GET /targets + COOKIES [projections=FIELDLIST] -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Obtain a list of targets and their data available in this server, with
optional key filters.

**Access control**

- Any logged in user can call

**Arguments**

- *projections = FIELDLIST*: list of keys that have to be returned.

  Type: JSON encoded list of UTF-8 strings

  Disposition: (optional) defaults to any implicit available parameter.

  ::

    FIELDLIST = [ 'SPEC1', 'SPEC2', ... ]

  Each *SPEC* is a regular expression describing *keys* which can
  use the regular expression characters:

    - `*`: any set of characters
    - `?`: one of any character
    - `[SET]`: any character of set
    - `[!SET]`: none of characters in set

  .. admonition:: example

     `my[345]lo*` would match *my3lo2222* but not *my33lo2222*.

  If the keys specified in the filter do not exist, they will be
  ignored.


  .. admonition:: Rationale

     if there are a lot of parameters and they are unneeded for the
     needs of the calling actor, this will reduce load on the system
     and network—especially important in high latency connections.

  .. admonition:: Example

     In the case of projections, specifying
     `field1.subfield.subsubfield` would refer to a
     dictionary such as::

       {
          id: "TARGETID",
          field1: {
            "subfield": {
               "subsubfield": "lamb",
               "subsubfield1": "sheep",
               "subsubfield3": "ram",
               ...
            },
            "subfield1": 4,
            ...
          }
       }

     which imposes the restriction no field names can
     contain a period.

- *explicit*: FIXME: specify extra fields to be added that are
  normally explicit


**Returns** A dictionary of dictionaries, keyed by target name; each
subdictionary contains the data for that given target, including a
field called *id* with the target's name::

  {
     "TARGET1": { "id": "TARGET1", key1: ..., key2: ... key3: },
     "TARGET2": { "id": "TARGET2", key1: ..., key2: ... key3: },
     "TARGET3": { "id": "TARGET3", key1: ..., key2: ... key3: },
     ...
  }

Values for the keys are any JSON valid data as defined above (numbers,
strings, booleans or dictionaries).

If a key is not present, it is assumed that its value is *None/nil/null*.

If the filtering of the keys to return for a target yields an
empty list, then no data will be returned for said target.

.. admonition:: Rationale

   This, combined with considering non-existing fields to have
   value *None/null/none* allows to greatly reduce the amount of
   data transmitted.

   If for example an actor needs to know which targets are
   currently allocated, all it needs to do is to ask for the
   *owner* key::

     GET /PREFIX/targets projections=['owner']

   if no target is allocated, the server will return an empty
   dictionary::

     {
         'targets': {}
     }

   however, if any is allocated, only those will be returned::

     {
         'targets': {
            'TARGET22': {
                'owner': 'USER1'
            }
            'TARGET34': {
                'owner': 'USER4'
            }
     }

**Examples**

obtaining a list of fields for all targets::

  $ curl -sk -b cookies.txt \
    -X GET https://SERVERNAME:5000/ttb-v2/targets/ \
    -d projections='["id","type","interfaces.power"]'
    | python -m json.tool
  {
      ...,
      "qu-90f": {
          "id": "qu-90f",
          "interfaces": {
              "power": {
                    "main_power": {
                        "instrument": "sqsy"
                    },
                    "state": false,
                    "substate": "full",
                    "tuntap-nwf": {
                        "instrument": "e7du"
                    }
                }
            },
            "type": "qemu-uefi-x86_64"
      },
      ...
  }

Obtaining all fields for all targets::

  $ curl -sk -b cookies.txt \
    -X GET https://SERVERNAME:5000/ttb-v2/targets/ \
    | python -m json.tool
  {
      "local": {
          ....
      },
      ...,
      "qu-90g": {
          ...
          "id": "qu-90g",
          "instrumentation": {
              ...
              "sqsy": {
                  "functions": {
                      "console": "ttyS0:ssh0",
                      "debug": "x86_64",
                      "images": "kernel:bios:initrd",
                      "power": "main_power"
                  },
                  "name": "QEMU virtual machine",
                  "serial_number": "ihqlxf5gef"
              },
              ...
          },
          "interconnects": {
              "nwg": {
                  "ipv4_addr": "192.168.103.90",
                  "ipv4_prefix_len": 24,
                  "ipv6_addr": "fd:a8:67::5a",
                  "ipv6_prefix_len": 104,
                  "mac_addr": "02:a8:00:00:67:5a"
              }
          },
          "interfaces": {
              "capture": {
                  "screen": {
                      "instrument": "x54e",
                      "mimetype": "image/png",
                      "type": "snapshot"
                  },
                  ...
              },
              "console": {
                  ...,
                  "ttyS0": {
                      "crlf": "\r",
                      "generation": "1591078001",
                      "instrument": "sqsy",
                      "state": false
                  }
              },
              "debug": {
                  "x86_64": {
                      "instrument": "sqsy"
                  }
              },
              "images": {
                  "bios": {
                      "estimated_duration": 60,
                      "instrument": "sqsy"
                  },
                  ...
              },
              "power": {
                  "main_power": {
                      "instrument": "sqsy"
                  },
                  "state": false,
                  "substate": "full",
                  "tuntap-nwg": {
                      "instrument": "e7du"
                  }
              },
              "store": {},
              "tunnel": {}
          },
          ...
      },
      "qu-90h": {
          ....
      },
      "qu-91f": {
          ...
      },
      ...
      }
  }


With the TCF client, use *tcf ls [TARGETNAME]*.


GET /target/TARGETID + COOKIES [projections=FIELDLIST] -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Same as *GET /targets*, but for specific target *TARGETID*; the JSON
returned would be a dictionary specific to the target, not a
dictionary of dictionaries.

**Arguments** Same as for *GET /targets*

**Returns** a JSON dictionary::

  {
      key1: ...,
      key2: ...,
      key3:
  }

With the TCF client, use *tcf get TARGETNAME* and *tcf property-get
TARGETNAME PROPERTY-NAME*.


PATCH /targets/TARGETID + COOKIES data=JSON -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add data fields to the target’s inventory

**Access control**

- Administrators can call anytime

- Normal users need to have the target allocated, see
  :ref:`allocation <ttbd_api_http_allocation>`

- Certain keys cannot be overriden by normal users; FIXME: we need to
  expand how the admin can determine which fields can be overriden by
  a normal user

- Certain keys cannot be overriden by any user (including admins)
  FIXME/PENDING

- Certain keys shall not be visible no non *admin* users, since they
  may be containing configuration information that includes
  authentication tokens to access remote instrumentation that shall
  not be exposed. FIXME/PENDING

**Arguments**

- *TARGETID*: name of the target to modify; if the target does not
  exist and the user has the *admin* role, a new target might be
  created (if the implementation allows it) [FIXME: not yet
  implemented in *ttbd*].

- Data: JSON encoded fields to update, in the form of a dictionary

  Disposition: mandatory

  Type: Can be provided as a JSON dictionary in the request's body or
  as form arguments in the form *FIELD.SUBFIELD.SUBSUBFIELD=VALUE*

  Keys are always UTF-8 strings as described :ref:`in the inventory
  introduction <ttbd_api_http_inventory_key_name>`. Values can be
  *boolean*, *numbers* or UTF-8 strings.

  ::

    {
        'key1': VALUE1,
        'key2': {
            'key1.a': VALUE1A,
            'key1.b': VALUE1B,
        },
        ...
    }

  if a value is *null*, then the field is removed; setting a higher
  level dictionary (eg: *key2* in the above example) will wipe the
  whole dictionary and the values under it.

- keep_after_release: list of field names that will be kept
  unmodified when the target is released

  FIXME: TBD: this needs further definition along with the access control
  section


**Example**

To set a dictionary::

  "a": {
      "b": {
          "c": {
              "d": "4"
          }
      }
  },

it could be done with form arguments::

  $ curl -sk -b cookies.txt \
    -X PATCH https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME \
    -d a.b1.c.d=value -d a.b2=2 -d a.b3=3

which yields::

  $ curl -sk -b cookies.txt  -X GET https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME \
    -d projections='["a"]' \
    | python -m json.tool
  {
      "a": {
          "b1": {
              "c": {
                  "d": "value"
              }
          },
          "b2": 2,
          "b3": 3
      }
  }

to wipe everything under *a.b1.c*, set it to *null*::

  $ curl -sk -b cookies.txt \
    -X PATCH https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME -d a.b1.c=null

after that::

  $ curl -sk -b cookies.txt -X GET https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME \
    -d projections='["a"]' \
    | python -m json.tool
  {
      "a": {
          "b2": 2,
          "b3": 3
      }
  }

Instead of using form arguments, it can also be fed a JSON dictionary
on the request body::

  $ echo '{"a": { "b1": { "c": { "d": "value" } } }, "b2": 2, "b3": 3 }' \
    | curl -sk -b cookies.txt \
       -X PATCH https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME \
       -H "Content-Type: application/json" \
       --data-binary @/dev/stdin

When this returns::

  400 {"_message":"TARGETNAME: 400 Bad Request: The browser (or proxy) sent a request that this server could not understand."}

usually means the JSON is not properly formatted; a good trick is to
try to format it with *python -m json.tool* for a quick verification;
note the *x}* inserted in the middle of the JSON expression below
and how it generates an error::

  $ echo '{"a": { "b1": { "c": { "d": "value" } x} }, "b2": 2, "b3": 3 }' | python -m json.tool
  Expecting object: line 1 column 60 (char 59)


With the TCF client, use *tcf property-set TARGETNAME PROPERTY-NAME
VALUE* and *tcf property-get TARGETNAME PROPERTY-NAME*.



Allocation service
------------------

FIXME: this needs to be moved to ttbl.allocation for detailed
information and replaced here with a quick introduction

The allocation service is a basic priority based preemptable queue
that allows to request the allocation of one or more targets to a
user.

The allocation service is meant to service allocation requests by
automation systems that usually work in best effort mode.

For more interactive use (which usually includes reservation and
calendaring needs--allocating at a future time for a given length),
that task is delegated to a higher level API's reservation or
calendaring system that would operate this API when the time to
reserve a system comes.

The allocation service allows:

- a user to request an allocation of one or more targets:

  - with a given priority (controlled by policy that decides how high
    a priority a user can request)

  - with preemption enabled or disabled.

    With preemption enabled if the requesting user (*user1*) has
    higher priority than the user that currently owns the target
    (*user2*), the target will be taken away from *user2* and given to
    *user1* right away.

    With preemption disabled if the requesting user (*user1*) has
    higher priority than the user that currently owns the target
    (*user2*), *user2* will be put to wait for *user1* to release its
    use of the target.

- the system administrator to specify who can and cannot allocate
  which targets based on user's roles

- a user to add or remove guests from an allocation; guests can use
  the target/s in the allocation as the owner can, except they cannot
  release them. Guests can remove themselves from the allocation.

- a user with an *obo* (on behalf of) role to allocate targets on
  behalf of other users

  .. admonition:: rationale

     This enables a user to allocate on behalf of another, potentially
     using elevated privileges (such as priority and preemption) on
     behalf of the *obo-user*.

     Allows the implementation of reservation systems / schedulers
     that allocate machines on behalf of other users at given times
     with a given SLA.

.. _idleness:

Idleness and keepalives
^^^^^^^^^^^^^^^^^^^^^^^

There is no universal way to determine when a user is actively using a
target and when it has gone idle and it can be reclaimed to give it to
someone else.

Thus the API relies on:

- the user calling API methods that manipulate the target's state

- the user sending keepalives indicating their interest in an
  allocation and the target associated to it

In other words, the user has to constantly tell the system: I am using
this, do not release it. Otheriwse, it is given away after a
configurable number of missed keepalives/usages.

.. admonition:: Rationales

   - measuring power consumption is not a feasible way to test
     idleness:

     - measuring power consumption requires expensive instrumentation

     - users might be testing a machine's ability to wake up from deep
       sleep; thus power is not being consumed

     - determining what constitutes use might vary wildly based on the
       usage pattern; a malfunctioning software might be spinning
       cycles on a CPU and burning power but the user is not using it

   - measuring activity on a desktop / screen / serial console: this
     assumes the system is not producing random output, or a
     determination needs to be made if what is being produced is
     actual output that indicates valid activity

   - a user might launch a process that doesn't stop and then forget
     and go home for the weekend; said process produces activity that
     can be confused with user's actual usage of the target

.. admonition:: Example

   At the UI level, this might be represented with window in the
   user's desktop that sends the keepalives while (eg) their laptop is
   open. When the latpop is closed and the user goes home for the
   weekend, the keepalives stop and the allocation timesout, with the
   targets reclaimed.

   If the user needs to run an over-the-weekend script, they can
   allocate from a workstation that will stay on for the duration of
   the time needed.

   Another alternative is a calendaring/reservation system can take
   care to maintain allocations for users for longer periods of time.

.. _ttbd_api_http_allocation:

PUT /allocation COOKIES ARGUMENTS -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Request an allocation of targets

- This places a request to allocate targets for exclusive use of a given
  user and the guests they designate.

- The system will try to atomically allocate any of the specified target
  groups to the calling user or the user specified in the obo
  parameter.

- The system will use the given or default priority and preemption
  parameters to determine the place in the queue if any target is
  contended.

  FIXME: TBD:policy mechanism to specify max priority policy

- Allocations have no defined length of time; once allocated the user
  is free to use them as long as they need to. However, the system
  might impose allocation lengths based on policy

An allocation is presented by an *allocationid*, this is a unique
string that describes the ownership of the user over the targets and
it will be sent to the API as a handle to be able to use targets or
manipulate the allocation.

For most operations to manipulate the targets (eg: instrumentation),
the ALLOCATIONID is not necessary and as long as the calling user is
either the creator, the user or a guest of the allocation, the request
is granted.

However, if the ALLOCATIONDID specified to any of this operations, it
is validated and only permitted if the target is currently allocated
to that ALLOCATIONID.

.. admonition:: Rationale

   automation pipelines might run many (10, 100s, 100s...)  of scripts
   in parallel against the same pools of remote targets spread around
   multiple slave machines.

   Some of those scripts will be contending for targets using the
   allocator as an arbitrator. Specifying the ALLOCATIONID is an extra
   layer for each script to ensures it is using the right target and
   it has not overstepped its sequencing.

   However, if an interactive user wants to jump in to examine a
   target from a manual allocation or while a script is using it, it
   becomes very cumbersome to specify the ALLOCATIONID for each usage;
   thus, the system will allow the user to access the target as long
   as it is listed in the reservation as the owner, creator or guest.

.. _allocation_states:

An allocation might be in one of multiple states:

- *active*: all the targets in a group have been succesfully allocated
  and the user can start using them

- *busy*: the allocation cannot be service inmediately since targets
  are busy and thus it has been terminated

- *invalid*: invalid allocation

- *overtime*: the allocation has exceeded the maximum amount of time
  permitted and has been terminated

- *queued*: the allocation is pending allocation of all the targets
  in a group, since they might be in use by someone

- *rejected*: the user has no priviledge for the operation

- *removed*: the allocation has been terminated by the user

- *restart-needed*: an allocation has lost one or more targets due to
  preemption and the user has to acknowledge to the server the
  situation FIXME: TBD process so it can be moved to active (see
  preemption below)

- *timedout*: the allocation became idle as it was not used for more
  than the maximum amount of time the server determines via
  configuration.

  The server determines *use*:

  - as calling any API on a target that requires an allocation (while
    allocation is *active*)

  - calling *PUT /keepalive" on the allocation (see keepalives below)
    (while allocation is *active*, *pending* or *restart-needed*)


If the allocation request will return a dictionary with three fields,
an *allocationid* (on most conditions), a *state* and optionally a
*message* describing the situation:

- *state == active*: the allocation succeeded and all the targets
  are allocated to the *ALLOCATIONID* described by field *allocationid*.

  The user now calls needs to actively use the targets or send
  keepalives (see below) to inform the system on its interest on the
  allocation (otherwise it might be timedout and removed from the
  queue).

- *state == queued*: the allocation succeeded but the targets are not
  yet are allocated so they are pending on a queue; field *allocationid*
  describes the allocation.

  The user now calls needs to send keepalives (see below) to inform
  the system on its interest on the allocation (otherwise it might be
  timedout and removed from the queue) and to be notified when it
  changes to active so they can start using it.

- *state == busy*: the allocation failed to allocate inmediately and
  *queue* was set to *False*.

- *state == rejected*: the user does not have enough privilege;
  *message* will carry more information

  Reasons for this might be:

  - the user has no right to allocate some of the targets due to
    policy

  - the user has no rights to request certain priority or preemption

**Arguments:**

The arguments are passed as a JSON dictionary or as members of the
request form (FIXME)::

  {
     "obo": USERNAME,
     "priority": int(PRIO),
     "guests": [ "guest1", "guest2"... ]
     "preempt": bool(PREEMPT),
     "queue": bool(QUEUE),
     "reason": string,
     "groups": {
         "group1" : [ target1, target2, target3 ... ],
         "group2" : [ target3, target4, target1 ... ],
         "group3" : [ target1, target2, target5, target6 ... ],
     }
  }

- *groups:* one or more target group specifications

  Type: dictionary keyed by string of list of strings
  Disposition: mandatory

  - each target group has a name and one or more targets

    .. admonition: Examples

       allocate only one specific target::

         "groups": {
             "group1" : [ 'target1' ],
         }

       allocate only one of two targets on which through examining the
       inventory we have determined something can execute::

         "groups": {
             "group1" : [ 'target1' ],
             "group2" : [ 'target2' ],
         }

       allocate two specific targets that are interconnected for a
       client/server test::

         "groups": {
             "group1" : [ 'target1', 'target2' ],
         }

       same, but multiple options for the groups::

         "groups": {
             "group1" : [ 'target1', 'target2' ],
             "group2" : [ 'target1', 'target3' ],
             "group3" : [ 'target4', 'target2' ],
             "group4" : [ 'target3', 'target3' ],
         }

       allocate one group of one thousand specific targets for a
       cluster test::

         "groups": {
             "group1" : [ 'target1', ... 'target1000' ],
             "group2" : [ 'target1001', ... 'target2000' ],
             "group3" : [ 'target1500', ... 'target2500' ],
         }


  - the target groups might have common targets (their intersection
    doesn’t have to be empty)

    .. admonition:: example

       the group specification::

         "groups": {
             "group1" : [ target1, target2, target3 ],
             "group2" : [ target1, target2, target4 ],
             "group3" : [ target1, target2, target5 ],
         }

  - all target groups need to contain the same number of targets

- *priority:* a number which indicates the priority of the allocation

  Type: integer 0 (highest priority) - 1000 (lowest priority)

  Disposition: optional, defaults to 10000 (lowest)

  A user may specify what priority their allocation request has; this
  will decide in which position in the queue it is put if there is
  contention for the targets.

  The user can only allow a priority as high as the policy allows them
  too (FIXME: TBD)

- *queue:* place the allocation on the queue if the it cannot be
  satisfied inmediately

  Type: boolean True/False

  Disposition: optional, defaults to False

- *preempt:* indicate if the allocation request can preempt lower
  priority allocations

  Type: boolean

  Disposition: optional, defaults to *False*

  If *True* and the priority requested is lower than that of the
  current user, the allocator will release the current user's
  allocation and allocate to the calling user/obo (as described
  above).

  A user can only specify *preempt* if policy allows them to.

  Note however that preemption has to apply to the whole queue if any
  waiter has requested it.

  .. admonition:: example

     If target T is owned by user A with priority 600 and
     users B and C are waiting with priorities 200 and 300, to look
     like::

       T(A:600), B:200, C:300

     because preemption is enabled, A is allowed to finish and then B
     will take it, followed by C.

     However, if D places now an allocation request for T with priority
     250 (higher than A's, and C's, but lower still than B's), the queue
     will look as::

       T(A:600), B:200, D:250/preempt, C:300

     Now, because D is requesting preemption, it gets enabled for the
     whole queue, so A's allocation gets cancelled and the target is
     given to B::

       T(B:200), D:250/preempt, C:300

     Once B is done, D takes over but at that point the preemption is
     removed from the queue since no other waiters are requesting it::

       T(D:250), C:300


- *obo:* the allocation shall be made on behalf of the USERNAME using
  the rights of the user making the call

  Type: string representing a USERNAME
  Disposition: optional, defaults to the calling user

  The user making the call is identified by the *COOKIES* given upon
  login.

  .. admonition:: Rationale

     This is to be used to implement things such as
     calendars/schedulers that have more rights or preemption rights
     to implement an SLA without giving users more rights than they
     need to have.

  .. admonition:: Example

     Most automation systems work with on demand, best effort service;
     interactive users however need allocatation well in advance.

     User X has a list of automated jobs running using targets, user Y
     has a reservation made in an scheduling service sitting above the
     API for target A.

     User X has 500 priority, user Y has lower priority (eg:
     600). Neither has preemption rights. User Z (the scheduler's) has
     priority 100 and preemption rights.

     When Y's reservation time arrives, the scheduler, through the
     privileges given by its userid Z by TBD:POLICY makes a *priority
     100* *preemption* request for target A on behalf of
     user Y. Effectively this becomes a priority 100 request, which
     trumps any other allocations queued by user X on target A. As
     well, because of the preemption, the current allocation of user X
     of target A is terminated and the target is assigned right away,
     thus satisfying the calendaring system's SLA.

     User X is notified of the target being removed when they try to
     use it or keepalive the allocation. At that point how to react is
     the user's decission; for example they can choose to have the
     allocator find a replacement and restart their execution or drop
     the execution alltogether.

- *reason:* a string that describes what this allocation is used for

  Type: string UTF-8

  Disposition: optional, defaults to nothing

  This is usable to understand what different targets are being used
  for; users can publish here information about where their request
  comes and what it is executing, like for example::

    JOBID::TESTCASENAME USERNAME@HOSTNAME:PID

  the format of this is free form; the implementation may impose
  length limitations.


Examples
""""""""

Request an allocation of a target inmediately (without queing)::

  $ curl -isk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/allocation \
    -d queue=false -d groups='{"mygroup": [ "TARGETNAME" ]}'
  {
      "_message": "allocation is being actively used",
      "allocid": "iDhx4Z",
      "group_allocated": "TARGETNAME",
      "state": "active"
  }

Same, but two targets::

  $ curl -isk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/allocation \
    -d queue=false -d groups='{"mygroup": [ "TARGETNAME1", "TARGETNAME2" ]}'
  {
      "_message": "allocation is being actively used",
      "allocid": "i2Z3x4",
      "group_allocated": "TARGETNAME1,TARGETNAME2",
      "state": "active"
  }

If we try to re-allocate the same, they are busy so they can't be
allocated and no queuing was requested--thus a rejected status is
returned::

  $ curl -isk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/allocation \
    -d queue=false -d groups='{"mygroup": [ "TARGETNAME1", "TARGETNAME2" ]}'
  {
      "_message": "targets cannot be allocated right now and queuing not allowed",
      "state": "busy"
  }

since they are busy, retry queueing (set *queue=true*)::

  $ curl -isk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/allocation \
    -d queue=true -d groups='{"mygroup": [ "TARGETNAME1", "TARGETNAME2" ]}'
  {
      "_message": "allocation is queued",
      "allocid": "LUEzwa",
      "state": "queued"
  }

With the TCF client, use *tcf acquire ...* and *tcf alloc-ls*.

GET /allocation/ COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Get information about all allocations in the system

**Access control**

- All logged in users can query current allocations, but only
  allocations they created or for which they are listed as owner or
  guest will be reported

**Returns** dictionary with each entry keyed by an Allocation ID::

  {
      "ALLOCID1" : { },
      "ALLOCID2" : { },
      "ALLOCID3" : { },
      ...
  }

with the fields for each allocation being (some might not be present,
depending on the allocation and its state):

- *state*: (string) any of *invalid*, *queued*, *busy*, *removed*,
  *rejected*, *active*, *overtime*, *restart-needed*, *timedout*; see
  :ref:`more detail about states <allocation_states>`

- *user*: (string) name of the user that owns this allocation

- *creator*: (string) name of the user that created this allocation

- *reason*: (string) string describing what this allocation is being
  used for

- *guests*: (list of strings) user names that are guests in this
  allocation and thus can use it

- *group_allocated*: (list of strings) names of targets allocated for
  use (when *state* is *active*)

- *target_group*: (dictionary of lists of strings) the target groups
  originall requested by the creator

- *timestamp*: (string) timestamp in YYYYMMDDHHMMSS format describing
  the last time the allocation was considered active (by using an
  instrumentation call or issuing a /keepalive call).


**Example**

Make an allocation, ask for two targets out of any of two groups::

  $ curl -sk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/allocation \
    -d queue=true \
    -d groups='{"group1": [ "TARGETNAME1", "TARGETNAME2" ], "group1": [ "TARGETNAME3", "TARGETNAME2" ]}' \
    | python -m json.tool
  {
      "_message": "allocation is being actively used",
      "allocid": "had3_Q",
      "group_allocated": "TARGETNAME2,TARGETNAME3",
      "state": "active"
  }

Now querying::

  $ curl -sk -b cookies.txt \
    -X GET https://SERVERNAME:5000/ttb-v2/allocation/ \
    |  python -m json.tool
  {
      "had3_Q": {
          "creator": "USERNAME",
          "group_allocated": "TARGETNAME2,TARGETNAME3",
          "preempt": false,
          "priority": 50000,
          "state": "active",
          "target_group": {
              "group1": [
                  "TARGETNAME2",
                  "TARGETNAME3"
              ]
          },
          "targets_all": [
              "TARGETNAME2",
              "TARGETNAME3"
          ],
          "timestamp": "20200715171701",
          "user": "USERNAME"
      }
  }

With the TCF client, use *tcf alloc-ls*.


GET /allocation/ALLOCATIONID COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Get information about an specific allocation.

**Access control:**

- a user can only query their own allocations or those they are guests
  of or those they created

- a user with *admin* role can query other user's allocation

**Returns** dictionary with information about the allocation ID, as
described on *GET /allocation* (except in this case there is only one
allocation returned and the information is in the top level
dictionary).

An important use of this call is, when an allocation transitions from
*queued* to *active* *state*, so the user can tell which targets were
allocated (if they requested multiple groups) in the *group_allocated*
field.

With the TCF client, use *tcf alloc-ls | grep ALLOCATIONID*

DELETE /allocation/ALLOCATIONID COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Remove an existing allocation

**Access control**

- a user can remove only an allocation they created or are owners of

- a guest of an allocation, when trying to remove an allocation will
  just remove themselves as a guest

- a user with *admin* role can remove anyone's allocations

**Returns** DICTIONARY with the new state and a message:

- *state == removed*: the allocation was succesfully removed
- *state == invalid*: the allocation is invalid (it might have been
  already removed)
- *state == rejected*: the user lacks privilege for the operation


**Example**

Remove an invalid allocation fails::

  $ curl -sk -b cookies.txt \
    -X DELETE https://SERVERNAME:5000/ttb-v2/allocation/BADALLOC
  {"_message":"BADALLOC: invalid allocation"}

Remove an existing allocation::

  $ curl -sk -b cookies.txt -X DELETE https://SERVERNAME:5000/ttb-v2/allocation/ypf77J
  {"state":"removed","_message":"allocation has been removed by the user"}

With the TCF client, use *tcf alloc-rm ALLOCATIONID*.


TARGETNAME PROPERTY-NAME



PUT /keepalive COOKIES DICTIONARY -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This call serves two purposes:

- for the user to inform the system on their active use of a set of
  allocations

  See :ref:'Idleness and keepalives <idleness>` above for more
  information on how the API determines when targets are idle so they
  can be reclaimed for other users.

- for the server to notify the user of state changes in the allocation
  (for example, when an allocation was *queued* and then all the
  targets in a group were allocated, it transitions to *active*)

The user periodically calls this (eg: every 30s), providing the system
with a list of allocations it is currently monitoring and the state
the user believes they are in::

  {
      'ALLOCID1': 'active',
      'ALLOCID2': 'queued',
      'ALLOCID3': 'active',
      'ALLOCID4': 'active',
      ...
  }

the server respond with a list of allocation IDs that have a different
state from the servers's perspective, so the user can update its
understanding and take action::

  {
      'ALLOCID2': 'active',	# transitioned queued -> active
      'ALLOCID4': 'overtime',   # transitioned active -> overtime
  }

When the allocation transitions:

- from *queued* to *active*, the user then can use *GET
  /allocation/ALLOCID* to obtain the list of targets that are
  allocated and ready to use and then start using them.

- from *active* to *restart-needed* the user has to decide how to
  recover their allocation that got preempted. FIXME: TBD.

- to any error state: the user needs to drop any attempt to use the
  targets and transmit an error condition up to indicate what
  happened.

**Access control**

- any user can call this endpoint, however only allocations for which
  they are creators or owners can be listed for keepalive operation

- admins can list and keepalive any allocation ID

**Arguments** Dictionary keyed by allocationid and expected state

- in the request body: a JSON dictionary
- in form mode: variables named after the allocation ID and their
  expected state

all allocation IDs and states are strings.

**Returns** Dictionary keyed by allocationid and actual state of
those who are different to the expected state.

**Example**

Allocate a target::

  $ curl -sk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/allocation \
    -d queue=true -d groups='{"group1": [ "TARGETNAME" ] }' \
  | python -m json.tool
  {
      "_message": "allocation is being actively used",
      "allocid": "q8Ghpp",
      "group_allocated": "TARGETNAME",
      "state": "active"
  }

Send a keepalive assuming allocation ID *q8Ghpp* is *queued*::

  $ curl -sk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/keepalive \
    -d q8Ghpp=queued \
  | python -m json.tool
  {
      "q8Ghpp": {
          "group_allocated": "TARGETNAME",
          "state": "active"
      }
  }

Now we send a keepalive assuming the same allocation ID is *active*::

  $ curl -sk -b cookies.txt \
    -X PUT https://SERVERNAME:5000/ttb-v2/keepalive \
    -d q8Ghpp=active
  | python -m json.tool
  {}

because the state of the allocation in the server is the same than we
have, we get no response, meaning nothing to update.

PATCH /allocation/ALLOCATIONID/USERNAME COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add *USERNAME* to the list of guests that can use the targets in this
allocation.

Guests can use the targets in this reservation the same way as the
original user (except for removing the allocation which just removes
them from the guestlist).

**Access control**

- Only the user, creator of an allocation or an admin can add guest to
  an allocation

**Returns**

On success, empty JSON dictionary on success

On error, HTTP error code on invalid ALLOCATIONID, USERNAME or lack of
permissions and more information on the reponse body as a JSON
dictionary.

Note the system has no way to validate *USERNAME*, since the users
might have not logged in yet.

**Example**

For an existing allocation *ALLOCID*, add guest *NEWUSER*::

  $ curl -sk -b cookies.txt \
    -X PATCH https://SERVERNAME:5000/ttb-v2/allocation/ALLOCID/NEWUSER
  {}

if now we get the allocation ID, we will find the NEWUSER in the list
of guests::

  $ curl -sk -b cookies.txt \
    -X GET https://SERVERNAME:5000/ttb-v2/allocation/fPK8Ab \
    | python -m json.tool
  {
      "creator": "USERNAME",
      "group_allocated": "TARGETNAME",
      "guests": [
          "NEWUSER"
      ],
      "preempt": false,
      "priority": 500000,
      "state": "active",
      "target_group": {
          "group": [
              "TARGETNAME"
          ]
      },
      "targets_all": [
          "TARGETNAME"
      ],
      "timestamp": "20200715211417",
      "user": "USERNAME"
  }


DELETE /allocation/ALLOCATIONID/USERNAME COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Remove USERNAME from the list of users that can use allocation
ALLOCATIONID.

**Access control**

Only the user, creator or guests of an allocation can use this
call. Guests can only use it to remove themselves. The user, creators
or users with *admin* role can remove any guest.

**Returns**

On succes: empty JSON dictionary

On error: non-200 HTTP status code and JSON dictionary describing the
error condition

**Example**

Following the example from the *PUT /allocation/ALLOCATIONID/USERNAME*
section above::

  $ curl -sk -b cookies.txt \
    -X DELETE https://SERVERNAME:5000/ttb-v2/allocation/_uUtZh/NEWUSER
  {}

PUT /targets/TARGETID/release COOKIES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Release TARGETID from its current allocation without affecting the
rest of the targets in the allocation or the allocation itself.

**Access control**

Only users, creators and guests of the allocation which has allocated
TARGETID can execute this call.

**Returns**

On success: empty JSON dictionary on success

On error non-200 HTTP status code and JSON dictionary with more details

**Example**

::

   $ curl -sk -b cookies.txt \
     -X PUT https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/release
   {}

Service: Instrumentation
------------------------

The API exposes a flexible way to export abstractions over
instrumentation, as generic or specific to the actual instrument as it
is needed by the user.

This allows to abstract things like:

- power on/off (via using PDU brand A versus B)

- serial consoles over USB, BMC, network, etc

- pushing buttons or flipping jumpers (via relays or mechanical
  actuators)

- capture screenshosts (via KVMs, cameras pointing to monitors

The instrumentation interfaces allows to observe and manipulate the
target's state and:

- it is bound to a specific target that exposes said capability

- it is published under the HTTP namespace
  *http[s]://SERVERNAME:PORT/PREFIX[vVERSION]/targets/TARGETID/INTERFACENAME/OPERATIONAME*.

  For example, to manage power control

   - */targets/TARGETID/power/off*
   - */targets/TARGETID/power/on*
   - */targets/TARGETID/power/cycle*
   - */targets/TARGETID/power/get*

  to flash BIOS images:

   - */targets/TARGETID/images/flash*

  to read/write serial consoles:

   - */targets/TARGETID/console/read*
   - */targets/TARGETID/console/write*

- operations can be execused with PUT/DELETE/GET/POST/PATCH HTTP
  methods, depending on what makes more sense

- interfaces use the inventory system to publish information about
  what they support (mostly list of components and data about them)
  when this information is intrinsic to the system and does not change
  over time (eg: not status information).

  E.g.: the capture system can list the capture mechanisms the target
  supports the MIME type of the data produced by each.

This makes for a simple framework that can be easily expanded based on
what new instrumentation categories are found; ideally, we have high
level operations reflected in here that hide the instrumentation’s
details—however, instrumentations that need to expose more details
about themselves can export such an specific interface to suit any
need.

All the calls here will need to be passed the ALLOCATION-ID as well as
the COOKIESs as handle that indicates the user has the right to use
the target/s.


Instrumentation interface: IP tunneling
---------------------------------------

Creates tunnels to internal test networks so they can be accessed from
the client side; tunnels are all removed upon target release.

PUT /targets/TARGETID/tunnel/tunnel ARGUMENTS -> LOCALPORT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Set up an IP tunnel to an internal network from the API server

**Access control:** the user, creator or guests of an
allocation that has this target allocated.

**Arguments:** as a JSON dictionary or forms in the request

- *IP-ADDR*: IPv4 or IPv6 address of the target in the internal
  network. Note this normally has to match an IP address for
  *TARGETID*.

- *PORT*: (number) port in the target to which to tunnel to

- *PROTOCOL*: name of the protocol which to tunnel (*tcp*, *udp*,
  *sctp*)

**Returns:**

On succes: a JSON dictionary with a value *result* containing the local
TCP port on the server to which a client can connect to reach the
target's port.

On error: non-200 HTTP status code and JSON dictionary describing the
error condition.


DELETE /targets/TARGETID/tunnel/tunnel ARGUMENTS -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Remove an existing IP tunnel created with *PUT /targets/TARGETID/tunnel/tunnel*

**Access control:** the user, creator or guests of an
allocation that has this target allocated.

**Arguments:** as a JSON dictionary or forms in the request

- *IP-ADDR*: IPv4 or IPv6 address of the target in the internal
  network.

- *PORT*: (number) port in the target to which to tunnel to

- *PROTOCOL*: name of the protocol which to tunnel (*tcp*, *udp*,
  *sctp*)

**Returns:**

On succes: empty JSON dictionary

On error: non-200 HTTP status code and JSON dictionary describing the
error condition


Listing active tunnels
^^^^^^^^^^^^^^^^^^^^^^

Currently active tunnels are available from the inventory under the
*interfaces.tunnel* hierachy::

  $ curl -sk -b cookies.txt \
    -X GET https://SERVERNAME:5000/ttb-v2/targets/TARGETID \
    -d projections='["interfaces.tunnel"]'
    | python -m json.tool
  {
      "interfaces": {
          "tunnel": {
              "6455": {
                  "id": 235036,
                  "ip_addr": "192.168.100.85",
                  "port": 40,
                  "protocol": "tcp"
              },
              "9565": {
                  "id": 235047,
                  "ip_addr": "192.168.100.85",
                  "port": 80,
                  "protocol": "tcp"
              }
          }
      }
  }

this target has two redirections configured:

- tcp:SERVERNAME:6455 to tcP:192.168.100.85:40
- tcp:SERVERNAME:9565 to tcP:192.168.100.85:80

Instrumentation interface: local storage
----------------------------------------

Implement access to a local storage facility specific to each user
where they can store intermediate files for instrumentation tools and
targets to use; the system is free to clean them up/delete according
to their own policy (eg: LRU/size).

The server can also offer other areas of storage the user can list or
download files from, but they will not be able to upload or
delete. These are intended to be used for providing files most users
would need for any specific reason.

This storage tree is then made available to the clients via:

- the public server network interfaces networks
- the NUT facing network interfaces

so test scripts can pull data from the targets or other locations (as
the targets and clients might not be in direct network access).

POST /store/file file_path=FILENAME CONTENT -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Upload a file to user’s storage

Note there is no way to create subdirectories in the the user's
storge; it is meant to be a flat file system.

**Access control:** only the logged in user can call this to access
their own storage area.

**Arguments:** arguments are given a form post arguments

- *file_path*: name to give the file in the storage area; can contain
  directory separators (Unix's ``/``); cannot contain ``..``.

- *data*: file's content in the HTTP request body.

**Returns:**

- On success, 200 HTTP code and a JSON dictionary with optional
  diagnostics

- On error, non-200 HTTP code and a JSON dictionary with diagnostics

**Example**

::

  $ curl -sk -b cookies.txt -X POST \
    https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/store/file \
    --form-string file_path=REMOTEFILENAME  -F file=@LOCALFILENAME

With the TCF client, use the *tcf store-upload TARGETNAME
REMOTEFILENAME LOCALFILENAME* command.


GET /store/list [ARGUMENTS] -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

List files in user’s storage or global storage and their digital
signature.

Note this only lists a single subdirectory without recursing into
other subdirectories--this is intended by design to avoid recursive
operation that might be costly to the server. The user can use the
*path* argument to specify a subdirectory of an storage area.

**Access control:** only the logged in user can call this to access
their own storage area and of common areas.

**Arguments**

- *filenames*: (optional) list of filenames to list; defaults to all
  if not specified. This is useful when the caller wants to check the
  existence of certain files and their signatures and is not
  interested in the rest.

- *path*: (optional) path to the storage area; if not specified,
  it will list in the user's storage area. Otherwise, it refers to the
  given storage area. The server's administrator will, upon
  configuration, specify which paths are allowed.

  The path */* refers to the top level storage area and can be used to
  list the top level storage areas the administrator has configured.

- *digest*: (optional, default *sha256*) digest to use to calculate
  digital signatures. Valid are:

  - *md5* (default)
  - *sha256*
  - *sha512*
  - *zero* (returns *0* for all entries)
  
**Returns**

- On success, 200 HTTP code and a JSON dictionary keyed by filename
  containing the digest of each file.

  If there are subdirectories in the area, they will be listed with a
  digest of "subdirectory".
  
  .. admonition:: deprecation notice

     Older servers might return the data wrapped inside a field called
     *result*; this is now deprecated and being replaced towards
     returning the data at the top level.

- On error, non-200 HTTP code and a JSON dictionary with diagnostics

.. note:: implementations are allowed to rate limit this call, since
          MD5 computation can be costly to avoid denial of service
          attacks.

          Eg: allowing a user to call this only once every five minutes
          and delaying the execution of the next if it came before
          five minutes.

**Example**

::

   $ curl -sk -b cookies.txt -X GET \
     https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/store/list \
     | python -m json.tool
   {
       "_diagnostics": "",
       ...
       "bios.bin.xz": "50c3c3ed1e54deddfe831198883af91ad6e9112f8f1487214cdd789125f737f0",
       "bmc.bin.xz": "5d12bddb65567e9cb74b6a0d72ed1ecac2bbb629f167d10e496d535461f8fd54",
       ...
   }

With the TCF client, use the *tcf store-ls TARGETNAME* command.


GET /store/file ARGUMENTS -> CONTENT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Download a file from user’s storage or from allowed global storage.

**Access control:** only the logged in user can call this to access
their own storage area.

**Arguments:**

- *file_path*: name of the file to read from the storage area

**Returns:**

- On success, 200 HTTP code and the file contents on the response
  body.

- On error, non-200 HTTP code and a JSON dictionary with diagnostics

**Example**

::

   $ curl -sk -b cookies.txt -X GET \
     https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/store/file \
     -d file_path="bios.bin.xz" > bios.bin.xz
   $ file bios.bin.xz
   bios.bin.xz: XZ compressed data

With the TCF client, use the *tcf store-dnload TARGETNAME
REMOTEFILENAME LOCALFILENAME* command.

DELETE /store/file file_path=FILENAME -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Delete a file from user’s  storage

**Access control:** only the logged in user can call this to access
their own storage area.

**Arguments:**

- *FILENAME*: name to give the file in the storage area

**Returns:**

- On success, 200 HTTP code and a JSON dictionary with optional
  diagnostics

- On error, non-200 HTTP code and a JSON dictionary with diagnostics

**Example**

::

   $ curl -sk -b cookies.txt -X DELETE \
     https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/store/file \
     -d file_path="bios.bin.xz"

With the TCF client, use the *tcf store-rm TARGETNAME REMOTEFILENAME*
command.


Instrumentation interface: power control
----------------------------------------

This interface provides means to power on/off targets or the invidual
components that compose the power rail of a target.

When powering on/off the whole target, the order in which the
different components of the power rail were specified is followed
(reverse when off); this allows enforce strict ordering needed by
some platforms.

Power rail components might not necessarily be something that turns on
or off, but they can also be:

- delays: delay for some time, delay until something happens (eg: a
  USB device is detected in the server, a file appears, a certain
  program returns a certain value when executed)

- service management: a program is started when powered on, killed
  when powered off (for example, a bridge to a JTAG)

- setup of network tunnels, reconfiguration of hardware for propert
  power on conditions, ensuring buttons are released (eg: reset)...

Allows to specify certain components as *explicit* so that they be
only be powered off or on if they are specifically named, but never by
default (when then whole target is powered on/off). Extends to
*explicit_off* (only power off if explicitly named when turning off)
and *explicit_on* (only power off if explicitly named when turning
on).

.. admonition:: Rationale

   Certain configurations have multiple switches to power on a target;
   however, it is not wished in general to power everything off.

   e.g.: a server power AC is controlled by a PDU and then via the
   BMC; for turning it on, the default (implicit) sequence is to power
   on the PDU, then on the BMC. To power off, the default (implicit)
   sequence is to just power off via the BMC and leave AC on. This
   could be needed, for example, to avoid hardware damage.

   If the user wants to implement a sequence where even the AC power
   is removed, they explicitly indicate to power AC off after the
   implicit sequence.

Each component might be queried for individual power status:

 - *true*: on

 - *false*:off

 - *none*: components that are not really implementing a power control
   but things like a delay

Note the same implementation of this interface is used to expose
button and jumper control, but under the endpoint
*/PREFIX/targets/TARGETID/buttons* -- as buttons / jumpers are
generally controlled with binary states actuated with a relay.

Power Rail Components naming conventions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In general, if the target has a single component of one category, it
is called as it is (eg: *AC*), but if more are going to be present,
then all are indexes with an integer (eg: *AC1*, *AC2*).

The following conventions are followed:

- *AC*, *AC1* ... *AC4* ...: anything that controls power from a wall
  outlet (eg: a smart PDU). 

- *DC*, *DC1* ... *DC4* ...: anything that controls power using things
  like a button, or via *BMC*.


GET /targets/TARGETID/power/list
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Return a list of the components in the target’s power rail and their
state

**Access control:** the user, creator or guests of an
allocation that has this target allocated.

**Returns:** dictionary with information::

  {
      "state": false,		# true, false
      "substate": "full",	# full, normal, partial
      "components": {           # power state for each component
          COMPONENT1: STATE1,	# true, false, none
          COMPONENT2: STATE2,
          ...
          COMPONENTN: STATEN,
      }
  }

The global target power state is described by the *state* field:

- *on* the target is powered on

  *substate* can be:

  - *normal*: all the non-explicit power components and those marked
    *explicit/off* report *on* or *n/a*.  The components marked
    *explicit* and *explicit/on* report *off* or *n/a*.

    This is the state in which a target can be used as per the usual
    usage pattern.

  - *partial*: same as *normal*, but one or more of those marked
    *explicit* or *explicity/on* report *on* or *n/a*.

    Same *normal*, however extra components being powered on for
    non-usual usage patterns might or not affect the operation of the
    target.

  - *full*: all the power components (including those marked
    *explicit*, *expliciy/off* and *explicty/on*) are *on* or *n/a*.

    Same *normal*, however all the extra components being powered on
    for non-usual usage patterns might or not affect the operation of
    the target.

- *off*: the target is powered off

  - *normal*: all the non-explicit power components and those marked
    *explicit/on* report *off* or *n/a*. The components marked
    *explicit* and *explicit/off* report *on* or *n/a*.

    This is the state in which a target can be considered off as per
    the usual usage pattern.

    When the target is idle, the system will power it off to this state.

  - *partial*: some of the non-explicit power components or those
    marked *explicit/on* report *off* or *n/a*.

    This is an inconsistent power state in which the target is off but
    not all the components that should be off are off.

    To use normally, it is adviced to do a power cycle, which will
    power everything off and power on to the right state.

  - *full*: all the power components (including those marked
    *explicit*, *explicit/on* and *explicty/off*) are *off* or *n/a*.

    This is a full power off where the system consumes the least power
    (ideally zero). When the target has been in power off *normal* due to
    idleness, after a configured time it will be brought to *full*
    power off.

For each component, its state is described in the field *state* along
with its explicitness.

As a convenience, the system publishes in the target's inventory:

- *interfaces.power.state*: last power state recorded on the last
  *list()* call.
- *interfaces.power.substate*: last power substate recorded on the
  last *list()* call.

this can be used for caching purposes, since quering the power state
can be a time consuming operation. However, it must be noted that
external actors might take actions that would affect the true value of
this state (eg: a PDU self-powering off an outlet due to overcurrent),
so it shall not be used for hard evaluation.

**Example**

::

  $ curl -sk -b cookies.txt --max-time 800 -X GET \
    https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/power/list \
    | python -m json.tool
  {
      "_diagnostics": "..."
      "components": {
          "AC1": {
              "state": false
          },
          "AC2": {
              "state": false
          },
          "jtag": {
              "explicit": "off",
              "state": false
          },
          ...
          "serial0": {
              "state": false
          }
      },
      "state": false,
      "substate": "full"
  }

With the TCF client, use the *tcf power-ls [-v] TARGETNAME* command.

PUT /targets/TARGETID/power/on [ARGUMENTS] -> DICT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Turn on the target (the whole power rail) or specific components of
the power rail.

If no components are specified, turns on in sequence the elements of
the power rail (list subject to the *explicit* argument).

If one or more components are specified, turn on those components.

This operation can be lengthy if the power rail is very long and the
components take a long time to operate--this is implementation
specific and there is no way to predict how long is going to
take. However, as an implementation convention, no power rail shall
take longer than sixty seconds to power on.

**Access control:** the user, creator or guests of an
allocation that has this target allocated.

**Arguments**

- *component*: (optional; defaults to all) name of a component to turn
  on

- *components*: (optional; defaults to all) JSON encoded list of
  components to turn on

- *explicit*: boolean; when no components are specified, if *True*
  this indicates also the components marked *explicit* and
  *explicit/on* shall be powered on.

**Returns:**

- On success, 200 HTTP code and a JSON dictionary with optional
  diagnostics

- On error, non-200 HTTP code and a JSON dictionary with diagnostics

**Linkage to other subsystems**

Before powering on a the whole power rail, the targets' default console
is reset; as well, any hooks defined in the server to be executed
before power on (and after power on, on success) are executed.

**Example**

::

   $ curl -sk -b cookies.txt -X PUT \
     https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/power/on
   {
       "_diagnostics": ...
   }

   $ curl -sk -b cookies.txt -X PUT \
     https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/power/on \
     -d component="AC1"
   {
       "_diagnostics": ...
   }

With the TCF client, use the *tcf power-on [-v] TARGETNAME* command.

PUT /targets/TARGETID/power/off [ARGUMENTS] -> DICT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Turn off the target (the whole power rail) or specific components of
the power rail.

If no components are specified, turns off in sequence the elements of
the power rail (list subject to the *explicit* argument).

If one or more components are specified, turn off those components.

This operation can be lengthy if the power rail is very long and the
components take a long time to operate--this is implementation
specific and there is no way to predict how long is going to
take. However, as an implementation convention, no power rail shall
take longer than sixty seconds to power off.

**Access control:** the user, creator or guests of an
allocation that has this target allocated.

**Arguments**

- *component*: (optional; defaults to all) name of a component to turn
  off

- *components*: (optional; defaults to all) JSON encoded list of
  components to turn off

- *explicit*: boolean; when no components are specified, if *True*
  this indicates also the components marked *explicit* and
  *explicit/off* shall be powered off.

**Returns:**

- On success, 200 HTTP code and a JSON dictionary with optional
  diagnostics

- On error, non-200 HTTP code and a JSON dictionary with diagnostics


**Linkage to other subsystems**

Before powering off the whole power rail, the targets' pre execution
hooks are run, as well as post-off hooks. This is specially relevant
in that the consoles are all disabled.

**Example**

::

   $ curl -sk -b cookies.txt -X PUT \
     https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/power/off
   {
       "_diagnostics": ...
   }

With the TCF client, use the *tcf power-off TARGETNAME -c COMPONENT]* command.

PUT /targets/TARGETID/power/cycle [ARGUMENT] -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Power cycle (turn off, then on) the target (the whole power rail) or a
specific component of the power rail.

.. note: A power cycle can be left to the user (power off, then power
   on)--however, since it is a very common case and the implementation
   has data readily available on the state, it is more efficient to
   implement it here.


**Access control:** the user, creator or guests of an
allocation that has this target allocated.

**Arguments**

- *component*: (optional; defaults to all) name of a component to turn
  off

- *components*: (optional; defaults to all) JSON encoded list of
  components to turn off

- *explicit*: boolean; when no components are specified, if *True*
  this indicates also the components marked *explicit* and
  *explicit/off* shall be powered off. Likewise with the *explicit/on*
  components on the power on path.

- *wait* (optional; > 0 integer): number of seconds to wait between
  power off and power on; cannot be less than what is specified in
  target parameter power_cycle_wait.  (optional), defaults to target’s
  parameter power_cycle_wait (if specified), otherwise two seconds.

**Returns:**

- On success, 200 HTTP code and a JSON dictionary with optional
  diagnostics

- On error, non-200 HTTP code and a JSON dictionary with diagnostics

With the TCF client, use the *tcf power-cycle [-v] TARGETNAME* command.


PUT /targets/TARGETID/power/sequence -> DICT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Execute a sequence of power on/off/cycle events for different
components.

**Access control:** the user, creator or guests of an
allocation that has this target allocated.

**Arguments**

- *sequence*: JSON list of pairs *[ OPERATION, ARGUMENT ]* describing
  the events to execute; *OPERATION* can be:

  - *on*, *off* or *cycle*: in this case *ARGUMENT* becomes:

    - *all*: perform the operation on all the components except
      explicit ones

    - *full*: perform the operation on all the components
      including the explicit ones

    - *COMPONENT NAME*: perform the operation only on the given
      component

  - *wait*: *ARGUMENT* is a positive number describing how many
    seconds to wait

**Returns:**

- On success, 200 HTTP code and a JSON dictionary with optional
  diagnostics

- On error, non-200 HTTP code and a JSON dictionary with diagnostics

**Linkage to other subsystems**

When powering on/off the whole target, the same events described for
the ON or OFF operations will happen.

**Example**

::

   $ curl -sk -b cookies.txt -X PUT \
       https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/power/sequence \
       -d sequence='[ [ "off", "AC1" ], [ "wait", 2 ], [ "on", "AC1"] ]'
   {
       "_diagnostics": ...
   }

With the TCF client, use the *tcf power-sequence [-v] TARGETNAME
OP:ARG [OP:ARG [OP:ARG [...]]]* command.

Instrumentation interface: image flashing
-----------------------------------------

This interface provides means to program/write/burn/flash
data/binaries/images to one or more permanent storages in the
platform.

For example, firmwares, BIOSes which are flashed via a JTAG, an EEPROM
interface, fastboot or similar interfaces.

A target can any number of flashing destinations (eg: BIOS1,
BIOS.recovery, microcontroller3) and the user may request flashing of
them all with a single call. How the target is configured, and based
on its capabilities and/or limitations will dictate if they all can be
flashed/programmed/burnt in parallel or serially.

The process for flashing anything is to first upload the data file to
the server using the storage interface described above, and then
commanding this interface to burn said file into a given location.

Listing possible flashing targets
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use the inventory to obtain the list of possible flashing targets::

  GET /targets/TARGETID projection=["interfaces.images"]

**Access control:** any logged in user can call

**Returns:** dictionary of information containing an entry per
destination and:

- the estimated amount of seconds the flash operation will
  last

- the unique identity (UPID) of the instrument that implements
  the flashing operation (more information about the instrument can be
  found in the inventory in the field *instrumentation.<UPID>*)

- if something has been already flashed, the SHA512 signature of the
  last file flashed

::

  {
      "interfaces": {
          "images": {
              "bios": {
                  "estimated_duration": 930,
                  "instrument": "u62a",
                  "last_sha512": "301f5e61fec5a260b2fabbc38d89d637d3aebd77e0b61398427658eece82ee028dfb5730a14ddad3c51e37afacc8c05c5a238d2c8e4cedd009a0c317124cd748"
              },
              "bmc": {
                  "estimated_duration": 930,
                  "instrument": "z4hn",
                  "last_sha512": "ab4598eb3d64817340ea869a6d7581ee1cebb2c9d5346d72dc603fead7659911be58dd5fa674739c0ea967ca03e2cd2eee5dd3deabe9a7e9b00b9ac5047d10bd"
              },
              "microcontroller1": {
                  "estimated_duration": 930,
                  "instrument": "rgde"
              },
              "microcontroller2": {
                  "estimated_duration": 930,
                  "instrument": "rgde"
              }
          }
      }
  }

In this example, the target offers four destinations (one for the BIOS,
another one for a BMC and two microcontrollers).

Wit the TCF client, use *tcf images-ls TARGETNAME*


PUT /targets/TARGETID/images/flash IMAGES -> DICTIONARY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Flash images onto their targets.

This is a synchronous operation; user must query the inventory (see
above) to find how long each destination takes to flash and keep the
connection open for as long as indicated waiting for the system to
provide a reply.

While the flashing operation is going on, the system considers the
target is being used, so it won't be idled.

After flashing, the inventory is updated to reflect the SHA 512
signature of the image flashed on each destination; this can be used
by the client to, before flashing, check if the signature will be the
same and thus avoid re-flashing (*soft flash*).

Images must have been uploaded first to the storage area using the
*store* interface. The client shall first list files in the storage
area to verify a file with the same signature is present and skip the
upload if already available in the server (*soft upload*).

The server will recognize image files compressed with the tools *gz*,
*xz* and *bz2* (because their name ends in *.gz*, *.bz* or *.xz*) and
decompress them before flashing. The SHA 512 recorded will be that of
the decompressed files. It is recommended to compress large files,
since upload to the server will be significantly faster.

**Access control:** the user, creator or guests of an
allocation that has this target allocated.

**Returns**

- on success, a 200 HTTP code and a JSON dictionary, or optionally
  with diagnostics fields.

- on error, a non 200 error code and a JSON dictionary with details,
  which will vary.

**Example**

Compress and upload files *bios.bin.xz* and *bmc.bin.xz*::

  $ xz bios.bin bmc.bin
  $ curl -sk -b cookies.txt -X POST \
    https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/store/file \
    --form-string file_path=bios.bin.xz  -F file=@bios.bin.xz
  $ curl -sk -b cookies.txt -X POST \
    https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/store/file \
    --form-string file_path=bmc.bin.xz  -F file=@bmc.bin.xz

flash files; from the inventory report we have seen destinations
*bios* and *bmc* report a duration of 400 each, so we set the timeout
to 800::

  $ curl -sk -b cookies.txt --max-time 800 -X PUT \
    https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/images/flash \
    -d images='{"bios":"bios.bin.xz", "bmc":"bmc.bin.xz"}' \
    | python -m json.tool
  {
      "_diagnostics": "..."
  }

With the TCF client, use *tcf images-flash TARGETNAME bios:bios.image.xz*.



GET /targets/TARGETID/images/list
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Deprecated** use the inventory method described above

Return a list of the possible flashing destinations the target
offers.

**Access control:** any logged in user can call

**Returns:** dictionary of information::

  {
      "aliases": {},
      "result": [
          "microcontroller1",
          "microcontroller2",
          "bmc",
          "bios"
      ]
  }

In this example, the target offer four destinations (one for the BIOS,
another one for a BMC and two microcontrollers). No aliases are
specified.


Old documentation, pending rewrite/update
-----------------------------------------

Console
^^^^^^^

- ``/ttb/v1/targets/TARGETNAME/console/setup`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/console/list`` *GET*
- ``/ttb/v1/targets/TARGETNAME/console/enable`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/console/disable`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/console/state`` *GET*
- ``/ttb/v1/targets/TARGETNAME/console/size`` *GET*
- ``/ttb/v1/targets/TARGETNAME/console/read`` *GET*
- ``/ttb/v1/targets/TARGETNAME/console/write`` *PUT*

Capture
^^^^^^^

- ``/ttb/v1/targets/TARGETNAME/capture/start`` *POST*
- ``/ttb/v1/targets/TARGETNAME/capture/stop_and_get`` *POST*
- ``/ttb/v1/targets/TARGETNAME/capture/list`` *GET*

Buttons
^^^^^^^

- ``/ttb/v1/targets/TARGETNAME/buttons/sequence`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/buttons/list`` *GET*

Fastboot
^^^^^^^^

- ``/ttb/v1/targets/TARGETNAME/fastboot/run`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/fastboot/list`` *GET*



IOC_flash_server_app
^^^^^^^^^^^^^^^^^^^^

- ``/ttb/v1/targets/TARGETNAME/ioc_flash_server_app/run`` *GET*

Things
^^^^^^

- ``/ttb/v1/targets/TARGETNAME/things/list`` *GET*
- ``/ttb/v1/targets/TARGETNAME/things/get`` *GET*
- ``/ttb/v1/targets/TARGETNAME/things/plug`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/things/unplug`` *PUT*

Examples
--------

Example: listing targets over HTTP
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

What the command line tool would be::

  $ tcf list -vv

anything that has an @ sign is being used actively by TCF another -v
will get you the same JSON that either of::

  $ wget --no-check-certificate https://SERVERNAME:5000/ttb-v1/targets
  $ curl -k https://SERVERNAME:5000/ttb-v1/targets/

will return; in JSON, you can tell a target is idle if *owner* is
None or missing; if it has a value, it is the user ID of whoever has
it::

  {
      ...
      'id': 'r14s40',
      ....
      'owner': None,
      ...
  }

now::

  $ tcf login USERNAME
  Password: <....>
  $ tcf acquire r14s40
  $ tcf list -vvv r14s40
  { ...
    'id': u'r14s40',
    ...
    'owner': u'USERNAME',
    ...
  }

In Python::

  import requests
  r = requests.get("https://SERVERNAME:5000/ttb-v1/targets", verify = False)
  r.json()


Example: Reading the console(s) from HTTP
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can see which consoles are available with either or::

  $ tcf acquire r14s40
  $ tcf console-list r14s40
  $ tcf list -vvv r14s40 | grep consoles

You can continuously read with::

  $ tcf console-read --follow r14s40

in Python, HTTP I do like:

>>> import cPickle, requests
>>> cookie = cPickle.load(open("/home/user/.tcf/cookies-httpsSERVERNAME5000.pickle"))
>>> r = requests.get("https://SERVERNAME:5000/ttb-v1/targets/r14s40/console/read",
...     verify = False, data = dict(offset = 20, component = "sol0_ssh"), cookies = cookie)
>>> r.text

So you put this in a loop, which is what *tcf console-read --follow*
does in (``tcf.git/tcfl/target_ext_console.py:_cmdline_console_read``)
