.. _ttbd_api_http:

The HTTP API exported by *ttbd* is a very basic REST model which is
goint to at some point be coverted to *odata* or JSON-RPC.

FIXME: this document is work in progress

It is recommended to access the server using the Python API as defined
in :class:`tcfl.tc.target_c`.

>>> import tcfl
>>> target = tcfl.target_c.create_from_cmdline_args(None, "TARGETNAME")
>>> target.power.off()


If raw HTTP access is needed, it is a good way to double check if
things are being done right to run the *tcf* client with *--debug*,
since it will print the HTTP requests done, to cross check::


  $ tcf --debug login USERNAME
  ...
  I ttb_client.rest_login():679: https://localhost:5004: checking for a valid session
  Login to https://localhost:5004 as USERNAME
  Password: 
  D ttb_client.send_request():275: send_request: PUT https://localhost:5004/ttb-v1/login
  D connectionpool._new_conn():813: Starting new HTTPS connection (1): localhost:5004
  send: 'PUT /ttb-v1/login HTTP/1.1\r\n
  Host: localhost:5004\r\n
  Connection: keep-alive\r\n
  Accept-Encoding: gzip, deflate\r\n
  Accept: */*\r\n
  User-Agent: python-requests/2.20.0\r\n
  Cookie: remember_token=USERNAME|e72e83d4ae70d6ef484da8cec6fa1c4d93833327dabda9566bb12091038cfbe982f7ec3b1d269ae6316969489e546bf797ce564c8daef89f13451505ae5b5a37; session=.eJxNj0-LgzAUxL_K8s5S2rRehL0sacVDXlAs8nKRbutu_inFKhJLv_tmb70NMwzzmye0P2P30JBN49wl0JobZE_4-IYMJD-maK8rNuUO-ZfHWkRNQXJvlC13ZB1Dro2sBRNWOcULJnmR4uqYaJSWuQiqLw9oK68sMVmfvGwo9mgvetqiPe5VUy6KUxB5pZHREvcWsVZG9UVKVsdN70TkEA0dMD9vY6ZlTYvkkcueF-xPTtW_n_BKwNy6YTJT2FzmSbdTuHeQDbP3b8n_OzDDxQVIYH50Y_vmvP4Ax1dagQ.ENlzCw.jIg8VhRQADhEZiyNtCh2A6HRFsk\r\n
  Content-Length: 60\r\n
  Content-Type: application/x-www-form-urlencoded\r\n
  \r\n
  password=PASSWORD&email=USERNAME'
  reply: 'HTTP/1.1 200 OK\r\n'
  header: Vary: Cookie
  header: Set-Cookie: remember_token="USERNAME|1efa96aafcf99f21c105d8323d161d205fa8bd1e7aa2ed3fcab38daba7f0c748280941d478ed4e3fc9b4e5f6606d35abad1e23666ee56b55be6adb560f8748e9"; Expires=Fri, 20-Dec-2019 21:03:40 GMT; Path=/
  header: Set-Cookie: session=.eJyNjz1rwzAYhP9KeefUJEq8GAqlKDEeJGHjYKTFOIkafdkJjoyRQ_571a1jt4Pnjrt7Qvs9yoeCzI-TXEGrL5A94e0EGTC8T6k5L7QpNxR_OVqTqHlg2Glhyg03FlGsNKsJIkZYgQvEcJHSxSLSCMVyEkRf7qipnDAcsfrgWMNjjm9Jz9fU7LeiKWeBeSB5pSjic-ybyVJp0RcpNyp2OkviDtLwHc2P68gUq_nMcNxljjPtD1bU1w94rUBf5OC1D0k3edX6cJeQDZNzf8jvO9BDZ0Nyl6Nc3q-3YemcXD714KVLzrceVjA95Nj-x_r6AYOEbek.ENmCrA.JjU3Fqwtw2jvYjbJCJCKYMyR1Gs; HttpOnly; Path=/
  header: Content-Length: 92
  header: Content-Type: application/json
  header: Server: TornadoServer/5.0.2
  ...

Arguments are encoded as HTTP form fields; for non escalar arguments,
the values are JSON encoded.

Authentication is done via cookies, which also include the username,
stored in ``~/.tcf/cookies-SERVERNAME.pickle``, which can be loaded in
python with:

>>> import cPickle, requests
>>> cookie = cPickle.load(open("/home/USER/.tcf/cookies-httpsservername000.pickle"))

and then this can be used to make a request to, for example, the
console interface:

>>> r = requests.get("https://servername:5000/ttb-v1/targets/r14s40/console/read",
>>>                  verify = False, data = dict(offset = 20, component = "sol0_ssh"),
>>>                  cookies = cookie)
>>> r.text

Basic target interface
----------------------

Common arguments:

- ``ticket``: ticket under which the current owner is holding the
  target; this is string unique identifier, same as used to aquire::

    $ tcf login username
    $ tcf -t BLAHBLAH acquire TARGETNAME

  means *TARGETNAME* is now acquired by *username:BLAHBLAH* since the
  ticket is *BLAHBLAH*.

- ``component``: for interfaces that understand multiple
  implementations or multiplex to multiple components (eg: *power*,
  *console*, *images*) this is a string that indicates to which
  instance to direct the request.

.. warning::

   FIXME: this document is work in progress, to get more info for the
   time being, ``tcf.git/ttbd`` unpacks most of these calls (as per
   the ``@app.route`` decorator); needed arguments can be extracted by
   look at what is obtained with *flask.request.form.get()*

Endpoints:

- ``/ttb/v1/login`` *PUT*
  
- ``/ttb/v1/logout`` *PUT*
  
- ``/ttb/v1/validate_session`` *GET*

- ``/ttb/v1/targets`` *GET*

- ``/ttb/v1/targets/TARGETNAME/`` *GET*

- ``/ttb/v1/targets/TARGETNAME/acquire`` *PUT*

- ``/ttb/v1/targets/TARGETNAME/active`` *PUT*
  
- ``/ttb/v1/targets/TARGETNAME/release`` *PUT*
  
- ``/ttb/v1/targets/TARGETNAME/enable`` *PUT*
  
- ``/ttb/v1/targets/TARGETNAME/disable`` *PUT*
  
- ``/ttb/v1/targets/TARGETNAME/property_set`` *PUT*
  
- ``/ttb/v1/targets/TARGETNAME/property_get`` *GET*
  
- ``/ttb/v1/targets/TARGETNAME/ip_tunnel`` *POST*
  
- ``/ttb/v1/targets/TARGETNAME/ip_tunnel`` *DELETE*
  
- ``/ttb/v1/targets/TARGETNAME/ip_tunnel`` *GET*  

- ``/ttb/v1/files/FILENAME`` *POST* upload a file to user's storage
  
- ``/ttb/v1/files/FILENAME`` *GET* download a file from the user's
  storage
  
- ``/ttb/v1/files/FILENAME`` *DELETE* delete a file from the user's
  storage
  
- ``/ttb/v1/files`` *GET* list files in the user's storage


General interface access
------------------------

Functionality to manipulate / access targets is implemented by
separate unrelated and available at the endpoints
``/ttb/v1/TARGETNAME/INTERFACENAME/METHODNAME`` (with PUT, GET, POST,
DELETE depending ont he operation).

Note different targets might implement different interfaces, and thus
not all of them are always avaialble. Interfaces supported by a target
are available by listing the target's metadata (with
``/ttb/v1/targets[/TARGETNAME]``) and looking for the value of the
*interfaces* field.

.. warning::

   FIXME: this document is work in progress, to get more info for the
   time being, ``tcf.git/ttbd/ttbl/*.py`` implements these interfaces
   by instantiating a :class:`ttbl.tt_interface` and implementing
   calls to ``METHOD_NAME`` where method is *put*, *post*, *get* or
   *delete*. The dictionary *args* passed is a dictionary with the
   arguments passed in the HTTP call.


Power
"""""

- ``/ttb/v1/targets/TARGETNAME/power/off`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/power/on`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/power/cycle`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/power/get`` *GET*
- ``/ttb/v1/targets/TARGETNAME/power/list`` *GET*

Console
"""""""

- ``/ttb/v1/targets/TARGETNAME/console/setup`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/console/list`` *GET*
- ``/ttb/v1/targets/TARGETNAME/console/enable`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/console/disable`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/console/state`` *GET*
- ``/ttb/v1/targets/TARGETNAME/console/size`` *GET*
- ``/ttb/v1/targets/TARGETNAME/console/read`` *GET*
- ``/ttb/v1/targets/TARGETNAME/console/write`` *PUT*

Capture
"""""""

- ``/ttb/v1/targets/TARGETNAME/capture/start`` *POST*
- ``/ttb/v1/targets/TARGETNAME/capture/stop_and_get`` *POST*
- ``/ttb/v1/targets/TARGETNAME/capture/list`` *GET*

Buttons
"""""""

- ``/ttb/v1/targets/TARGETNAME/buttons/sequence`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/buttons/list`` *GET*

Fastboot
""""""""

- ``/ttb/v1/targets/TARGETNAME/fastboot/run`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/fastboot/list`` *GET*

Images
""""""

- ``/ttb/v1/targets/TARGETNAME/images/flash`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/images/list`` *GET*


IOC_flash_server_app
""""""""""""""""""""

- ``/ttb/v1/targets/TARGETNAME/ioc_flash_server_app/run`` *GET*

Things
""""""

- ``/ttb/v1/targets/TARGETNAME/things/list`` *GET*
- ``/ttb/v1/targets/TARGETNAME/things/get`` *GET*
- ``/ttb/v1/targets/TARGETNAME/things/plug`` *PUT*
- ``/ttb/v1/targets/TARGETNAME/things/unplug`` *PUT*

Examples
--------

Example: listing targets over HTTP
""""""""""""""""""""""""""""""""""

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
"""""""""""""""""""""""""""""""""""""""""

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
