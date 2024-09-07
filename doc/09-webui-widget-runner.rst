The Widget Runner: Setup and description
========================================

The Widget Runner is a a general UI interface to an agent that
executes a script against a remote target using a *runner*; multiple
runners are supported per target.

This does not do the actual execution, but tells a runner agent (such
as Jenkins) to do the execution and monitors the output to display a
summary in the WebUI.

Each runner needs:

 - a pipeline URL that points to the agent that will execute
 - a type (only *jenkins* supported for now)
 - a remote git repository and a path to a script in it
 - a user name for the runner to use to access the target
 - an email address for the engine to notify (optional)

This will present controls in a UI to start and stop the script
execution and provide information about the progress in three columns:
result, elapsed time in minutes, summary of details which might
include links to more details. The details display can be toggled to
show just failures, all info or hide it all.

The information about result/summary is obtained by parsing the
runners's output, which is obtained calling its API. The rules for
parsing and reducing are taken from the target's inventory

In addition, this can display information about previous runs if it is
stored in a database; for now, only MongoDB is supported, via the
schema  :mod:`tcfl.report_mongodb` uses to report data into it.

See the Architecture:FIXMElink sections for more details on
implementation.

Deployment Guide
----------------

The following things are needed to deploy the widget runner:

- inventory entries for each target on which the runner has to operate
  (templates are available to simplify this process)

- a running agent (at this point Jenkins only supported)

- (optional) a MongoDB for history display


Setting up the Inventory
~~~~~~~~~~~~~~~~~~~~~~~~

.. _webui_widget_runner_setting_up_inventory:

The target's inventory describes the runner in the section
*runner.RUNNER*, where *RUNNER* is a simple name that is also a valid
inventory key (eg: *[-_a-zA-Z0-9]*) (FIXME:link). This allows fine
grained configuration of what shall be run where.


Since each runner can have a sizeable amount of information to
describe its operation, it is not practical to put it in every
target's inventory. Thus, templates are available, see **Templates**
below.


Thus, for each runner, declare entries in the inventory (again: in
*local.runner.default* to serve as default to all,
*local.runner.RUNNER* to set as defaults for a runner called *RUNNER*,
*target.runner.RUNNER* to set as set for target *target*, runner
*RUNNER*)--all entries are mandatory unless marked optional:

- **button_name**: name (simple string) to display next to the "run" button;
  basic HTML tagging is allowed (<b>, <i>, <a href>, etc)

  eg: "Run instrumentation healthcheck"

- **pipeline**: URL to pipeline; basic URL which will be used to
  compose API calls to the runner agent. In Jenkins, it'd be a
  parameterized job:

  eg: https://jenkinserver.mydomain.com/job/somejobname

- **type** pipeline type; only *jenkins* recognized at this point.

  eg: jenkins

- **repository**: URL of git source control repository for script;
  ensure it ends in **.git**:

  eg: https://github.com/someproject/somerepo.git

  Append *#BRANCHNAME* or *#REF* or *#TAG* to checkout an specific
  branch or reference/version/tag.

- **file_path**: relative path of script in repository

- **username**: name of user for the pipeline to access the target in
  this server; the pipeline must be able to login on its own or have
  already its credentials loaded associated to this username.

- **notify**: (optional) list of email addresses to notify of
  execution result; this is also runner type specific.

- **confirm**: (optional) a simple message to ask the user to confirm
  the operation. This is normally used when an script execution is
  potentially destructive and you want to give the user the chance to
  think twice about it.

- **confirm2**: (optional) a simple message to ask the user to really
  confirm the operation; normally only set with *confirm* for those
  fumblefinger users that can always use a second check.

