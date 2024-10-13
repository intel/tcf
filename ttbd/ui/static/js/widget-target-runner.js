/* See ../../doc/09-webui-widget-runner.rst */

"use strict";

/*


  ROADMAP
  =======


  js_runner_state_update
    js_runner_jenkins_state_update
      js_runner_jenkins_build_state_check
      js_runner_ui_state_set
      js_runner_run_button_disable
      js_runner_run_button_enable
      js_runner_jenkins_log_parse: read jeknins console, parse it
        _js_runner_build_tbodies_add(): add a row header for a build
        _js_runner_build_tbodies_data_add():  add a row of data
      js_runner_jenkins_state_update_deferred           if the build still going
        js_runner_jenkins_state_update -> async after 2s


    js_runner_previous_builds_toggle():
      _js_runner_build_tbodies_add(): add a row header for a build
      _js_runner_build_tbodies_data_add():  add a row of data to a build


   HTML > tbody header for build
     js_runner_table_toggle_hide: in a build toggle show all/show fails only/hide log

   js_runner_ui_toggle_button_html: generates the UI button to call js_runner_table_toggle_hide


  FIXME:

  - Summarize build output in current DONE field
    latch on summary

  - add error regxes to catch
    - jenkins: failed tcf stuff doesn't error the build

  - add a tip: you can run this with "tcf run -vt {{ targetid }} ... "

  - ensure all values from invenroy are sanitized to basic text so
    there is no HTML crashes

  - this needs a serious roadmap

  - remove dep on .build_id -> just query jenkins for builds and see
    who is active? who was last?

  - FIXME: this means user A could cancel user B's, which at some
     point we have to address, maybe with dynamic pipelines per
     user/target/script, but that's another deal).

  - pipeline speedup idea -> if the GIT revision is the same, clearly
    the container won't have to change, so maybe cache up by git commit
    ID -- map git commit IDs to container version and keep using that?
    tag it in the container repo as a git; this way we don't even have
    to check it out--we just query it's commit, see if we have it and
    use it or then checkit out and compute it.

  - disable button until a BUID ID is found since it is clicked
     DEBUG [null]: job_container_run(applications.infrastructure.capi.tcf-intel.git): image: REGISTRYHOST/PROJECT/REPO.git__master:6b4485a1a5b63409  jenkins image REGISTRYHOST/PROJECT/jenkins-agent:latest

     - ensure log pull function can run only once

  - can we tag the build in jenkins with the targetid and the manifest
    so we can search which one like that are running and cleanup?  yes,
    let's just set the build description to include the tc_path and the
    targetid and filter by that we can pass in param_capi_description a
    UUID we can use to then just list by that to identify

  - tcf enable fileprefix in argparse
*/



/*
 * Common functions
 */
async function js_ttbd_target_property_set(targetid, property, value) {
    let r = await fetch('/ttb-v2/targets/' + targetid, {
	method: 'PATCH',
	headers: { 'Content-Type': 'application/json; charset=UTF-8', },
	body: JSON.stringify({[property]: value,})
    });
    console.log(`js_ttbd_target_property_set ${targetid} set ${property} to ${value}`)
    return r
}


/*
  Return a runner's data field, maybe taking defaults from a template
 */
function js_runner_field_get(targetid, runner, field) {
    const runner_data = inventory[targetid]['runner'][runner] ?? null;
    if (runner_data == null) {
        let msg = `CONFIGURATION ERROR: ${targetid} asking for`
	    + ` runner "${runner}" that does not exist in inventory`;
	alert(msg);
	throw new Error(msg);
    }
    // take values from local.runner.default.FIELD and
    // local.runner.RUNNERNAME.FIELD; the idea is that we can create
    // templates like that.
    const local_default_value = inventory["local"].runner?.default?.[field] ?? null;
    const local_runner_value = inventory["local"].runner?.[runner]?.[field] ?? null;
    const runner_value = runner_data[field] ?? null;

    //console.log(`js_runner_field_get(${targetid}, ${runner}, ${field}):`
    //		+ ` ${local_default_value} ${local_runner_value} ${runner_value}`)

    // note the values might be objects/dictionaries, so we have to
    // merge them up, with values from targetid.runner.RUNNER
    // overriding local.runner.RUNNER overriding local.runner.default
    let value = local_default_value;
    if (local_runner_value != null) {
	if (value && value.constructor == Object
	    && local_runner_value.constructor == Object) {
	    value = Object.assign({}, value, local_runner_value);  // merge up
	} else
	    value = local_runner_value;
    }

    if (runner_value != null) {
	if (value && value.constructor == Object
	    && runner_value.constructor == Object) {
	    value = Object.assign({}, value, runner_value);        // merge up
	} else
	    value = runner_value;
    }

    if (field == "notify" && value == null) {
	// take by default the userid of the calling user -- only
	// works if it maps to an email, but beats nothing
	value = state.user;
    }

    return value
}



/* jenkins crumbs by sever -- read in doc header -- */
const jenkins_crumbs = {};


