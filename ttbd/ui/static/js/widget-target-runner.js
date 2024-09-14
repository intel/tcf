"use strict";

/*
 * Deployment info:
 *
 *  - created job cv-widget-runner
 *
 *  - setup CORS in jenkins FIXM
 *
 * FIXME:
 * - move runner info to a variable in the widget for easy acces for regexs for log
 * - toggle run button to kill the build -- debug state
 * - fixme: ensure log pull function can run only once
 * - where do we store the auth credential? how do we access it?
 * - ensure all values from invenroy are sanitized to basic text so there is no HTML crashes
 * - set runner.*.build_id to user setable
 * - can we tag the build in jenkins with the targetid and the manifest so we can search which one like that are running and cleanup?
 * - make the jenkins pipeline allow multiple jobs in parallel
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


/* FIXME how do we fix this */
const auth = 'Basic ' + btoa('inaky:117f2a79266c988e946ce1b49ed2f02a41');



/*
 * Sets the visual state of the runner's status
 *
 * state: a string UNKNOWN | PENDING | RUNNING | READY
 *
 * FIXME: add coloring
 */
function js_runner_ui_state_set(runner, state) {
    $('#label_id_runner__' + runner).empty();
    $('#label_id_runner__' + runner).append(state);
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

async function js_runner_jenkins_build_state_check(pipeline, build_id, auth) {
    let r = await fetch(pipeline + '/' + build_id + '/api/json', {
	headers: {
	    'Authorization': auth,
	},
	// note, mode: no-cors yields no response information, in case you are wondering
        method: 'GET'
    });
    console.log(`js_runner_jenkins_build_state_check: pipeline ${pipeline} build ${build_id} status: ${r.status}`)
    if (r.status != 200) {
	console.log(`js_runner_jenkins_build_state_check: pipeline ${pipeline} build ${build_id} error: ${r.text}`)
        return [ false, false ];
    }
    let data = await r.json()
    let building = data['building'] ?? null;
    let result = data['result'] ?? null;
    console.log(`js_runner_jenkins_build_state_check: DEBUGpipeline ${pipeline} build ${build_id} building=${building} result=${result}`);
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
    html_element.append(html_element.attr('label_original'));
}

function js_runner_run_button_disable(runner, reason) {
    console.log(`js_runner_run_button_set_ready(${runner}, ${reason}): disabling run button`)
    let html_element = $(`#widget-runner-${runner}-run-button`);
    html_element.empty();
    html_element.prop('class', 'warning');
    html_element.empty();
    html_element.append("CANCEL: " + html_element.attr('label_original'));
}


async function js_runner_jenkins_state_update_deferred(
    runner, targetid, pipeline, file_path, build_id) {
    /* sleep some */
    console.log(`js_runner_jenkins_state_update_deferred(${runner}, ${targetid}, ${pipeline}): waiting 1s`)
    await new Promise(r => setTimeout(r, 2000));	// 1s im ms
    console.log(`js_runner_jenkins_state_update_deferred(${runner}, ${targetid}, ${pipeline}): calling 1s`)
    await js_runner_jenkins_state_update(runner, targetid, pipeline, file_path);
}


async function js_runner_jenkins_log_parse(
    runner, targetid, pipeline, build_id, file_path) {
    let html_state_table_el = $(`#label_id_runner_${runner}_table`);
    html_state_table_el.append("<tr><td>checking</td></tr>");
    /* do one attr per build, to simplify not havig to clean it up */
    let console_offset_lines = html_state_table_el.attr(`console_offset_lines-${build_id}`);
    if (console_offset_lines == null)
	console_offset_lines = 0;
    else
	console_offset_lines = parseInt(console_offset_lines);
    /* check on the console output
     *
     * Latch on:
     *

     Prep main container
     
     setup_workspace: RUNID is 20240101-0101-37

     DONE
     tar cvvjf workspace-common.tar.xz etc run

     target container exists

     - Container with hash 6b4485a1a5b63409 already exists, skipping build -> reusing target container

     - kaniko/executor -> building target container

     preparing to run in target container
     - tar xf workspace-common.tar.xz
     - tcf.git/tcf config

     running
     - tcf.git/tcf run
     
    */

    /* get all lines since last count of lines
     *
     * https://plugins.jenkins.io/timestamper/
     */
    console.log(`js_runner_jenkins_log_parse(${runner}, ${targetid}, ${pipeline}, ${build_id}): getting log from line ${console_offset_lines}`)
    const search_params = new URLSearchParams()
    search_params.set("elapsed", "m");			/* elapsed time in minutes */
    search_params.set("appendLog", true);			/* give us log lines */
    search_params.set("startLine", console_offset_lines);	/* only the new ones */
    let r = await fetch(`${pipeline}/${build_id}/timestamps?${search_params.toString()}`, {
	headers: { 'Authorization': auth, },
	method: 'GET',
    });
    let text = await r.text();
    var lines = 0;

    const phase_regexes = {
	// FIXME: move to inventory
	// https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/RegExp
	["container: located image"]: new RegExp("Container with hash .* already exists, skipping build"),
	["container: rebuilding image"]: new RegExp("kaniko/executor"),
	["container: preparing"]: new RegExp("tar xf workspace-common.tar.xz"),
	["container: configuring"]: new RegExp("tcf.git/tcf config"),
	["container: executing"]: new RegExp("tcf.git/tcf run"),
	["completed"]: new RegExp("Finished: "),
	// FIXME: how do we do the running subcase
    }
    /* We also parse TCF summary lines to see testcase and subcase; they look like
     *
     *
     * FAIL0/240906-2036-50-9cajaf applications.infrastructure.capi.tcf-intel.git/testcases/cluster/test_healthcheck_bat.py##150_power_list##serial_BMC_detected @fl31ca303as0507 [+0.0s]: subcase failed
     *
     * <TAG>/<RUNID> TCREPOBASENAME/TCPATH(##SUBCASES) @[SERVER/]SUTNAME [TIMESTAMP]: message
     *
     * can't use spaces just in case but maybe we should oh well
     */
    let tcf_regex = new RegExp(
	"^(PASS|FAIL|ERRR|BLOCK|SKIP|INFO|DATA)([0-9]+)"	// the tag + verbosity level
	    + "/([-0-9a-z]+)"					// the runid
	    + ` +([^\w]+)/${file_path}`				// the testcasename
	    + "(##[-_a-zA-Z0-9#]+)*"				// the subcases
	    + ` @.*(${targetid})`				// the targetid    
	    + " (\\[\\+[\.0-9]+s\\]):"				// the elapsed timestamp
	    + " (.*)$");					// the leftovers

    let m = null;
    let parts = null;
    let elapsed = null;
    let rest = null;
    for (const line of text.split("\n")) {
	console.log(`line ${lines} is ${line}`);
	lines++;
	for (const [phase, regex] of Object.entries(phase_regexes)) {
	    // line is ELAPSEDMINUTES<two spaces>rest of the line
	    parts = line.split("  ", 2);
	    elapsed = parts[0];
	    rest = parts[1];
	    m = regex.exec(rest);
	    if (m != null) {
		// FIXME: colors, URL links
		html_state_table_el.append(
		    "<tr><td><code>FOUND</code></td>"
			+ `<td>+${elapsed}</td><td>${phase}</td></tr>`);
		continue
	    }
	}
	// returns a list of matches
	// REST, TAG, LEVEL, TCPATH, SUBCASES, TARGETID, LEFTOVER
	m = tcf_regex.exec(rest);
	if (m) {
	    // FIXME: verify TCPATH, TARGETID
	    // FIXME: colors, URL links
	    html_state_table_el.append(
		`<tr><td><code>${m[1]}</code></td>`
		    + `<td>+${elapsed}</td>`
		    + `<td>${m[4]}}</td></tr>`);
	}
    }
    console.log(`js_runner_jenkins_log_parse(${runner}, ${targetid}, ${pipeline}, ${build_id}): got ${lines} more lines`)
    console_offset_lines += lines;
    html_state_table_el.attr(`console_offset_lines-${build_id}`, console_offset_lines);

    /* FIXME: we need to figure out how to sequence this function so only one is running at the same time*/
}


async function js_runner_jenkins_state_update(
    runner, targetid, pipeline, file_path, build_id = null) {
    let r = null;
    js_runner_ui_state_set(runner, "PENDING")
    js_runner_run_button_disable(runner, "checking build state")
    if (build_id == null)
	build_id = await js_runner_ttbd_build_id_query(runner, targetid);
    console.log(`js_runner_jenkins_state_update(${runner}, ${targetid}, ${pipeline}): build_id ${build_id}`)
    if (build_id != null) {
	// there is a build declared that was running, let's check status on it
	const [ building, result ] = await js_runner_jenkins_build_state_check(pipeline, build_id, auth)
	if (building) {
	    js_runner_ui_state_set(runner, "RUNNING")
	    js_runner_run_button_disable(runner, `jenkins ${pipeline} running build ${build_id}`);
	    js_runner_jenkins_log_parse(runner, targetid, pipeline, build_id, file_path);
	    js_runner_jenkins_state_update_deferred(runner, targetid, pipeline, file_path, build_id);
	} else if (!building && !result) {
	    // Since this build doesn't exist, just clear it out
	    js_runner_ui_state_set(runner, "READY")
	    js_runner_run_button_enable(runner, `no info for jenkins ${pipeline} build ${build_id}`)
	    r = await js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, null)
	} else {
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


async function js_runner_state_update(
    runner, targetid,
    type, pipeline,
    repository, file_path, notify) {
    if (type == "jenkins") {
	js_runner_jenkins_state_update(runner, targetid, pipeline, file_path);
    } else
	_js_runner_bad(runner, targetid, type);
}



async function js_runner_jenkins_start_or_stop(
    runner, targetid,
    pipeline,
    repository, file_path, notify) {

    /* FIXME: check it is not building */
    let build_id = await js_runner_ttbd_build_id_query(runner, targetid)
    if (build_id != null) {
	/* according to the inventory, we are building; are we done?
	 * query jenkins for info */
	const [ building, result ] = await js_runner_jenkins_build_state_check(pipeline, build_id, auth)
	if (building) {
	    // FIXME: kill it
	    let r = await fetch(pipeline + `/${build_id}/kill`,  {
		headers: {
		    'Authorization': auth,
		},
		method: 'POST',
	    })
	    js_runner_ui_state_set(runner, "READY")
	    js_runner_run_button_enable(runner, `jenkins ${pipeline} build ${build_id} killed`)
	    r = await js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, null)
	    return
	}
	// we are not, we do not clear, so we keep the last build info
	// present
    }
    js_runner_run_button_disable(runner, `jenkins ${pipeline} launchig build`)
    
    // FIXME: get a timestamp -- it's insanely hard in JS
    // const timestamp = new Date().getTime()
    const param_run_timestamp = "20240101-0101";
    // FIXME: make the jenkins user a guest

    /*
     * Launch the Jenkins build, get the build ID
     *
     * Holy cow in a motorbike, this could have been easier
     */
    let r = await fetch(pipeline + '/buildWithParameters',  {
	headers: {
	    'Authorization': auth,
	},
	method: 'POST',
	body: new URLSearchParams({
	    // FIXME: how do we tell the runner not to allocate
	    "param_manifest": `${repository} ${file_path}`,
            "param_run_timestamp": param_run_timestamp,
            // FIXME: add server to qualify "server == '${}' and"`
            "param_capi_sut_filter": `id == \'${targetid}\'`,
	})
    })
    /*
     * the location header has the queue ID
     *
     *   location: https://tcf-jenkins.intel.com/queue/item/80588/
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
     *        "url" : "http://localhost:8666/jenkins/job/morgRemote/35/"
     *     },
     *  }
     *
     * credit https://stackoverflow.com/a/28524219
     */
    let location = null;
    for (const pair of r.headers.entries()) {
	// for I don't know wy, r.headers['location'] ?? null is not getting the value
	if (pair[0] == "location") {
	    location = pair[1];
	    break;
	}
    }
    console.log(`js_runner_jenkins_schedule: build call yielded ${location}`)
    if (!location) {
	alert(`Jenkins ${pipeline}: can't start run, API returned no location`)
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
	r = await fetch(location + "/api/json",  {
	    headers: { 'Authorization': auth, },
	    method: 'GET',
	});
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
	    r = await js_ttbd_target_property_set(targetid, `runner.${runner}.build_ts`, param_run_timestamp);
	    r = await js_ttbd_target_property_set(targetid, `runner.${runner}.build_id`, build_id);
	    // this disables the button if the run is going
	    // FIXME pass build_id?
	    js_runner_jenkins_state_update(runner, targetid, pipeline, file_path);

	    // Now start a background task that every second checks the output from jenkins and 
	    return
	}
	/* repeat: we have no build info, try again */
    }
    alert("BUG: js_runner_jenkins_schedule: got out of the loop?")
}



async function js_runner_start_or_stop(
    runner, targetid,
    type, pipeline,
    repository, file_path, notify) {
    if (type == "jenkins") {
	js_runner_jenkins_start_or_stop(
	    runner, targetid, pipeline, repository, file_path, notify);
    } else
	_js_runner_bad(runner, targetid, type);
}
