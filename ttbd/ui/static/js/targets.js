"use strict";

/*
* make an http request to make an allocation for the current user
*
* @param {target_list} list -> list of targets id  to acquire, (if you want to
*                               only acquire one, then just make a list of 1
*                               target id.)
*
* return {void} -> it reloads the windows though
*/
async function acquire(target_list) {

    // we need a group id for the allocation, so we do a similar approach to
    // the cli `tcf`, and we just join all the targets id in the reservation
    // with a comma, creating a string like:
    // target1,target2,target3
    let group_id = target_list.join(',');

    let r = await fetch('/ttb-v2/allocation', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
            'groups': {
                group_id: target_list
            },
            'queue': false,
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
* Acquire targets selected with checkboxes.
*
* For selecting the targets the table must have an input tag with the following
* requirements.
* -  value shall be the target id
* -  type shall be set to checkbox
*
* Note that you will only be able to have a one target per checkbox.
*
* @param {checkboxes_class} str -> class all the checkboxes representing
*                                  targets share
*
* return {void}
*/
function js_acquire_selected_targets(checkboxes_class) {

    let checkboxes = document.getElementsByClassName(checkboxes_class)
    let targets = new Array()

    for (let i = 0; i < checkboxes.length; i++) {
        if (checkboxes[i].checked) {
            targets.push(checkboxes[i].value);
        }
    }
    acquire(targets);
}