async function jenkins_fetch(pipeline, path, method, body = null) {
    let headers = {};
    if (pipeline.endsWith("/")) {
	pipeline = pipeline.slice(0, -1);
    }
    let url = new URL(pipeline);
    if (!path.endsWith("/crumbIssuer/api/json")) {
  	headers['Jenkins-Crumb'] = await js_widget_runner_jenkins_get_crumb(pipeline);
        console.log(`jenkins_fetch(${pipeline}, ${path}, ${method}): using crumb ${headers['Jenkins-Crumb']}`);
    }
    else
        console.log(`jenkins_fetch(${pipeline}, ${path}, ${method}): not using crumbs`);
    let r = null
    try {
	let args =  {
	    headers: headers,
	    method: method,
	    credentials: 'include',
	    body: body,
	};
	if (path.endsWith("/kill")) {
	    // when we do kill, we get a 302 but shows as a 0 for whatever
	    // reaosns, but it's ok
	    args['redirect'] =  "manual";
	}
	r = await fetch(`${pipeline}/${path}`, args);
	if (r.ok)
	    return r;
    } catch (e) {
        console.error(`ERROR/network: fetching ${pipeline}/${path}: ${e.message}`);
	if (e instanceof TypeError) {
	    // FIXME: there has to be a better way here
	    if (e.message.includes("NetworkError when attempting to fetch resource") /* Firefox */
		|| e.message.includes("Failed to fetch") /* Chromish */) {
		// generally CORS or didn't login
		await confirm_dialog(
		    `ERROR calling Jenkins ${pipeline}:<br>`
			+ ` (1) ensure you  <a href = "${url.protocol}//${url.host}/login" target="_blank" rel="noopener noreferrer">logged in </a><br>`
			+ ` (2) ensure your admin has configured CORS per deployment guide`,
		    "I am done logging in (window will reload)"
		);
		window.location.reload();	// need to reload so the cookies are picked up
		return null;
	    }
	}
	confirm_dialog(
	    `ERROR calling Jenkins ${pipeline}; check Web console log`,
	    "Acknowledge");
	return null;
    }

    let text = await r.text();

    if (text.includes("No valid crumb was included in the request")) {
	confirm_dialog(
	    "BUG? got an HTTP ERROR 403: No valid crumb was included in the request",
	    "I am done");
    }
    else if (r.status == 403) {
	await confirm_dialog(
	    `You need to <a href = "${url.protocol}//${url.host}/login" target="_blank" rel="noopener noreferrer">`
	    + `login</a> to jenkins and try again.`,
	    "I am done loging in (window will reload)"
	);
	window.location.reload();	// need to reload so the cookies are picked up
    }
    else if (r.status == 0 && path.endsWith("/kill") && method == "POST") {
	// when we do kill, we get a 302 but shows as a 0 for whatever
	// reaosns, but it's ok
	return r;
    } else  {
	confirm_dialog(
	    `Jenkins call ${pipeline}/${path} returned ${r.status}; check the web console`,
	    "I am done"
	);
    }
    return r;		
}



/* return a crumb for a pipeline -- read in doc header */
async function js_widget_runner_jenkins_get_crumb(pipeline) {
    let crumb = jenkins_crumbs[pipeline] ?? null;
    if (crumb) {
	console.log(`js_widget_runner_jenkins_get_crumb(${pipeline}): got cached ${crumb}`);
	return crumb;
    }
    let url = new URL(pipeline);
    let r = await jenkins_fetch(`${url.protocol}//${url.host}`, '/crumbIssuer/api/json',
				"GET");
    crumb = (await r.json())['crumb'];
    console.log(`js_widget_runner_jenkins_get_crumb(${pipeline}): got new ${crumb}`);
    jenkins_crumbs[pipeline] = crumb;
    return crumb;
}


/*
 * Sets the visual state of the runner's status
 *
 * state: a string UNKNOWN | PENDING | RUNNING | READY
 *
 * FIXME: add coloring
 */
function js_runner_ui_state_set(runner, state) {
    let el = $(`#label_id_runner__${runner}__status`);
    el.empty();
    el.append(state);
}



function _js_runner_bad(runner, targetid, type) {
    alert(
        `CONFIGURATION ERROR: ${targetid} inventory`
	    + ` runner.${runner}.type reports type ${type} which`
	    + ` is unknown (known: jenkins)`
    );
}



/*
* releases target based on an allocation id
*
* @param {allocid} str -> allocation id that you want to remove
*
* returns: tuple of [ building, result ] from Jenkins API
*  - building: true | false -> not building
*  - result: ABORTED FAILURE NOT_BUILT SUCCESS UNSTABLE
*        https://javadoc.jenkins.io/hudson/model/class-use/Result.html
*/

async function js_runner_jenkins_build_state_check(pipeline, build_id) {

    let r = await jenkins_fetch(pipeline, `/${build_id}/api/json`, "GET");
    console.log(`js_runner_jenkins_build_state_check: pipeline ${pipeline} build ${build_id} status: ${r.status}`)
    if (r.status != 200) {
	console.log(`js_runner_jenkins_build_state_check: pipeline ${pipeline} build ${build_id} error: ${r.text}`)
        return [ false, false ];
    }
    let data = await r.json();
    let building = data['building'] ?? null;
    let result = data['result'] ?? null;
    console.log(`js_runner_jenkins_build_state_check: pipeline ${pipeline} build ${build_id} building=${building} result=${result}`);
    // FIXME: return timestamp too -- set the ID field in jenkins
    return [ building, result ];
}


/*
 * Query the ttbd inventory for build id
 *
 */
async function js_runner_ttbd_build_id_query(runner, targetid) {

    // get from the inventory if there is a current build ID
    // FIXME: from js we can't just query THAT FIELD, so we need to do the whole inv...sigh
    //
    //     let r = await fetch('/ttb-v2/targets/' + targetid + `?projections=["runner.${runner}.build_id"]`, {
    //
    //   tried the body, but turns out fetch doesn't allow to send
    //   bodies with GET...wtf
    //
    //    headers: {
    //	    'Content-Type': 'application/x-www-form-urlencoded'
    //   },
    //   body: new URLSearchParams({
    //       "projections": `["runner.${runner}.build_id"]`,
    //   })
    let r = await fetch('/ttb-v2/targets/' + targetid, { method: 'GET',})
    let data = await r.json()
    // DO NOT access via js_runner_field_get(), since that uses the
    // inventory we have recorded in the HTMl -- this queries the
    // server for possible updates.
    // r.json() is a nested dict { runner { runner1 { build_id: value } }
    const data_runners = data['runner'] ?? {};
    const data_runner = data_runners[runner] ?? {};
    const build_id = data_runner["build_id"] ?? null;
    console.log(`js_runner_jenkins_build_state_check: runner ${runner} ttbd build ${build_id}`);
    return build_id
}


function js_runner_run_button_enable(runner, reason) {
    console.log(`js_runner_run_button_set_ready(${runner}, ${reason}): enabling run button`)
    let html_element = $(`#widget-runner-${runner}-run-button`);
    html_element.empty();
    html_element.prop('disabled', false);
    html_element.prop('class', 'primary');
    html_element.empty();
    //html_element.append(html_element.attr('label_original'));
    html_element.append("▶");
}

function js_runner_run_button_disable(runner, reason) {
    console.log(`js_runner_run_button_set_ready(${runner}, ${reason}): disabling run button`)
    let html_element = $(`#widget-runner-${runner}-run-button`);
    html_element.empty();
    html_element.prop('class', 'warning');
    html_element.empty();
    //html_element.append("CANCEL: " + html_element.attr('label_original'));
    html_element.append("■");
}