- **regex**: dictionary of regular exprpessions to handle log messages
  and translate them to summarized entries in the WebUI display.

  When the WebUI parses the log output from the runner, each line is
  compared against this regular expressions looking for a match to
  display information or call out errors. If there is no match, the
  line is ignored.

  Each entry consists of a pattern to match against, a message
  template and a result template, to summarize / massage the line in
  the display table.

  - **regex.KEY.pattern**: a Javascript pattern that matches on a log
    line from the pipeline's output; use named groups so they can be
    replaced them later in the message and tag templates, eg::

      PROGRESS (?<subcase>\S+) step $(?<stepname>\S+)

  - **regex.KEY.message**: template for the summarized message; if
    none, *KEY* will be used.

    This is a template and fields are available to substitute as
    *%(FIELDNAME)s*: build_id, pipeline, type, repository,
    repository_nogit, file_path, targetid, runner. As well, all named
    groups from the regular expression pattern are also available, eg,
    from the example above::

      Got to %(stepname)s from %(file_path)s

  - **regex.KEY.result**: Same as above, but it is used to display a
    very summarized status in the first column (like *pass*, *fail*,
    etc) with maybe a hyperlink to state, a color. eg::

      <div display="background-color: green;"><a href = "%(pipeline)s/%(build_id)s/log">PASS</a></div>

  Notes on adding regexes for processing:

  - if *KEY* starts with *error_*, it will be considered this is
    latching to an error message and displayed as such, with purple
    coloring.

  - see :func:`target_runner_progress_tcf_add` for adding a template
    that can process output from executing using TCF, and can use used
    to create a template such as, in a :ref:`server configuration file
    <ttbd_configuration>`::

      target_local = ttbl.test_target.get('local')
      target_runner_progress_tcf_add(target_local, "default")

Setting up multiple runners
~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can define as many runners as needed.

It is easier however to template them; all fields will be taken from
the following locations inventory, in order (if not defined in one,
proceed to the next; some fields are optional)::

    TARGET.runner.RUNNERID.FIELD
    local.runner.RUNNERID.FIELD
    local.runner.default.FIELD

thus, templates can be created in the local target and then you can
proceed to just define for targets where you want to instantiate
them::

    TARGET1.runner.runner1.instantiate = True
    TARGET2.runner.runner1.instantiate = True
    TARGET3.runner.runner1.instantiate = True

the full runner1 definition can be taken from local.runner.runner1,
which is then the only place that needs to define it.


Templates
^^^^^^^^^

Runner values for field *FIELD* for runner *RUNNER* are gathered from
the following inventory keys in order:

 - local.runner.default.FIELDNAME
 - local.runner.RUNNER.FIELDNAME
 - TARGETID.runner.RUNNER.FIELDNAME

*local* is the target that describes the server. This is possible to
describe all the runners in a single place in in *local.runner* such
as by (eg) setting inventory entries such as:

  - local.runner.switch_healthcheck.\*
  - local.runner.server_healthcheck.\*
  - local.runner.client_healthcheck.\*

and then just instantiate for specific targets as:

  - switch1.runner.switch_healthcheck.instantiate: True
  - switch2.runner.switch_healthcheck.instantiate: True
  - switch3.runner.switch_healthcheck.instantiate: True

  - serverA.runner.server_healthcheck.instantiate: True
  - serverA.runner.server_healthcheck.instantiate: True

  - serverB.runner.server_healthcheck.instantiate: True

  - clientA.runner.client_healthcheck.instantiate: True
  - clientB.runner.client_healthcheck.instantiate: True
  - clientC.runner.client_healthcheck.instantiate: True

Setting the property *runner.RUNNER.instantiate* to *True* creates the
*runner.RUNNER dictionary*, which triggers the widget runner UI to
create a runner called *RUNNER* and pull the values from fields from
the local and target's inventories.

Example (simplified)::

  local.runner.default.username: jenkins_useragent
  local.runner.default.pipeline: https://jenkins.domain.com/job/widget-runner
  local.runner.default.type: jenkins

  local.runner.switch_healthcheck.button_name: Run <b>switch</b> healthcheck
  local.runner.switch_healthcheck.repository: https://gitlab.server.com/deployment/healthchecks.git
  local.runner.switch_healthcheck.file_path: common/test_switch.py

  local.runner.server_healthcheck.button_name: Run <b>server</b> healthcheck
  local.runner.server_healthcheck.repository: https://gitlab.server.com/deployment/healthchecks.git
  local.runner.server_healthcheck.file_path: common/test_server.py

  local.runner.client_healthcheck.button_name: Run <b>server</b> healthcheck
  local.runner.client_healthcheck.repository: https://gitlab.server.com/deployment/healthchecks.git
  local.runner.client_healthcheck.file_path: common/test_server.py

