"use strict";

/*
* make an http request to make an allocation for the current user
*
* @param {targetid} str -> target to acquire
*
* return {void} -> it reloads the windows though
*/
async function acquire(targetid) {
    let r = await fetch('/ttb-v2/allocation', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
            'groups': {
                targetid: [targetid]
            },
            'queue': true,
            "endtime": 'static',
      })
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (r.status != 200) {
        alert(b);
        return
    }

    window.location.reload()
}

/*
* releases target based on an allocation id
*
* @param {allocid} str -> allocation id that you want to remove
*
* return {void} -> it reloads the windows though
*/
async function release(allocid) {
    let r = await fetch('/ttb-v2/allocation/' + allocid, {
      method: 'DELETE',
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (r.status != 200) {
        alert(b);
        return
    }

    window.location.reload()
}

/*
* make a power call given an action and a component
*
* @param {targetid} str -> target for performing power action
* @param {action} str -> on/off/cycle, action you want to perform
* @param {component} str -> component we want to perform the action onto
*/
async function power(targetid, action, component) {
    //TODO
    window.location.reload()
}

/**
 * toggle visibilty of div
 *
 * modify html element by id, switching the display tag to either, show the
 * element or hide it.
 *
 * @param {id} var      id of element you want to toggle.
 *
 * @return {void}
 */
function toggle(id) {
    let inv  = document.getElementById(id);
    if (inv.style.display === "none") {
        inv.style.display = "block";
        return;
    }
    inv.style.display = "none";
}