async function js_runner_jenkins_state_update_deferred(
    runner, targetid, pipeline, file_path, build_id) {
    /* sleep some */
    console.log(`js_runner_jenkins_state_update_deferred(${runner}, ${targetid}, ${pipeline}): waiting 1s`)
    await new Promise(r => setTimeout(r, 2000));	// 1s im ms
    console.log(`js_runner_jenkins_state_update_deferred(${runner}, ${targetid}, ${pipeline}): calling 1s`)
    await js_runner_jenkins_state_update(runner, targetid, pipeline, file_path, null);
}



/*
  Read the jenkins console output and parse it out to produce
  summarized rows of information in a table

  Since this will be called multiple times, we store an offset (in
  lines, because Jenkins) of the last time we called this in the
  tbody_element.

  Each line of jenkins log has a time offset in minutes and then
  whatever -> this whatever gets chewed based on the rules we pass in
  the regexes. Those rules are site specific, and depend on what you
  have in your pipelines. There is a set of defined regexes to extact
  info from TCF execution.

  FIXME: we need to figure out how to sequence this function so
  only one is running at the same time
*/
async function js_runner_jenkins_log_parse(
    runner, targetid, pipeline, build_id, file_path) {

    const repository = js_runner_field_get(targetid, runner, 'repository');
    const runner_info = {
	build_id: build_id,
	pipeline: pipeline,
	file_path: file_path,
	repository: repository,
	repository_nogit: repository.replace(new RegExp("\.git/?$"), ""),
	targetid: targetid,
	runner: runner,
	type: "jenkins",
    };


    let tbody_data_el = document.getElementById(`label_id_runner_${runner}_build_main_data`);
    let table_main_control_el = document.getElementById(`label_id_runner_${runner}_table_main_control`);
    /* do one attr per build, to simplify not havig to clean it up */
    let console_offset_lines = table_main_control_el.getAttribute(`console_offset_lines-${build_id}`);
    if (console_offset_lines == null)
	console_offset_lines = 0;
    else
	console_offset_lines = parseInt(console_offset_lines);

    /* get all lines since last count of lines
     *
     * https://plugins.jenkins.io/timestamper/
     */
    console.log(`js_runner_jenkins_log_parse(${runner}, ${targetid}, ${pipeline}, ${build_id}): getting log from line ${console_offset_lines}`)
    const search_params = new URLSearchParams()
    search_params.set("elapsed", "m");			/* elapsed time in minutes */
    search_params.set("appendLog", true);			/* give us log lines */
    search_params.set("startLine", console_offset_lines);	/* only the new ones */
    let r = await jenkins_fetch(
	pipeline, `/${build_id}/timestamps?${search_params.toString()}`,
	"GET")
    let text = await r.text();
    var lines = 0;

    /* extract the regexes from the inventory
       FIXME: cache this somewhere */

    const regexes_from_inv = js_runner_field_get(targetid, runner, 'regex');
    const regexes = {}
    const fields_valid = Object.keys(runner_info).join(",");
    /* compile'em */
    for (let key in regexes_from_inv) {
	// this iterates over all the things defined in runner.RUNNER.regex.*
	const pattern = regexes_from_inv[key].pattern ?? null;
	// if there is a replacement field, use it, otherwise replace with the key
	const message = regexes_from_inv[key]?.message ?? key;
	const result = regexes_from_inv[key].result ?? null;

	// POS Javascript can't key with the regex object...we can't
	// key in the message since we could have identical ones we
	// are replacing with and we'd loose them--pattern is more
	// likely to be unique, but still could be bad, so we just key
	// on...the key from inventory, that is guarenteed to be
	// unique

	if (pattern == null) {
	    alert(`CONFIGURATION ERROR: runner.${runner}.regex.${key}:`
		  + "field *pattern* not defined--check for typos, is the most"
		  + "common scenario; ignoring");
	    continue;
	}
	// FIXME: expand build data
	const pattern_templated = pattern.replace(
		/%\((\w+)\)s/g, (_, field) => runner_info[field] || `${field}:UNDEFINED`);
	if (pattern_templated.includes(`:UNDEFINED`)) {
	    alert(`
CONFIGURATION ERROR: runner.${runner}.regex.${key}.pattern: pattern template contains invalid
 fields, marked with UNDEFINED (valid are: ${fields_valid}); pattern is
 ${pattern_templated} is tryingcontains unknown fields ${key}`);
	    continue;
	}
	//console.log(`js_runner_jenkins_log_parse(${runner}, ${targetid}, ${pipeline}, ${build_id}):`
	//	    + ` compiling regex ${pattern_templated}`);
	regexes[key] = [ new RegExp(pattern_templated), message, result ];
    }


    /* So now iterate over the lines and see if each matches any
     * regex; use the regex match dictionary and the runner_info
     * dictionary to format the message and result templates described in
     * the inventory in runner.RUNNER.regex.* and set displays for it
     *
     */
    let m = null;
    let parts = null;
    let elapsed = null;
    let rest = null;
    //console.log(`js_runner_jenkins_log_parse(${runner}, ${targetid}, ${pipeline}, ${build_id}): got text: ${text}`)
    for (const line of text.split("\n")) {
	//console.log(`line ${lines} is ${line}`);
	lines++;

	let result = null;
	// Each log line is <ELAPSED-TIME-IN-MINS> <LINE>
	parts = line.split("  ", 2);
	elapsed = parts[0];
	rest = parts[1];

	for (let regex_key in regexes) {
	    let regex = regexes[regex_key][0];

	    m = regex.exec(rest);
	    if (m == null)
		continue;

	    // now format the replacement template, all the
	    // %(FIELD)s in there, with the matches from the regex
	    // AND the build info whic has the data from the runner
	    let message_template = regexes[regex_key][1];
	    let result_template = regexes[regex_key][2]

	    let message = message_template;
	    // merge up the runner_info and m.groups dictionaries, having
	    // m.groups key override runner_info's
	    let all_info = Object.assign({}, runner_info, m.groups?? {});
	    message = message.replace(
		// replaces %(KEY)s with allinfo[KEY] or KEY:UNDEFINED
		// if not defined in all_info
		/%\((\w+)\)s/g, (_, key) => all_info[key] || `${key}:UNDEFINED`);

	    if (result_template) {
		result = result_template.replace(
		    // replaces %(KEY)s with allinfo[KEY] or KEY:UNDEFINED
		    // if not defined in all_info
		    /%\((\w+)\)s/g, (_, key) => all_info[key] || `${key}:UNDEFINED`);
	    } else if (regex_key.startsWith("ignore_")) {
		break;			// we need to ignore this line
	    } else if (regex_key.startsWith("error_")) {
		// FIXME: #${lines} doesn't work, how do we get to the line?
		result = '<div style = "background-color: #d000d0;">'
		    + `<a href = "${pipeline}/${build_id}/consoleFull#${lines}" target="_blank" rel="noopener noreferrer">`
		    + '<code>ERRR</code></a></div>';
	    } else {
		result = "";
	    }	
	    _js_runner_build_tbodies_data_add("main", tbody_data_el,
					      result, elapsed, message);
	    break;	// Only one match per line -> next line
	}
	// no regex matched with this line, ignored
	
    }
    console.log(`js_runner_jenkins_log_parse(${runner}, ${targetid}, ${pipeline}, ${build_id}): got ${lines} more lines`)
    console_offset_lines += lines;
    table_main_control_el.setAttribute(`console_offset_lines-${build_id}`,
				       console_offset_lines);
}