Now the instantation and a very specific one for *server3*::

  server1.runner.client_healthcheck.instantiate: True
  server1.runner.server_healthcheck.instantiate: True

  server2.runner.client_healthcheck.instantiate: True
  server2.runner.server_healthcheck.instantiate: True

  server3.runner.client_healthcheck.instantiate: True
  server3.runner.server_healthcheck.instantiate: True
  server3.runner.server3_healthcheck.button_name: Run <b>server3 specific</b> healthcheck
  server3.runner.server3_healthcheck.repository: https://gitlab.server.com/deployment/healthchecks.git
  server3.runner.server3_healthcheck.file_path: common/test_server3_specific.py

In a server :ref:`server configuration file: <ttbd_configuration>`
these cab be primary coded as::

  target_local = ttbl.test_target.get("local")   # assume local target already created

  target_local.property_set("local.runner.default.pipeline",
                            "https://jenkins.domain.com/job/widget-runner")
  # etc, etc...

  for name in [ "server1", "server2", "server3" ]:
      target = ttbl.test_target.get(name)   # assume target already created

      # server targets can do both client and server healthchecks
      target.property_set("local.runner.default.client_healthcheck.instantiate", True)
      target.property_set("local.runner.default.server_healthcheck.instantiate", True)

  target = ttbl.test_target.get("server3")   # assume target server3 already created
  target.property_set("server3.runner.server3_healthcheck.button_name",
                      "Run <b>server3 specific</b> healthcheck")
  target.property_set("server3.runner.server3_healthcheck.repository",
                      "https://gitlab.server.com/deployment/healthchecks.git
  target.property_set("server3.runner.server3_healthcheck.file_path",
                      "common/test_server3_specific.py")

Another example::

  target_local = ttbl.test_target.get('local')
  target_local.property_set("runner.default.pipeline", "https://JENKINSSEVER/job/JOB-WIDGET-RUNNER/")
  target_local.property_set("runner.default.type", "jenkins")
  target_local.property_set("runner.default.username", "USERNAME-FOR-JENKINS")
  # leave empty, so we notify the calling user by default
  target_local.property_set("runner.default.notify", None)

  # (optional, get historical builds) set parameters for MongoDB --
  # like those for tcfl.report_mongodb
  #
  # Define passwords for MongoDB
  commonl.passwords[re.compile("USERNAME@MONGOHOST")] = \
      "FILE:/etc/ttbd-production/pwd.MONGOHOST.USERNAME"
  target_local.property_set("runner.default.mongo_url", "mongodb://USERNAME@MONGOHOST:7764/DBNAME?ssl=true&replicaSet=mongo7764")
  target_local.property_set("runner.default.mongo_db", "DBNAME")
  target_local.property_set("runner.default.mongo_collection", "COLLECTION")

  # Now define templates for jobs, just what's different
  target_local.property_set("runner.instrumentation_healthcheck.button_name", "Instrumentation Healthcheck")
  target_local.property_set("runner.instrumentation_healthcheck.repository", "https://github.com/PATH/reponame.git")
  target_local.property_set("runner.instrumentation_healthcheck.file_path", "testcases/test_healthcheck_instruments.py")

  target_local.property_set("runner.sysbench.button_name", "Run Linux sysbench")
  target_local.property_set("runner.sysbench.repository", "https://github.com/intel/tcf.git")
  target_local.property_set("runner.sysbench.file_path", "examples/test_sysbench.py")

  # Now enable on specific targets
  target = ttbl.test_target.get('qemu-02e')
  target.property_set("runner.instrumentation_healthcheck.instantiate", True)
  target.property_set("runner.sysbench.instantiate", True)


Setting up the runner
~~~~~~~~~~~~~~~~~~~~~

The runner is the external agent that will do the actual script
execution. Currently only Jenkins is supported, but others can be
added.

Runner's responsibilities / actions:

- run only one script on a target at the same time -- the target is
  allocated already

- the user logged into the WebUI must be able to access the runner
  server and have an account in there.


Setting up Jenkins as a runner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The user has to have login access to Jenkins and the ability to start
builds and read; Jenkins has to be configured to support CORS so the
user's browser can call into its API.

1. Create a job (eg, we'll call it JOBNAME): the job has to be a
   parameterized job; it will be called with a set of parameters by
   doing a *POST* request to the *pipeline*, eg
   https://SERVERNAME/job/JOBMAME/buildWithParameters

   the parameters will be (from the inventory data):

   - *param_manifest*: GITREPOSITORYURL FILE_PATH
   - *param_notify_email*: comma separated list of email addresses
   - *param_ttbd_allocid*: allocation ID
   - *param_ttbd_servers*: URL of the server
   - *param_ttbd_targetid*: name of the target where to run

2. Configure Jenkins API access: authentication.

   The WebUI user has to have access to Jenkins (read and launch
   builds for the given pipeline).

   The WebUI access the Jenkins server using the cookies of the user,
   and thus the user must be logged into Jenkins for it to work.

   The WebUI accesses Jenkins using the cookies of the user who is
   currently logged in.

3. Configure Jenkins API access: configure permissions:

   1. Go to *Manage Jenkins > Configure Global Security*

   2. Select *Matrix Based Authentication*

   3. For users: decide a group, make sure they are members of it and set they can

     - job build
     - job cancel
     - job read

3. Configure Jenkins API access: CORS
   .. _webui_widget_runner_jenkins_cors:

   1. To access the API we need cookies and crumb.

      A set of cookies; which we get doing fetch() calls with the
      *credentials: "include"* argument; this gets them all from the
      cookies store. ; the cookies are there since the user logged in
      to Jenkins already, they have the domain they accept.

   2. a crumb (jenkins specific); we get that from the API using the
      cookie and then cache them per pipeline -- otherwise you get
      a 403.

   3. Setup CORS to include allow (get from todo)

     1. Go to *Manage Jenkins > Plugins*, install "CORS filter"

     2. Go to *Manage Jenkins > System*, scroll down to CORS Filter

     3. Ensure it is enabled *Enabled*

     4. Set:

        - *Access-Control-Allow-Origins*: \*
	- *Access-Control-Allow-Methods*: GET,PUT,POST,OPTIONS,DELETE
	- *Access-Control-Allow-Headers*: accept,accept-encoding,accept-language,access-control-allow-origin,access-control-request-headers,access-control-request-method,authorization,connection,content-type,dnt,jenkins-crumb,location,origin,priority,referer,sec-fetch-dest,sec-fetch-mode,sec-fetch-site,te,user-agent,x-requested-with
	- *Access-Control-Expose-Headers*: access-control-allow-origin,authorization,jenkins-crumb,location
	- *Access-Control-Max-Age*: 999

     5. Click *Apply*, then *Save*


Setting up informationf or historical runs from MongoDB
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FIXME



Architecture and implementation details
----------------------------------------

The UI widget provides just a way to interact with remote pipelines
that do the actual execution and summarize the output of said
pipelines in a table with three columns (result summary, ellapsed
time, message).

The HTML provides the following main input points:

- user clicked the button to start/stop a run

  The call goes into a general part and then it calls a pipeline type
  specific one (jenkins, etc)

  When starting it, we call the pipeline start function with the
  parameters for what we want to run and where and then pretty much
  call the state update function that keeps calling itself to update
  until the pipeline ends (see next)

- user clicked the button to refresh the last run information

  The call goes into a general part and then it calls a pipeline type
  specific one (jenkins, etc) -- this generally just gets the log from
  the pipeline and parses it to summarize in the table.

- user clicked the buttons to toggle the visibility of the run
  information (show all, show only failures, hide all).

  The rows in the table are tagged so indicate if they report failure
  information or others, so we can toggle visbibility (sometimes it's
  better just to see failures).

- user clicked the buttons to show historical information

  If access to a MongoDB is enabled and the pipeline has reported
  there, we can report historical information.

FIXME: Architecture: document MongoDB caching using doc count


Jenkins specifics
~~~~~~~~~~~~~~~~~

For Jenkins: the Javascript code starts a job using the Jenkins API
passing the parameters specified and displays output that is filtered
based on FIXME:templates



Troubleshooting
---------------

Jenkins: CORS errors, eg in browser console
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the following message is displayed in the web browser console
(*inspect > console*)::

  Cross-Origin Request Blocked: The Same Origin Policy disallows
  reading the remote resource at https://jenkins.server.com/crumbIssuer/api/json.
  (Reason: CORS header ‘Access-Control-Allow-Origin’ missing).
  Status code: 200.

This means CORS is disabled in Jenkins, configure it (see
:ref:`instructions <webui_widget_runner_jenkins_cors>` above).


Jenkins: Launching BUILD returns a 404, alert message
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

User has no permission in jenkins to build

