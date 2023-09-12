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
async function js_alloc_remove(allocid) {
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
*
* return {void}
*/
async function power(targetid, action, component) {
    $('.diagnostics').empty();
    $('#loading').append(
        '<label>powering ' + action + ': ' + component+ '</label><progress id="progress-bar" aria-label="Content loading…"></progress></div>'
    );

    // https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/power/on
    let data = new URLSearchParams();

    if (component != 'all') {
        data.append('component', component);
    }

    let r = await fetch('/ttb-v2/targets/' + targetid + '/power/' + action, {
        method: 'PUT',
        body: data,
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (!r.ok) {
        alert(
            'something went wrong: ' + b
        );
        $('#loading').empty();
        $('#loading').append(
            '<b><label style="color: red;">FAIL</label></b>'
        );
        window.location.reload();
        return
    }


    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}


/*
 * make a button call given an action and a component
 *
 * FIXME: this iss exactly the same as for power; refactor adding an interface name
 *
 * @param {targetid} str -> target for performing power action
 * @param {action} str -> on/off/cycle, action you want to perform
 * @param {component} str -> component we want to perform the action onto
 *
 * return {void}
 */
async function js_buttons(targetid, action, component) {
    $('.diagnostics').empty();
    $('#loading').append(
        '<label>powering ' + action + ': ' + component+ '</label><progress id="progress-bar" aria-label="Content loading…"></progress></div>'
    );

    // https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/buttons/on
    let data = new URLSearchParams();

    if (component != 'all') {
        data.append('component', component);
    }

    let r = await fetch('/ttb-v2/targets/' + targetid + '/buttons/' + action, {
        method: 'PUT',
        body: data,
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (!r.ok) {
        alert(
            'something went wrong: ' + b
        );
        $('#loading').empty();
        $('#loading').append(
            '<b><label style="color: red;">FAIL</label></b>'
        );
        window.location.reload();
        return
    }


    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}

function common_error_check(r) {

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return true
    }

    if (!r.ok) {
        alert(
            'something went wrong: ' + response_text
        );
        $('#loading').empty();
        $('#loading').append(
            '<b><label style="color: red;">FAIL</label></b>'
        );
        window.location.reload();
        return true
    }

    return false
}


/*
* Remove a guest from an allocation
*
* @param {allocid} str -> allocation from which to remove the guest
* @param {selector_id} str -> select tag html id which selected the user
*
* return {void}
*/
async function js_alloc_guest_add(allocid, input_field_id) {

    $('.diagnostics').empty();

    // the selector_id element in the HTML document has picked up something
    let input_field_item = document.getElementById(input_field_id);
    console.log('DEBUG 1')
    if (input_field_item == null) {
        // this means do nothing
        return
    }
    console.log('DEBUG 2')
    let user_name = input_field_item.value;

    console.log('DEBUG user_name is ' + user_name)

    let r = await fetch('/ttb-v2/allocation/' + allocid + '/' + user_name, {
        method: 'PATCH',
    });

    if (common_error_check(r)) {
        return
    }

    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}


/*
* Remove a guest from an allocation
*
* @param {allocid} str -> allocation from which to remove the guest
* @param {selector_id} str -> select tag html id which selected the user
*
* return {void}
*/
async function js_alloc_guest_remove(allocid, selector_id) {

    $('.diagnostics').empty();

    // the selector_id element in the HTML document has picked up something
    let selected_item = document.getElementById(selector_id);
    if (selected_item == null) {
        // this means do nothing
        return
    }
    let user_name = selected_item.value;

    if (user_name.value == 'None') {
        // this means do nothing
        return
    }

    let r = await fetch('/ttb-v2/allocation/' + allocid + '/' + user_name, {
        method: 'DELETE',
    });

    if (common_error_check(r)) {
        return
    }

    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}



/*
* make a flashing call given a version and an image type
*
* @param {targetid} str -> target id to which you want to flash
* @param {select_id} str -> select tag html id where the paths for flashing are
* @param {image_type} str ->  the type of firmware you want to flash, if you
*   want to flash multiple you can separate them by `:`
*   Ex. fw:bios:ifwi:
* @param {suffix} str ->  suffix, if any, of the image files name names , you
*   can send multiple separated by `:`
*   Ex. ::.img:
*
* return {void}
*/
async function js_images_flash(targetid, select_id, image_type, suffix) {

    // jquery does not like dots in ids, we need to escape them
    select_id = select_id.replace('.', '\\.');

    let selected = document.getElementById(select_id);
    let fullpath = selected.value;
    $('#loading').append(
        '<label>flashing ' + image_type + ': ' + fullpath + '</label><progress id="progress-bar" aria-label="Content loading…"></progress></div>'
    );

    let images = new Object();
    if (select_id != 'flash_images_version_for_all') {
        images[image_type] = fullpath;
    } else {
        // flashing multiple images bios:fw:smth:
        const imgs = image_type.split(':');
        const suffixes = suffix.split(':');
        imgs.pop()
        suffixes.pop()

        let i = 0;
        imgs.forEach((img_type) => {
            images[img_type] = fullpath + img_type + suffixes[i];
            i++;
        });
    }

    images = JSON.stringify(images);

    let data = new URLSearchParams();
    data.append('images', images);

    // https://<SERVER>:5000/ttb-v2/targets/<TARGET NAME>/images/flash
    //  -X PUT-d images='{"bios":"bios.xz"}'
    let r = await fetch('/ttb-v2/targets/' + targetid + '/images/flash', {
        method: 'PUT',
        body: data,
    });

    let response_text = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (!r.ok) {
        alert(
            'something went wrong: ' + response_text
        );
        $('#loading').empty();
        $('#loading').append(
            '<b><label style="color: red;">FAIL</label></b>'
        );
        window.location.reload();
        return
    }


    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

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


/**
 * make inventory dialog appear
 *
 * @return {void}
 */
function show_inventory() {
    const inventory = document.getElementById('inventory');
    inventory.showModal();
}