async function js_runner_jenkins_state_update(
    runner, targetid, pipeline, file_path, build_id = null) {
    let r = null;
    let html_state_table_el_control = $(`#label_id_runner_${runner}_table_main_control`);
    js_runner_ui_state_set(runner, '<span style="background-color: yellow;">PENDING</span>');
    js_runner_run_button_disable(runner, "checking build state")
    if (build_id == null)
	build_id = await js_runner_ttbd_build_id_query(runner, targetid);
    console.log(`js_runner_jenkins_state_update(${runner}, ${targetid}, ${pipeline}): build_id ${build_id}`)
    if (build_id != null) {
	// there is a build declared that was running, let's check status on it
	const [ building, result ] = await js_runner_jenkins_build_state_check(pipeline, build_id)
	if (building) {
	    // the build is still going, get the current log and
	    console.log(`js_runner_jenkins_state_update(${runner}, ${targetid}, ${pipeline}): we are running`)
	    js_runner_ui_state_set(runner, '<span style="background-color: orange;">RUNNING</span>')
	    js_runner_run_button_disable(runner, `jenkins ${pipeline} running build ${build_id}`);
	    js_runner_jenkins_log_parse(runner, targetid, pipeline, build_id, file_path);
	    js_runner_jenkins_state_update_deferred(runner, targetid, pipeline, file_path, build_id);
	} else if (!building && !result) {
	    // Since this build doesn't exist, just clear it out
	    console.log(`js_runner_jenkins_state_update(${runner}, ${targetid}, ${pipeline}): ${build_id} doesn't exist, clening`)
	    js_runner_ui_state_set(runner, "READY")
	    js_runner_run_button_enable(runner, `no info for jenkins ${pipeline} build ${build_id}`)
	    r = await js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, null)
	} else {
	    console.log(`js_runner_jenkins_state_update(${runner}, ${targetid}, ${pipeline}): ${build_id} is done, reporting`)
	    let tr_el = _js_runner_build_tbodies_header_tr_make(
		runner, targetid, build_id, "main",
		"DONE",
		`Execution <a href = "${pipeline}/${build_id}/consoleFull" target="_blank" rel="noopener noreferrer">#${build_id}</a>`);
	    let tbody_el = document.getElementById(`label_id_runner_${runner}_build_main_header`);
	    tbody_el.innerHTML = '';
	    tbody_el.appendChild(tr_el);
	    await js_runner_jenkins_log_parse(runner, targetid, pipeline, build_id, file_path);
	    // we don't clear the build ID in here, since this was the
	    // last build run and we can use it to map to results
	    //js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, null)
	    // FIXME: we'll need to report then based on data from the
	    // DB, since th build info in Jenkins will be removed
	    // FIXME: report last timestamp somewhere
	    js_runner_ui_state_set(runner, "READY")
	    // do one last log collection
	    js_runner_run_button_enable(runner, `Jenkins ${pipeline} build ${build_id} finished`)
	}
    } else {
	js_runner_ui_state_set(runner, "READY")
	js_runner_run_button_enable(runner,  `Jenkins ${pipeline} no builds running`)
    }
}


/*
 * Update the state table for this runner
 *
 * Queries the runner for information and fills the main table with
 * data from the last build.
 *
 * The last build is determined because we set it in
 * runner.RUNNER.build_id, FIXME: move that to just pull from runner service.
 *
 * The info is rendered in a table called "the main table", a tbody
 * for that. We use tbodys so we can easily hide them when minimizing.
 *
 */
async function js_runner_state_update(runner, targetid) {
    let tbody_data_el = $(`#label_id_runner_${runner}_build_main_data`);
    let table_main_control_el = $(`#label_id_runner_${runner}_table_main_control`);
    const type = js_runner_field_get(targetid, runner, 'type');
    const pipeline = js_runner_field_get(targetid, runner, 'pipeline');
    const file_path = js_runner_field_get(targetid, runner, 'file_path');
    /* remove table from previous runs */
    tbody_data_el.empty();
    if (type == "jenkins") {
	/* jenkins: reset the console offset we read from */
	let build_id = await js_runner_ttbd_build_id_query(runner, targetid);
	table_main_control_el.attr(`console_offset_lines-${build_id}`, 0);
	js_runner_jenkins_state_update(runner, targetid, pipeline, file_path, build_id);
    } else
	_js_runner_bad(runner, targetid, type);
}



async function js_runner_jenkins_stop_if_running(runner, targetid, allocid) {
    const pipeline = js_runner_field_get(targetid, runner, 'pipeline');
    const file_path = js_runner_field_get(targetid, runner, 'file_path');

    let r = null;
    let build_id = await js_runner_ttbd_build_id_query(runner, targetid)
    if (build_id != null) {
	/* according to the inventory, we are building; are we done?
	 * query jenkins for info */
	const [ building, result ] = await js_runner_jenkins_build_state_check(pipeline, build_id)
	if (building) {
	    await jenkins_fetch(pipeline, `${build_id}/kill`, 'POST');
	    js_runner_ui_state_set(runner, "READY");
	    js_runner_run_button_enable(runner, `jenkins ${pipeline} build ${build_id} killed`);
	    r = await js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, null);
	    return true;
	}
	// we are not, we do not clear, so we keep the last build info
	// present
    }
    return false;
}


