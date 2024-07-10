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
            'queue': false, //FIXME show the user the reservation did not queue
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


/*
* make an http request to store the custom fields of a user into their
* secondary DB
*
* @param {custom_fields} str -> comma,separated,values,to,store
*
* return {void} -> on success it creates a green div with a success message on
* the elements with class `.message`
*
*/
async function save_custom_fields(custom_fields_list) {

    let custom_fields_list_joined = custom_fields_list.join(',');

    let r = await fetch('/ttb-v2/ui/targets/customize', {
      method: 'POST',
      headers: {
        'content-type': 'application/json'
      },
      body: JSON.stringify({
        "ui_preferred_fields_for_targets_table": custom_fields_list_joined,
      })
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (r.status != 200) {
        alert(b);
        return
    }

    $(".message").append("<div class='info info-green'>Successfully saved the following fields: <b>" + custom_fields_list_joined +  "</b></div>")

}

/*
* store in secondary db selected (by checkbox) fields.
*
* for selecting the fields the table must have an input tag with the following
* requirements.
* - value shall be the field
* - type shall be set to checkbox
* - they must share the same class
*
*
* @param {checkboxes_class} str -> class all the checkboxes representing the
* checkboxes
*
* return {void}
*/
function js_save_custom_fields(checkboxes_class) {

    let checkboxes = document.getElementsByClassName(checkboxes_class);
    let custom_fields = new Array();

    for (let i = 0; i < checkboxes.length; i++) {
        if (checkboxes[i].checked) {
            custom_fields.push(checkboxes[i].value);
        }
    }
    save_custom_fields(custom_fields);
}

/*
* Given a class, uncheck all the checkboxes found
*
* @param {checkboxes_class} str -> class all the checkboxes representing the
* checkboxes
*
* return {void}
*/
function js_uncheck_all_checkboxes(checkboxes_class) {
    let checkboxes = document.getElementsByClassName(checkboxes_class);
    for (let i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = false;
    }
}

/*
* Given a table object (from DataTables) and an input tag with a pattern as its
* value. Create a new row in that table with the pattern and a checkbox for it
* to be selected
*/
function add_row_to_field_table(table, pattern_input_id) {
    let pattern_input = document.getElementById(pattern_input_id);
    let pattern = pattern_input.value;
    table.row
        .add([
            "<input type='checkbox' id='" + pattern + "' name='" + pattern + "' value='" + pattern + "' class='ui_preferred_fields_for_targets_table' checked/>",
            pattern,
            'Custom Pattern'
        ])
        .draw();
}