async function js_runner_jenkins_start(
    runner, targetid, allocid) {
    const repository = js_runner_field_get(targetid, runner, 'repository');
    const pipeline = js_runner_field_get(targetid, runner, 'pipeline');
    const file_path = js_runner_field_get(targetid, runner, 'file_path');

    /* FIXME: check it is not building */
    let r = null;
    let build_id = await js_runner_ttbd_build_id_query(runner, targetid)

    // clean the build info from the table -- except for the first row, which has the status
    let html_state_table_el = $(`#label_id_runner_${runner}_build_main_data`);
    html_state_table_el.empty();

    let tr_build_header_el = document.getElementById(`label_id_runner_${runner}_build_main_header`);
    let tr_el = _js_runner_build_tbodies_header_tr_make(
	runner, targetid, build_id, "main",
	"WAITING", "Requesting new build ID");
    tr_build_header_el.innerHTML = '';
    tr_build_header_el.appendChild(tr_el);
    js_runner_ui_state_set(runner, '<span style="background-color: orange;">ASKING</span>')
    js_runner_run_button_disable(runner, `jenkins ${pipeline} launchig build`)

    /* make the jenkins user a guest; that's declared in the targets
     * runner.${runner}.username */
    let username = js_runner_field_get(targetid, runner, 'username');
    if (username == null) {
	alert("Configuration BUG, target needs to declare inventory"
	      + `runner.${runner}.username with the username Jenkins will`
	      + " use to access it."
	      + " It can be added via config or command line: "
	      + ` <code>tcf property-set ${targetid} runner.${runner}.username`
	      + " JENKINSUSERNAME</code></p>.")
	return;
    }
    await js_alloc_guest_add(allocid, username);
    // we leave it added as guest for other calls...no point on trying
    // to remove it as it introduces a host of race conditions
    console.log(`js_runner_jenkins_schedule: added ${username} as guest in ${allocid}`)

    let notify = js_runner_field_get(targetid, runner, "notify");
    if (notify == null) {
	// take by default the userid of the allocation owner
	notify = state.user ?? null;
    }

    /*
     * launch the Jenkins build, get the build ID
     *
     * Holy cow in a motorbike, this could have been easier
     */
    r = await jenkins_fetch(
	pipeline, '/buildWithParameters', 'POST',
	new URLSearchParams({
	    "param_manifest": `${repository} ${file_path}`,
	    "param_notify_email": notify,
	    "param_ttbd_allocid": allocid,
	    "param_ttbd_servers": `${ttbd_server_url.protocol}//${ttbd_server_url.host}`,
	    "param_ttbd_targetid": targetid,
	})
    );
    if (r == null || !r.ok) {	// it failed, backup
	js_runner_ui_state_set(runner, "READY");
	js_runner_run_button_enable(runner, `jenkins ${pipeline} build ${build_id} killed`);
	js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, null);
	return;
    }

    /*
     * the location header has the queue ID
     *
     *   location: https://jenkins.server.com/queue/item/80588/
     *
     * GET that and
     *
     *  {
     *     ...,
     *     "id" : 39,
     *      "inQueueSince" : 1423993879845,
     *     ...,
     *     "cancelled" : false,
     *     "executable" : {
     *        "number" : 35,  ==> the BUILD ID
     *        "url" : "http://localhost:4236/jenkins/job/JOBNAME/35/"
     *     },
     *  }
     *
     * credit https://stackoverflow.com/a/28524219
     */
    let location = null;
    for (var pair of r.headers.entries()) {
	// seriously, eff this language
	// https://stevemiller.dev/2019/getting-response-headers-with-javascript-fetch/
	// and thank you, Steve
	console.log(`js_runner_jenkins_schedule(${runner}, ${targetid}): header ${pair[0]} is ${pair[1]}`)
	if (pair[0] == "location") {
	    location = new URL(pair[1]);
	    break;
	}
    }

    console.log(`js_runner_jenkins_schedule(${runner}, ${targetid}): build call yielded location ${location}`)
    if (!location) {
	alert(`Jenkins ${pipeline}: can't start run, API returned no location`
	      + "--(1) are you logged in to Jenkins?"
	      + " (2) does Jenkins permit the user logged in as to launch builds?"
	      + " (3) is CORS in Jenkins configured to expose the 'location' header?")
	return
    }

    // if it is in the quiet period we have no buidl ID, so this has
    // to loop until that happens
    console.log(`js_runner_jenkins_schedule: build call yielded2 ${location}`);
    let count = 0, top = 60;
    while(true) {
	/* loop for a max */
	count += 1;
	if (count >= top) {
	    alert(`Jenkins ${targetid} ${pipeline}: waited too long to get`
		  + "a build number; overloaded");
	    js_runner_ui_state_set(runner, "READY")
	    js_runner_run_button_enable(runner, `jenkins ${pipeline} timed out getting build ID`)
	    r = await js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, null)
	    return
	}
	/* sleep some */
	await new Promise(r => setTimeout(r, 1000));	// 1s im ms
	/* query the queue info */
	r = await jenkins_fetch(`${location.protocol}//${location.host}`, location.pathname + "/api/json", "GET");
	const data = await r.json()
	const data_executable = data['executable'] ?? null;
	/* does it have executable info? this means build started */
	if (data_executable == null) {	// still not scheduled
	    console.log(`js_runner_jenkins_schedule(${runner}, ${targetid}, ${pipeline}:`
			+ ` no Jenkins queue executable data`)
	    continue
	}
	build_id = data_executable['number'] ?? null;
	if (build_id == null) {	// still not scheduled
	    console.log(`js_runner_jenkins_schedule(${runner}, ${targetid}, ${pipeline}:`
			+ ` no build ID in Jenkins queue executable data`)
	    continue
	} else {
	    /* we have a build info, yay */
	    console.log(`js_runner_jenkins_schedule(${runner}, ${targetid}, ${pipeline}:`
			+ ` found build ID ${build_id}`)
	    console.log(`js_runner_jenkins_schedule: found build ID is ${build_id}`)
	    r = await js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, build_id);
	    // this disables the button if the run is going
	    tr_el = _js_runner_build_tbodies_header_tr_make(
		runner, targetid, build_id, "main",
		"START",
		`Execution <a href = "${pipeline}/${build_id}/consoleFull" target="_blank" rel="noopener noreferrer">#${build_id}</a>`);
	    tr_build_header_el.innerHTML = '';
	    tr_build_header_el.appendChild(tr_el);
	    js_runner_jenkins_state_update(runner, targetid, pipeline, file_path);

	    // Now start a background task that every second checks the output from jenkins and
	    return
	}
	/* repeat: we have no build info, try again */
    }
    alert("BUG: js_runner_jenkins_schedule: got out of the loop?")
}



function confirm_dialog(message, confirmlabel, cancellabel = null) {
    /*
      This is like Javascript confirm(), but it detects if we are
      being blocked by the browser due to pop ups stuff and tries to
      remediate by telling the user
     */
    return new Promise((resolve) => {
        // Create dialog elements
        const overlay = document.createElement('div');
        const dialog = document.createElement('div');
        const message_element = document.createElement('p');
        const confirm_button = document.createElement('button');
	let cancel_button;
        if (cancellabel)
	    cancel_button = document.createElement('button');
        const unblock_message = document.createElement('p'); // Instructions for unblocking popups

        // Set styles for overlay
        overlay.style.position = 'fixed';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.zIndex = '1000';

        // Set styles for dialog
        dialog.style.backgroundColor = 'white';
        dialog.style.padding = '20px';
        dialog.style.borderRadius = '8px';
        dialog.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.2)';
        dialog.style.textAlign = 'center';

        // Set message and buttons
        message_element.innerHTML = message;
        confirm_button.textContent = confirmlabel;
        if (cancellabel)
	    cancel_button.textContent = cancellabel;

        // Set styles for buttons
        confirm_button.style.backgroundColor = 'blue';
        confirm_button.style.color = 'white';
        confirm_button.style.border = 'none';
        confirm_button.style.padding = '10px 20px';
        confirm_button.style.margin = '10px';
        confirm_button.style.cursor = 'pointer';
        confirm_button.style.borderRadius = '5px';

        if (cancellabel) {
	    cancel_button.style.backgroundColor = 'red';
            cancel_button.style.color = 'white';
            cancel_button.style.border = 'none';
            cancel_button.style.padding = '10px 20px';
            cancel_button.style.margin = '10px';
            cancel_button.style.cursor = 'pointer';
            cancel_button.style.borderRadius = '5px';
	}

        // Append elements
        dialog.appendChild(message_element);
        dialog.appendChild(confirm_button);
        if (cancellabel)
	    dialog.appendChild(cancel_button);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Handle button clicks
        confirm_button.onclick = function() {
            resolve(true);  // User confirmed
            document.body.removeChild(overlay);
        };

	if (cancellabel) {
	    cancel_button.onclick = function() {
		resolve(false); // User canceled
		document.body.removeChild(overlay);
            };
	};

        // Show unblock message only if dialog is closed without a
        // selection
        overlay.onclick = function(event) {
            if (event.target === overlay) {
                // Simulate blocked dialog
                resolve(null);
                unblock_message.textContent = "Browser's pop-up blocker"
		    + " might be blocking a dialog box; check your browser's"
		    + " popup blocker settings.";
                unblock_message.style.color = 'red';
                dialog.appendChild(unblock_message);
            }
        };
    });
}



async function js_runner_start_or_stop(runner, targetid, allocid) {
    const type = js_runner_field_get(targetid, runner, 'type');

    let r = null;
    if (type == "jenkins") {
	r = await js_runner_jenkins_stop_if_running(runner, targetid, allocid );
    } else
	_js_runner_bad(runner, targetid, type);

    if (r == true)	// it was running, we are done here
	return;

    // it wasn't running, so let's start

    /*
      do we have to confirm before we start?

      Do this here so the browser considers this to be a user-induced
      action and there are less chances of the pop up being blocked
    */
    let confirm_msg = js_runner_field_get(targetid, runner, "confirm");
    if (confirm_msg) {
	r = await confirm_dialog(confirm_msg, "Proceed", "Cancel")
	if (r == null) {
	    console.log(`js_runner_start_or_stop(${runner}, ${targetid}, ${allocid}):`
			+ ` dialog blocked by browser?`);
	    return;
	} else if (r == false) {
	    console.log(`js_runner_start_or_stop(${runner}, ${targetid}, ${allocid}):`
			+ ` cancelled by user on confirm prompt`);
	    return;
	}
    }

    let confirm2_msg = js_runner_field_get(targetid, runner, "confirm2");
    if (confirm2_msg) {
	r = await confirm_dialog(confirm2_msg, "Proceed", "Actually yes, do cancel")
	if (r == null) {
	    console.log(`js_runner_start_or_stop(${runner}, ${targetid}, ${allocid}):`
			+ ` dialog blocked by browser?`);
	    return;
	} else if (!r) {
	    console.log(`js_runner_start_or_stop(${runner}, ${targetid}, ${allocid}):`
			+ ` cancelled by user on confirm2 prompt`);
	    return;
	}
    }

    /* good to go, start it */

    if (type == "jenkins") {
	js_runner_jenkins_start(runner, targetid, allocid);
    } else
	_js_runner_bad(runner, targetid, type);
}



/*
** Return the HTML for the build view toggle button with a tool top --
** gets tricky to embed it as such in the JS call where we use it,
** this is maybe cleaner.
*/
function _js_runner_ui_toggle_button_html(runner, build_id) {
    return '<div class = "tooltip">'
	+ `<button id = "button_id_toggle_hide_${runner}_${build_id}"`
	+ ` toggle_state = "show all"`
	+ ` onclick = "js_runner_table_toggle_hide(\'${runner}\', \'${build_id}\')">👁</button>`
	+ `<span class = "tooltiptext" id = "button_id_toggle_hide_${runner}_${build_id}_tooltip">`
	+ `toggle build ${build_id}'s visibility<ul>`
	+ '</span>'
	+ '</div>';
}



/*
** Toggle the visibility of a build's run information
**
** Called from the button button_id_toggle_hide_${runner}_${build_id} <eye icon>
**
** We store in the button a property called toggle_state that we use
** it to track what we should do. Based on that we go and use
** style.display in the <trs> to hide them or show them. Update the
** tooltip to say what we are currently showing
**
** Note we tell the <trs> for the build because they have a property
** called __filter_{runnername}_{buildid}
*/
async function js_runner_table_toggle_hide(runner, build_id) {
    /* locate the table */
    let button_el = null;
    let button_tooltip_el = null;
    let tbody = null;
    tbody = document.getElementById(`label_id_runner_${runner}_build_${build_id}_data`);
    button_el = $(`#button_id_toggle_hide_${runner}_${build_id}`);
    button_tooltip_el = $(`#button_id_toggle_hide_${runner}_${build_id}_tooltip`);
    let trs = tbody.getElementsByTagName('tr');
    let current_state = null;

    /* we check the target state based on the button's toggle_state property
     *
     * show all -> hide passes -> hide build
     */
    current_state = button_el.attr('toggle_state');
    if (current_state == "show all") { 	// move to "hide passes"
	console.log(`js_runner_table_toggle_hide(${runner}, ${build_id}):`
		    + " moving from 'show all' to 'hide passes'");
	// hide all TRs that report non-issue info
	for (var i = 0; i < trs.length; i++) {
	    let tr = trs[i];
	    // hide all the TRS that report non-issues
	    let tr_attr = tr.getAttribute(`__filter_${build_id}`, null)
	    if (tr.getAttribute(`__filter_${build_id}`, null) == "1")
		tr.style.display = "none";
	}
	button_el.attr('toggle_state', "hide passes");
	button_tooltip_el.empty();
	button_tooltip_el.append(
	    `toggle build ${build_id}'s visibility.<br><br>`
		+ " Currently hiding passes, showing only issues"
		+ " (if you see nothing, means nothing failed).");
    } else if (current_state == "hide passes") { 	// move to "hide build"
	console.log(`js_runner_table_toggle_hide(${runner}, ${build_id}):`
		    + " moving from 'hide passes' to 'hide build'");
	tbody.style.display = "none";
	button_el.attr('toggle_state', "hide build");
	button_tooltip_el.empty();
	button_tooltip_el.append(
	    `toggle build ${build_id}'s visibility.<br><br>`
		+ " Currently hiding all build output.");
    } else if (current_state == "hide build") { 	// move to "show all"
	console.log(`js_runner_table_toggle_hide(${runner}, ${build_id}):`
		    + " moving from 'hide build' to 'show all'");
	tbody.style.display = "";    // show the build
	// show all the TRS for this build
	for (var i = 0; i < trs.length; i++) {
	    let tr = trs[i];
	    // each tr that we need to toggle has a tag called tag_filter_id `${build_id}-hide`
	    if (tr.hasAttribute(`__filter_${build_id}`))
		tr.style.display = "";
	}
	button_el.attr('toggle_state', "show all");
	button_tooltip_el.empty();
	button_tooltip_el.append(
	    `toggle build ${build_id}'s visibility.<br><br>`
		    + " Currently showing all build output.");
    }
}



function _js_runner_build_tbodies_header_tr_make(
    runner, targetid, build_id, build_name,
    status = "DONE",
    description = null) {
    const pipeline = js_runner_field_get(targetid, runner, 'pipeline');
    const tr_el = document.createElement('tr');
    tr_el.setAttribute(         // set the build header row background to
	'bgcolor', '#e0e0e0');	//  light gray so they are easy to find

    let td_el = document.createElement('td');
    td_el.insertAdjacentHTML(		// FIXME: tooltip with the TC
	'afterbegin',
	`<code>${status}</code>`);	// count, PASS/FAIL/ERRR/SKIP/BLCK
    tr_el.appendChild(td_el);

    td_el = document.createElement('td');
    // FIXME: rename ui_toggle to build_ui_toggle
    td_el.insertAdjacentHTML('afterbegin',
			     _js_runner_ui_toggle_button_html(runner, build_name));
    tr_el.appendChild(td_el);

    td_el = document.createElement('td');
    if (description == null) {
	// FIXME: jenkins hardcode!
	description = `Execution <a href = "${pipeline}/${build_id}/consoleFull" target="_blank" rel="noopener noreferrer">#${build_id}</a>`;
    }
    td_el.insertAdjacentHTML('afterbegin', description);
    tr_el.appendChild(td_el);	
    return tr_el
}



function _js_runner_build_tbodies_add(runner, targetid, build_id, table_el) {
    const pipeline = js_runner_field_get(targetid, runner, 'pipeline');
    let tbody_el = document.createElement('tbody');
    tbody_el.setAttribute("id", `label_id_runner_${runner}_build_${build_id}_header`);
    let tr_el = _js_runner_build_tbodies_header_tr_make(runner, targetid, build_id, build_id);
    tbody_el.appendChild(tr_el);
    table_el.appendChild(tbody_el);

    let tbody_data_el = document.createElement('tbody');
    tbody_data_el.setAttribute(
	'id', `label_id_runner_${runner}_build_${build_id}_data`);
    table_el.appendChild(tbody_data_el);
    return [ tbody_el, tbody_data_el ];
}


/*
  Add a row of data to a build
 */
function _js_runner_build_tbodies_data_add(
    // build_id is a number, build_name is a name -- can be the same
    // (build 95) for historical ones, but for the last one, build ID
    // could be 32, but build_name would be "main" -- we use that to
    // tag the elements that we might have to hide later with
    // js_runner_table_toggle_hide()
     build_name, tbody_data_el,
    result, timestamp, tc_name) {

    let tr_el = document.createElement('tr');
    // js_runner_table_toggle_hide() uses this to show only failures
    if (result.includes("failure=1"))
	tr_el.setAttribute(`__filter_${build_name}`, 0);
    else
	tr_el.setAttribute(`__filter_${build_name}`, 1);
    tr_el.insertAdjacentHTML('afterbegin',
			     `<td}>${result}</td>`
			     + `<td>+${timestamp} min</td>`
			     + `<td>${tc_name}</td>`);
    tbody_data_el.appendChild(tr_el);
}



async function js_runner_previous_builds_off(runner, targetid) {
    /* just delete the previous history entries, _on() will re-query
     * the DB and recreate them */
    const table_el = document.getElementById(`label_id_runner_${runner}_table`);
    for (let i = 0; i < table_el.children.length; i++) {
	let el = table_el.children[i];
	// from js_runner_build_tbodies_add -- don't remove the
	// entries for the main build!
	if (el.id.startsWith(`label_id_runner_${runner}_build_`)
	    && ! el.id.startsWith(`label_id_runner_${runner}_build_main`))
	    el.remove();	
    }
    console.log(`js_runner_find_old_builds(${runner}, ${targetid}): cleaned old builds`);
}



async function js_runner_previous_builds_on(runner, targetid) {
    /*
      Query the datase and create entries for each build and on each
      build, data about the run, deleting any previous info we might
      have

      For each build we add two tbodies, one for header, one for data;
      they have labels and the hide button is tide to hiding the data
      section.
    */
    console.log(`js_runner_find_old_builds(${runner}, ${targetid}):`);

    const pipeline = js_runner_field_get(targetid, runner, 'pipeline');
    const file_path = js_runner_field_get(targetid, runner, 'file_path');
    const repository = js_runner_field_get(targetid, runner, 'repository');

    const mongo_url = js_runner_field_get(targetid, runner, 'mongo_url');
    const mongo_db = js_runner_field_get(targetid, runner, 'mongo_db');
    const mongo_collection = js_runner_field_get(targetid, runner, 'mongo_collection');

    if (mongo_url == null) {
	alert("Configuration needed! target needs to declare MongoDB URL"
	      + `runner.${runner}.mongo_url to pull old builds`)
	return;
    }

    if (mongo_db == null) {
	alert("Configuration needed! target needs to declare MongoDB URL"
	      + `runner.${runner}.mongo_db to pull old builds`)
	return;
    }

    if (mongo_collection == null) {
	alert("Configuration needed! target needs to declare MongoDB URL"
	      + `runner.${runner}.mongo_collection to pull old builds`)
	return;
    }

    // in the databae, this will be recorded is $(basename
    // $repository)/$file_path. Eg
    //
    // https://github.com/prefix/project.git/some/path/something.py
    //
    // in the DB is: project.git/some/path/something.py
    //
    // So let's fix that
    const repo_url = new URL(repository);
    const repo_pathname_parts = repo_url.pathname.split("/");
    const basename = repo_pathname_parts[repo_pathname_parts.length - 1];
    // FIXME: not quite like this, since if file_path starts with
    // /...but I can't find an equivalent of os.path.join()
    const tc_name = basename + "/" + file_path;

    const params = {
	//mongourl: encodeURIComponent('mongodb://USERNAME:PASSWORD@HOSTNAMEREPLICA1:7764,HOSTNAMEREPLICA2:7764,.../DBNAME?ssl=true&replicaSet=REPLICANAME'),
	mongourl: encodeURIComponent(mongo_url),
	dbname: encodeURIComponent(mongo_db),
	collection: encodeURIComponent(mongo_collection),
	// FIXME: pass just the hostname until we fix these records to
	// include the full URL
	server: encodeURIComponent(ttbd_server_url.hostname.split(".")[0]),
	targetid: encodeURIComponent(targetid),
	tc_name: encodeURIComponent(tc_name),
    }

    // we have configured in the ttbd server a bridge to MongoDBs so
    // we can do the query to get data; FIXME: document data schema
    let r = await fetch("/mongo_build_query?" + new URLSearchParams(params).toString(), {
	method: 'GET',
	credentials: "include",
    });
    const data = await r.json();
    console.log(`js_runner_find_old_builds(${runner}, ${targetid}): got data`);

    /* clean the old builds */
    js_runner_previous_builds_off(runner, targetid);

    // JSON in fetch muddles up the sorting...
    let build_ids = Object.keys(data)
    build_ids.sort(( a, b ) => {
	// custom sort so we can also sort numbers properly
	const a_number = parseFloat(a);
	const a_is_number = !isNaN(a_number);
	const b_number = parseFloat(b);
	const b_is_number = !isNaN(b_number);

	if (a_is_number && b_is_number)
            return a_number - b_number;	// both numbers, num sort
	else if (a_is_number)
            return -1;			// a number, comes first
	else if (b_is_number)
            return 1;			// b number, comes second
	else
            return a.localeCompare(b);	// neither numbers, compar alpha
    });
    build_ids.reverse()
    let table_el = document.getElementById(`label_id_runner_${runner}_table`);
    for (let i in build_ids) {
	// look, I am sure there is a better way to do this, but swear
	// I didn't find it. I dislike Javascript with a
	// passion. Y de este burro no me bajo.
	let build_id = build_ids[i];
	let build_data = data[build_id];

	let [ tbody_el, tbody_data_el ] = _js_runner_build_tbodies_add(
	    runner, targetid, build_id, table_el);

	tbody_data_el.style.display = "none"; // start with build rows hidden
	let button_hide_toggle_el = $(`#button_id_toggle_hide_${runner}_${build_id}`);
	button_hide_toggle_el.attr('toggle_state', "hide build");
	let ts0 = null;
	for (let i in build_data) {
	    let [timestamp, result, tc_name, runid_hashid] = build_data[i];
	    // this data already comes sorted, so no need to rethink
	    // the sorting
	    if (ts0 == null)
		ts0 = timestamp;

	    // This is very TCF specific, but it is quite hard to move
	    // to the inventory :/ the background_CODE is defined in
	    // widget-target-runner.html -- failure=1 is to enable filtering
	    if (result == "ERRR" || result == "BLCK"
		|| result == "FAIL" || result == "SKIP") {
		result = `<div class = "background_${result}">
      <a href = "${pipeline}/${build_id}/artifact/report-${runid_hashid}.txt" target="_blank" rel="noopener noreferrer">
        <code>${result}</code><!--failure=1-->
      </a>
    </div>`;
	    } else {
		result = `<div class = "background_${result}"><code>${result}</code></div>`;
	    }
	
	    timestamp -= ts0
	    _js_runner_build_tbodies_data_add(
		build_id, tbody_data_el,
		result, timestamp.toFixed(0), tc_name);
	}
    }
    return r;
}



async function js_runner_previous_builds_toggle(runner, targetid) {

    let table_main_control_el = document.getElementById(`label_id_runner_${runner}_table_main_control`);
    /* do one attr per build, to simplify not havig to clean it up */
    let show_history = table_main_control_el.getAttribute(`show_history`);
    if (show_history == "true") {
	console.log(`js_runner_find_old_builds(${runner}, ${targetid}): hiding old builds`);
	let show_history = table_main_control_el.setAttribute(`show_history`, "false");
	js_runner_previous_builds_off(runner, targetid)
    } else {
	console.log(`js_runner_find_old_builds(${runner}, ${targetid}): showing old builds`);
	let show_history = table_main_control_el.setAttribute(`show_history`, "true");
	js_runner_previous_builds_on(runner, targetid)
    }
}
