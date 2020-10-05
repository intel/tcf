#! /usr/bin/python
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
#
# FIXME: create an object 'bios_c' that can be used to manipulate BIOS
# settings; attach most to it
"""Utilities for manipulating BIOS menus
-------------------------------------

When a BIOS menu can be accessed from the serial console (eg:
Tianocore's EDKII), it usually uses an ANSI Text UI that is quite
ellaborate and complicated to send/expect for.

This is a collection of tools to handle them. Most of this functions
can be used from test scripts to navigate BIOS menus, such as

- :func:`menu_scroll_to_entry`
- :func:`menu_dig_to`
- :func:`main_menu_expect`
- :func:`main_boot_select_entry`
- :func:`boot_efi_shell` or :func:`boot_network_pxe` or
  :func:`boot_network_http`

All funcions will raise :exc:tcfl.tc.error_e if they cannot find what
is expected at any time. In some cases they will try to recover but
will give up after a certain number of tries.

.. _biosl_ansi_shortref:

ANSI short reference
^^^^^^^^^^^^^^^^^^^^

A string such as::

  ^[[1m^[[37m^[[40m^[[1m^[[37m^[[40m^[[02;03HEFI Shell

(where *^[* is the escape character, hex 0x1b) means:

- *^[[X;YH* means put this in X,Y
- *^[[1m* means bold (*^[[0m* means normal display)
- *^[[37m* means white foreground
- *^[[40m* means black background
- *^[[46m* means cyan background

Depending on the types of BIOS menus, in general when an entry is
highlighted, it is printed in:

- bold on white foreground black background::

    ^[[0m^[[37m^[[40m^[[1m^[[37m^[[40m^[[02;03HENTRY

- bold on white foregound, blue background

- ...

We can use regular Python expressions, such as::

  \\x1b[1m\\x1b\[37m\\x1b\[40m\\x1b\[[0-9]+;[0-9]+HLaunch EFI Shell

References:

- formatting:

  - https://en.wikipedia.org/wiki/ANSI_escape_code
  - https://bluesock.org/~willkg/dev/ansi.html

- keys:

  - https://invisible-island.net/xterm/xterm-function-keys.html

"""
import collections
import numbers
import re
import time

import commonl
import tcfl.tc
import tcfl.tl
import tcfl.pos

# white/grey-background menus
normal_white_fg_black_bg = "\x1b\[0m\x1b\[37m\x1b\[40m"	# highlighted
normal_black_fg_white_bg = "\x1b\[0m\x1b\[30m\x1b\[47m"	# normal
# blue background menus
bold_white_fg_cyan_bg =    "\x1b\[1m\x1b\[37m\x1b\[46m"	# highlighted
normal_white_fg_blue_bg =  "\x1b\[0m\x1b\[37m\x1b\[44m" # normal

ansi_key_codes = {
    'F2': {
        "\x1b[12~": [ "rxvt", "xterm" ],
        "\x1bOQ": [ 'vt100' ],
    },
    'F6': {
        "\x1b[17~": [ "rxvt", "xterm", 'vt100' ],
    },
    'F7': {
        "\x1b[18~": [ "rxvt", "xterm", 'vt100' ],
    },
    'F10': {
        "\x1b[21~": [ "rxvt", "xterm", 'vt100' ],
    },
    'F12': {
        # 24, not 23 :/ https://en.wikipedia.org/wiki/ANSI_escape_code#Terminal_input_sequences
        "\x1b[24~": [ "rxvt", "xterm", 'vt100' ],
    },
}

class unknown_key_code_e(Exception):
    pass

def ansi_key_code(key, term):
    """
    Translate a human known key code to an ANSI sequence

    :param str key: key name (eg: F2, F6, F10...)

    :param str term: terminal type (*rxvt*, *xterm*, *vt100*...)

    :return str: ANSI sequence for that key in that terminal
    """
    assert isinstance(key, str)
    assert isinstance(term, str)

    if key not in ansi_key_codes:
        return key
    key_map = ansi_key_codes[key]
    for seq, terms in key_map.items():
        if term in terms:
            return seq
    raise unknown_key_code_e("unknown key code %s for term %s"
                             % (key, term))

def entry_select(target, wait = 0.5):
    # sometimes it needs to wait a wee bit for the menu to settle; so
    # do it here
    # in the future this will include more things, BIOS specific, to
    # select entries
    time.sleep(wait)
    target.console_tx("\r")

def menu_scroll_to_entry(
        target, entry_string, has_value = False,
        max_scrolls = 30, direction = "down",
        highlight_string = normal_white_fg_black_bg,
        normal_string = normal_black_fg_white_bg,
        level = "top", column_key = 4,
        timeout = 10):
    """Scroll in an ANSI menu until the entry is highlighted

    Menus have two type of entries:

    1. **Submenu**: named *ENTRY* takes you to a submenu with a title
       bar *ENTRY*

       - when selected: highlit with *^[[0m^[[37m^[[40m^[[05;04HENTRY*
       - when not selected: with *^[[0m^[[30m^[[47m^[[05;04HENTRY*

    2. **Settable key/values**: two columns with a *KEY* on the left
       and a *VALUE* on the right; when selected, the *VALUE* is
       highlighted, not the key (confusing); comes as::

         ^[[0m^[[37m^[[40m^[[05;31HVALUE
         ^[[0m^[[30m^[[47m^[[05;40H                  [SPACES]
         ^[[05;01H   [SPACES]
         ^[[05;04HKEY

       really messy to track, so we need to lock in the highlight color
       string, trap the value, lock in the normal color string, lock in
       the key.

    So we fiest lock on the highlight string, extract if it could be a
    submenu or a key/value

    Look at :ref:`ANSI sequences <biosl_ansi_shortref>` for info on
    ANSI sequences.

    Limitations:

    - multiline entries and/or values cannot be easily matched, match
      only to the last line of either.


    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param str entry_string: entry being search. This can be a
      non-compiled Python regular string, but limit it to simple
      without ANSI sequences; eg::

        MAC:(?P<macaddr>[0-0A-Za-z:]+)

    :param bool has_value: (optional; default *False*) the entry in the
      menu is a key/value entry (which are displayed differently).

    :param int max_scrolls: (optional; default *30*) how many times to
      scroll in the menu before giving up if we don't find the entry

    :param str direction: (optional; default *down*) what key to
      press, *up* or *down*.

    :param str highlight_string: sequence that prefixes an entry being
      highlighted; defaults to ANSI normal (non bold), white
      foreground, black background::

        \\x1b[0m\\x1b\[37m\\x1b\[40m


    :param str normal_string: (optional) sequence that prefixes an
      entry not highlighted; defaults to ANSI normal, black
      foreground, white background::

        \\x1b[0m\\x1b\[30m\\x1b\[47m

    :param str level: (optional; defaults to *top*): the name of the
      level we are working on.

    :param int timeout: (optional; defaults to *10*) seconds to wait
      for an expected output, otherwise we retry.

    :returns dict: None if the entry is not found; otherwise a
      dictionary with values found in the text from the regular
      expressions:

      - *row*: row where the entry was printed
      - *column_key*: column where the entry was printed
      - *column_value*: column where the value was printed (if
         *has_value* is *True*)
      - *value*: value printed (if *has_value* is *True*)

      if the *entry_string* contained groups such as::

        MAC:(?P<macaddr>[0-0A-Za-z:]+)

      this would also include an entry called *macaddr*
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(entry_string, str)
    assert isinstance(has_value, bool), \
        "has_value: expected bool; got %s: %s" % (type(has_value), has_value)
    assert isinstance(max_scrolls, int) and max_scrolls > 0
    assert isinstance(highlight_string, str)
    assert isinstance(normal_string, str)
    assert direction in [ 'up', 'down' ]
    assert isinstance(level, str)
    assert isinstance(timeout, int) and timeout > 0

    if direction == 'up':
        _direction = True
    else:
        _direction = False

    target.report_info("BIOS:%s: scrolling to '%s'" % (level, entry_string),
                       dlevel = 1)
    # FIXME: thus should not have the entry_string, gets repetitive
    name = "BIOS:%s/%s" % (level, entry_string)
    # FIXME: This won't work when we have multi line values in key/values
    # :/ latch on the first line of the entry and be happy with
    # it... but we'll loose the value on multiline values
    if has_value:
        # takes care of (2) in the function doc
        selected_regex = re.compile(
            highlight_string.encode('utf-8')
            + b"\x1b\[(?P<row>[0-9]+);(?P<column_value>[0-9]+)H"
            # value is anything that is not an ANSI escape char
            + b"(?P<value>[^\x1b]+)"
            # the rest for us is fluf until the entry name(key) comes
            + normal_string.encode('utf-8')
            # not sure if these two space sequences are optional
            # note we force with (?P=row) that they are all in the
            # same column; this will cause problem for multiline
            # entries...
            + b"\x1b\[(?P=row);[0-9]+H\s+"
            + b"\x1b\[(?P=row);[0-9]+H\s+"
            + b"\x1b\[(?P=row);(?P<column_key>[0-9]+)H"
            # Some entries do start with a space, but it is not *all* spaces
            + b"(?P<key>[^\x1b]*[^ \x1b][^\x1b]*)")
    else:
        # takes care of (1) in the function doc
        selected_regex = re.compile(
            # This won't work when we have multi line values in key/values
            # :/
            highlight_string.encode('utf-8')
            + b"\x1b\[(?P<row>[0-9]+);(?P<column_key>[0-9]+)H"
            # Some entries do start with a space, but it is not *all*
            # spaces; they might finish with a string of spaces, but
            # definitely in a escape sequence
            + b"(?P<key>[^\x1b]*[^ \x1b][^\x1b]*) *\x1b")

    entry_regex = re.compile(entry_string.encode('utf-8'))
    seen_entries = collections.defaultdict(int)
    last_seen_entry = None
    last_seen_entry_count = 0
    # we have either a bug or a feature, not clear and we miss the
    # first line that has the first entry selected; so the first time
    # we just go back and go fo
    first_scroll = True
    for _ in range(max_scrolls):
        if first_scroll != True:
            if _direction:
                # FIXME: use get_key() -- how do we pass the terminal encoding?
                target.console_tx("\x1b[A")			# press arrow up
            else:
                target.console_tx("\x1b[B")			# press arrow down
        else:
            if _direction:
                # FIXME: use get_key() -- how do we pass the terminal encoding?
                target.console_tx("\x1b[B")			# press arrow up
            else:
                target.console_tx("\x1b[A")			# press arrow down
            first_scroll = False

        skips = 4
        while skips > 0:
            skips -= 1
            target.report_info(
                # FIXME: make column a part of the BIOS menu profile
                "%s: waiting for highlighted entry on column %s"
                % (name, column_key), dlevel = 1)
            # read until we receive something that looks like an entry
            # selected
            try:
                r = target.expect(selected_regex, name = name,
                                  # don't report much, it's kinda
                                  # useless and we can get super huge
                                  # lines? FIXME: make it a config option
                                  #report = 0
                                  # if we don't get it in ten seconds,
                                  # bad--fail quick so we retry
                                  timeout = timeout)
            except tcfl.tc.failed_e as e:
                # FIXME: use _timeout_e from target_c's expect(), make
                # it more official
                if 'timed out' not in str(e):
                    raise
                target.report_info("%s: timed out, trying again %d"
                                   % (name, skips), dlevel = 1)
                # sometimes these are caused by bad serial lines,
                # with key characters missed, so we just try to
                # scroll up and try again; we don't try to go up and
                # down because it confuses the state machine.
                skips += 0.5
                if _direction:
                    # FIXME: use get_key() -- how do we pass the terminal encoding?
                    target.console_tx("\x1b[B")			# press arrow up
                else:
                    target.console_tx("\x1b[A")			# press arrow down
                continue
            # the key always matches spaces all the way to the end, so it
            # needs to be stripped
            key = r[name]['groupdict']['key'].strip()
            key_at_column = int(r[name]['groupdict']['column_key'])
            # entries are always on column four (FIXME: BIOS profile)
            if key_at_column == column_key:
                break
            # this might be another false negative we hit (like the
            # drawing of parts at the bottom in highlight), so let's retry
            target.report_info("%s: found non-interesting entry '%s' @%s"
                               % (name, key, column_key))
            continue
        else:
            target.report_info(
                "%s: didn't find an interesting entry after four tries"
                % name, dlevel = 1)
            return None

        target.report_info("%s: found highlighted entry '%s' @%s"
                           % (name, key, column_key), dlevel = 1)
        seen_entries[key] += 1
        if all(seen_count > 3 for seen_count in seen_entries.values()):
            target.report_info("%s: scrolled twice through all entries;"
                               " did not find '%s'"
                               % (name, entry_string), dlevel = 1)
            return None
        if last_seen_entry == key:
            last_seen_entry_count += 1
        else:
            last_seen_entry = key
            last_seen_entry_count = 1
        if last_seen_entry_count > 2:
            # make sure this count is lower then the one above for
            # seen_entries; we might not have seen all the entries in
            # the menu and have a limited count to make a judgement on
            # maybe this is a menu that does not wrap around, flip the
            # direction
            _direction = not _direction
        m = entry_regex.search(key)
        if m:
            target.report_info("%s: highlighted entry found" % name)
            r[name]['groupdict'].update(m.groupdict())
            return r[name]['groupdict']
        target.report_info("%s: found highlighted entry '%s'; not '%s'"
                           "--scrolling"
                           % (name, key, entry_string), dlevel = 1)
    return None


def menu_dig_to(
        target, entries,
        # FIXME: move to BIOS profile
        canary_end_menu_redrawn = "F10=Save Changes and Exit",
        highlight_string = normal_white_fg_black_bg,
        dig_last = True,
        level = "top"):
    """Dig all the way down a list of nested menus

    Given a nested menu hierarchy, select the each entry from the
    given list to navigate into the hierarchy.

    For example, given the hierarchy::

      level1
        level11
        level12
          level121
          level122
          level123
          level124
          level125
          ...
        level13
        level14
          level141
          level142
            level1421
            level1422
              level14221
              level14222
            level1423
          level143
          level144

    the list of entries *[ "level1", "level14", "level142",
    "level1422", "level14221" ]* would take control of the serial
    console to select each menu entry on the way down the hierarchy
    until entry *level14222* is selected.

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param list(str) entries: list of the menu and submenu entries
      that have to be selected. 

      An item can also be a tuple with two or thee entries::

        ( ENTRYNAME, MENUTITLE [, HASVALUE] )

      This is used when the menu tittle for a submenu will be
      different than the entry name; *MENUTITLE* can be *None* if we
      know it is going to be the same and we need to only specify
      *HASVALUE*. 

      *HASVALUE* is a boolean that indicates the entry is a key/value
      entry (see :func:`menu_scroll_to_entry`).

    :param str canary_end_menu_redrawn: (optional) string that is
      printed when the whole menu has been refreshed (and thus marks
      the end of the menu).

    :param str highlight_string: (optional) sequence that prefixes an
      entry being highlighted; defaults to ANSI normal (non bold),
      white foreground, black background::

        \\x1b[0m\\x1b\[37m\\x1b\[40m

    :param bool dig_last: (optional; default *True*) select the last
      menu entry once highlighted.

    :param str level: (optional; default *top*) name of the top level menu

    """
    assert isinstance(target, tcfl.tc.target_c)
    commonl.assert_list_of_types(entries, "entries", "entry",
                                 ( str, tuple))
    assert isinstance(canary_end_menu_redrawn, str)
    assert isinstance(highlight_string, str)
    assert isinstance(dig_last, bool)
    assert isinstance(level, str)

    cnt = 0
    rs = collections.OrderedDict()
    entries_len = len(entries)
    menu_name = [ level ]
    _menu_name =  " > ".join(menu_name)
    while cnt < entries_len:
        # Ok, time to scroll till the next one
        entry_next = entries[cnt]
        has_value = False
        if isinstance(entry_next, tuple):
            if len(entry_next) > 2:	# watch out, we'll override it next
                has_value = entry_next[2]
            entry_next = entry_next[0]
            menu_title = entry_next[1]
        else:
            menu_title = entry_next
        cnt += 1	# important this is here for later

        r = menu_scroll_to_entry(
            target, entry_next,
            has_value = has_value, direction = "down",
            highlight_string = highlight_string)
        if not r:
            raise tcfl.tc.error_e(
                "BIOS:%s: can't find entry '%s'" % (_menu_name, entry_next))
        else:
            rs[entry_next] = r
        if cnt < entries_len or cnt == entries_len and dig_last == True:
            target.report_info("BIOS: %s: selecting menu entry '%s'"
                               % (_menu_name, entry_next))
            entry_select(target)

            # Wait for main menu title
            #
            # - \x1b is the escape char
            # - ^[XX;YYH means place next string at (X, Y)
            # - The main manu label is placed in row 2, any column (ANSI
            #   ^[02;YH) and it is prefixed by a space, note the row
            #   number is in %02d format (prefixing zero).
            #
            menu_name.append(menu_title)
            _menu_name =  " > ".join(menu_name)
            submenu_header_expect(
                target, menu_title,
                canary_end_menu_redrawn = canary_end_menu_redrawn,
                menu_name = _menu_name)
        if cnt == entries_len:
            # We got there, done!
            return rs

    raise tcfl.tc.error_e(
        "BIOS:%s: we never got to the entry after %d tries"
        % (level, cnt))


def submenu_header_expect(
        target, menu_title,
        # FIXME: move to BIOS profile
        canary_end_menu_redrawn = "^v=Move Highlight",
        menu_name = None):
    """
    Wait for a submenu header to show up

    When a submenu or dialog box is printed, it is prefixed by a
    header like::

      /------------------------------------\\
      |                                    |
      |           Submenu title            |
      |                                    |
      \------------------------------------/

    wider or narrower or depending on the dialog or full  width (for a
    submenu).

    This function waits for the header to show up.

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param str menu_title: string that is expected to be printed in
      the menu/dialog.

    :param str canary_end_menu_redrawn: (optional) string that is
      printed when the whole menu has been refreshed (and thus marks
      the end of the menu).

    :param str menu_name: (optional; default same as menu_title)
      string that is printed in progress messages to describe the
      menu.

    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(menu_title, str)
    assert canary_end_menu_redrawn == None \
        or isinstance(canary_end_menu_redrawn, str)
    if menu_name == None:
        menu_name = menu_title
    else:
        assert isinstance(menu_title, str)
    start_of_menu = re.compile(br"/-+\\")
    end_of_menu = re.compile(br"\-+/")
    target.expect(start_of_menu,
                  name = menu_name + ":menu-box-start")
    target.expect(menu_title,
                  name = menu_name + ":menu-title")
    target.expect(end_of_menu,
                  name = menu_name + ":menu-box-end" )
    if canary_end_menu_redrawn:
        target.expect(canary_end_menu_redrawn,
                      name = menu_name + ":end-of-menu")
    target.report_info("BIOS:%s: found menu header" % menu_name)


def multiple_entry_select_one(
        target,
        select_entry,
        max_scrolls = 30,
        # regex format, to put inside (?P<values>VALUES)
        wait = 0.5, timeout = 10,
        highlight_string = "\x1b\\[1m\x1b\\[37m\x1b\\[46m",
        level = ""):
    """
    In a simple menu, wait for it to be drown and select a given entry

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :params str select_entry: name of the entry to select; can use
      Python regex format.

    :params int max_scrolls: how many times to scroll maximum

    :params str hightlight_string: (optional) ANSI sequence for
      highlightling an entry (defaults to blue BG, yellow FG, bold)

    :param str level: (optional; default *top*) name of the top level menu

    The menu is usually printed like (blue background, white foreground,
    yellow highlight, like::

      /------------\\
      | Enable     |
      | Disable    |
      \------------/

    In ANSI terms, this is a string as::

       ^[[23;27H<Enter>=Complete Entry
       ^[[23;03H^v=Move Highlight
       ^[[22;03H
       ^[[22;53H
       ^[[22;27H
       ^[[23;53HEsc=Exit Entry
       ^[[0m^[[37m^[[44m^[[10;34H
       ^[[11;34H
       ^[[12;34H
       ^[[13;34H
       ^[[10;34H^[[10;34H/------------\\
       ^[[11;34H|^[[11;47H|^[[12;34H|^[[12;47H|	 <--- vertical bars |
       ^[[1m^[[37m^[[46m^[[11;36HEnable
       ^[[0m^[[37m^[[44m^[[12;36HDisable
       ^[[13;34H\------------/

    selection highlight here is ^[[1m^[[37m^[[46m; this function thus
    waits for:

      - ^[[1m^[[37m^[[46m as highlight (selected)
      - ^[[0m^[[37m^[[44m as normal (not selected)
      - end of menu at \------------/

    and scroll until what we want is selected
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(select_entry, str)
    assert isinstance(max_scrolls, int) and max_scrolls > 0
    assert isinstance(wait, numbers.Real) and wait > 0
    assert isinstance(timeout, numbers.Real) and timeout > 0
    assert isinstance(level, str)

    _direction = False
    entry_highlighted_regex = re.compile(
        b"/-+\\"
        + ".*"
        + highlight_string.encode('utf-8')
        + "\x1b\[[0-9]+;[0-9]+H"
        + "(?P<key>[^\x1b]+)"
        + ".*"
        + r"\-+/")
    target.report_info("BIOS: %s: scrolling for '%s'"
                       % (level, select_entry))
    last_seen_entry = None
    last_seen_entry_count = 0
    for toggle in range(0, max_scrolls):
        if _direction:
            target.console_tx("\x1b[A")			# press arrow up
        else:
            target.console_tx("\x1b[B")			# press arrow down

        target.report_info("BIOS: %s: waiting for highlighted entry" % level)
        # wait for highlighted then give it a breather to send the rest
        retry_top = 5
        retry_cnt = 0
        while retry_cnt < retry_top:
            r = target.expect(entry_highlighted_regex,
                              timeout = timeout, name = "highlight")
            if 'highlight' in r:
                break
            retry_cnt += 1
            target.report_info(
                "BIOS: %s: %s: didn't find a highlighted entry, retrying"
                % (level, select_entry))
            # tickle it
            target.console_tx("\x1b[A")			# press arrow up
            target.console_tx("\x1b[B")			# press arrow down
        else:
            # nothing found, raise it
            raise tcfl.tc.error_e(
                "BIOS: %s: can't find highlighted entries after %d tries"
                % (level, retry_top))

        key = r['highlight']['groupdict']['key']
        select_entry_regex = re.compile(select_entry.encode('utf-8'))
        if select_entry_regex.search(key):
            target.report_info("BIOS: %s: entry '%s' found"
                               % (level, select_entry))
            return key, r['highlight']['groupdict']
        if last_seen_entry == key:
            last_seen_entry_count += 1
        else:
            last_seen_entry = key
            last_seen_entry_count = 1
        if last_seen_entry_count > 2:
            # make sure this count is lower then the one above for
            # seen_entries; we might not have seen all the entries in
            # the menu and have a limited count to make a judgement on
            # maybe this is a menu that does not wrap around, flip the
            # direction
            _direction = not _direction
        target.report_info("BIOS: %s: entry '%s' found, scrolling"
                           % (level, key))

    # nothing found, raise it
    raise tcfl.tc.error_e("%s: can't find entry option after %d entries"
                          % (select_entry, max_scrolls))


def menu_escape_to_main(target, esc_first = True):
    """
    At any submenu, press ESC repeatedly until we go back to the main
    menu

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param bool esc_first: (optional; default *True*) send an ESCAPE
      key press before starting.
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(esc_first, bool)

    target.report_info("BIOS: going to main menu")

    max_levels = 10	# FIXME: BIOS profile?
    if esc_first:
        target.console_tx("\x1b")
    #
    # We look for the Move Highlight marker that is printed at the end
    # of each menu; when we find that, then we look to see if what
    # came before it contained all the main menu entries; if it does,
    # we are good; if it doesn't, we press ESC again.
    #
    # We are going to wrap each main menu entry into how it looks in
    # the ouptut
    #
    # ^[[XX:YYHENTRY[SPACES]
    #
    # to make sure we are not catching false positives because there
    # will be a lot of ANSI flufff in betwween. not being this
    # paranoid makes the main menu detection go out of synch
    regexl = []
    for entry in main_level_entries:
        regexl.append(b"\[[0-9]+;[0-9]+H" + entry.encode('utf-8'))
    main_menu_regex = re.compile(".*".join(regexl))
    for level in range(max_levels):
        offset = target.console.size()
        # All menus print this after printing, so this is how we know
        # the menu has redrawn
        try:
            # FIXME: move this to BIOS profile canary/end/menu/redrawn
            target.expect("^v=Move Highlight")
        except tcfl.tc.error_e:
            target.report_info(
                "BIOS: escaping to main, pressing ESC after timeout %d/%d"
                % (level, max_levels))
            target.console_tx("\x1b")
            continue
        read = target.console.read(offset = offset)
        # then let's see if all the main menu entries are there
        m = main_menu_regex.search(read)
        if m:
            target.report_info("BIOS: escaped to main")
            # FIXME: this is a sync hack--we are still not sure why, but if
            # we don't do this, things dont' sync up properly
            time.sleep(5)
            return
        target.report_info("BIOS: escaping to main, pressing ESC %d/%d"
                           % (level, max_levels))
        target.console_tx("\x1b")

    # nothing found, raise it
    raise tcfl.tc.error_e(
        "BIOS: escaping to main: pressed ESC %d and didn't find"
        " all the main menu entries (%s)"
        % (max_levels, ",".join(main_level_entries)))


def dialog_changes_not_saved_expect(target, action):
    """
    Expect a changes have not saved dialog and do something about it
    (send *yes*, *No* or cancel)

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param str action: a string describing what to send (*Y*, *N*,
      *\x1b*)

    ::

      /---------------------------------------------------------------------\\
      |                                                                     |
      |           Changes have not saved. Save Changes and exit?            |
      |Press 'Y' to save and exit, 'N' to discard and exit, 'ESC' to cancel.|
      |                                                                     |
      \---------------------------------------------------------------------/
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert action in [ "Y", "N", "0x1b" ]

    submenu_header_expect(
        target, "Changes have not saved. Save Changes and exit",
        canary_end_menu_redrawn = None)
    target.console_tx(action)


def menu_config_network_enable(target):
    """
    With the BIOS menu at the top level, enable the configuration option

      *EDKII Menu > Platform Configuration > Network Configuration > EFI Network*

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :returns: *True* if enabled, *False* if it was already enabled.
    """
    assert isinstance(target, tcfl.tc.target_c)

    r = menu_dig_to(
        target,
        [
            "EDKII Menu",
            "Platform Configuration",
            "Network Configuration",
            ( "EFI Network", None, True ),
        ],
        dig_last = False,
        # FIXME: make this default
        canary_end_menu_redrawn = "Esc=Exit")

    entry = 'EFI Network'
    value = r['EFI Network']['value']
    # sic, different versions have differnt values, Disable vs Disabled vs ...
    if "Disable" not in value:
        target.report_info("BIOS: %s: already enabled (%s)" % (entry, value))
        target.console_tx("\x1b")	# ESC one menu up
        return False

    target.report_info("BIOS: %s: enabling (was: %s)" % (entry, value))
    # it's disabled, let's enable
    entry_select(target)			# select it
    # geee ... some do Enable, some Enabled (see the missing d)
    multiple_entry_select_one(target, "Enabled?")
    entry_select(target)			# select it
    # Need to hit ESC twice to get the "save" menu
    target.console_tx("\x1b\x1b")
    dialog_changes_not_saved_expect(target, "Y")
    return True


def menu_reset(target):
    """
    With the BIOS menu at the top level, select the *Reset* option

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    """
    assert isinstance(target, tcfl.tc.target_c)

    # reset to apply new boot option
    r = menu_scroll_to_entry(target, "Reset")
    if r:
        entry_select(target)
    else:
        raise tcfl.tc.error_e("BIOS: can't find 'Reset'")


def menu_continue(target):
    """
    With the BIOS menu at the top level, select the *Reset* option

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :returns: *True* if enabled, *False* if it was already enabled.
    """
    assert isinstance(target, tcfl.tc.target_c)

    # reset to apply new boot option
    r = menu_scroll_to_entry(target, "Continue")
    if r:
        entry_select(target)
    else:
        raise tcfl.tc.error_e("BIOS: can't find 'Continue'")


def bios_boot_expect(target):
    """
    Wait for the BIOS boot messages to show up and then select the
    options to bring the main menu and wait for it to appear.

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)
    """
    # FIXME: move to BIOS profile
    assert isinstance(target, tcfl.tc.target_c)

    target.report_info("BIOS: waiting for main menu after power on")
    # FIXME: [67] should be BIOS profile
    target.expect(re.compile(b"Press\s+\[F[67]\]\s+to show boot menu options"),
                  # this prints a lot, so when reporting, report
                  # only the previous 500 or per spend so much
                  # time reporting we miss the rest
                  report = 500,
                  # can take a long time w/ some BIOSes
                  timeout = 180)


def main_menu_expect(target):
    """
    When the platform boots, wait for the BIOS boot messages to show
    up and then select the options to bring the main menu and wait for
    it to appear.

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :returns: *True* if enabled, *False* if it was already enabled.
    """
    assert isinstance(target, tcfl.tc.target_c)

    bios_boot_expect(target)
    # let's just go to the BIOS menu, F7 is not working
    for _ in range(5):
        time.sleep(0.3)
        target.console.write(ansi_key_code("F2", "vt100"))

    # This means we have reached the BIOS main menu
    target.report_info("BIOS: confirming we are at toplevel menu")
    for entry in main_level_entries:
        target.expect(entry, name = "BIOS-toplevel/" + entry, timeout = 120)

def _paced_send(target, text):
    # FIXME: remove this, use pacing
    cs = 5
    for i in range((len(text) + cs - 1) / cs):
        target.console_tx(text[cs * i : cs * i + cs])

def boot_network_http_boot_add_entry(target, entry, url):
    """
    Create a boot entry called entry to HTTP boot

    THis adds an HTTP boot entry called *entry* that points to *url*
    navigating to:

      1. Navigate to *EDKII Menu > Network Device List >
         MAC:UPPERCASEMACADDR > HTTP Boot Configuration*

      2. Leaf menu white bg, black fg

         - Prints "HTTP Boot Configuration" menu banner (bold, blue
           bg, white fg)

         - two columns, key and value; value printed first
           (highlighted) to the right, then key to the left
           highlight: normal, black bg, white fg::

             ^[[0m^[[37m^[[40m^[[05;31HUEFI HTTP
             ^[[0m^[[30m^[[47m^[[05;40H
                               ^[[05;01H   ^[[05;04HInput the description

           really messy to track, so we need to lock in the
           highlight color string, trap the value, lock in the
           normal color string, lock in the key.

         - press enter to select the key, a menu pops up, blue bg,
           while fg for the fame, sys "Please type your data" and
           it is prefilled with VALUE ("UEFI HTTP" from
           before). Wait for "Please type your data" and "VALUE"
           before starting.

         - Issue len(VALUE) Ctrl-H to delete, then enter
           our value, send ENTER.

         - Scroll down until the selection is for key Boot URI,
           value _::

             ^[[0m^[[30m^[[47m
             ^[[0m^[[37m^[[40m
             ^[[07;31H_
             ^[[0m^[[30m^[[47m
             ^[[07;32H                          ^[[07;01H   [SPACES]
             ^[[07;04HBoot URI                   [SPACES]

         - then same ting as before

         - issue F10 to save

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param str entry: name of the boot entry

    :param str url: url to boot

    :returns: *True* if enabled, *False* if it was already enabled.
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(entry, str)
    assert isinstance(url, str)

    r = menu_scroll_to_entry(target, "Input the description",
                             level = "HTTP Boot Menu",
                             has_value = True)
    entry_select(target)			# select it
    # this pops a menu in the middle of the screen
    # /-----------------------------------------------------------------\
    # |                                                                 |
    # |                     Please type in your data                    |
    # |VALUE                                                            |
    # |                                                                 |
    # \-----------------------------------------------------------------/
    # with a pre-filled in VALUE, which we have to delete
    submenu_header_expect(target, "Please type in your data",
                          canary_end_menu_redrawn = None)
    # delete by sending as many deletes as the value is worth
    value = r['value']
    _paced_send(target, "\x08" * len(value))
    # Fill our new value
    _paced_send(target, entry)
    entry_select(target)			# select it
    # wait until the menu redraw's otherwise we'll get false positives
    target.expect("^v=Move Highlight")

    r = menu_scroll_to_entry(target, "Boot URI",
                             level = "HTTP Boot Menu",
                             has_value = True)
    entry_select(target)			# select it
    # this pops a menu in the middle of the screen
    # /-------------------------------------------------------------\
    # |                                                             |
    # |                     Please type in your data                |
    # |VALUE                                                        |
    # |                                                             |
    # \-------------------------------------------------------------/
    # with a pre-filled in VALUE, which we have to delete
    submenu_header_expect(target, "Please type in your data",
                          canary_end_menu_redrawn = None)
    # delete by sending as many deletes as the value is worth
    value = r['value']
    _paced_send(target, "\x08" * len(value))
    # Fill our new value
    _paced_send(target, url)
    entry_select(target)			# select it
    # wait until the menu redraw's otherwise we'll get false positives
    target.expect("^v=Move Highlight")

    # save; this takes us to the previous menu
    target.console_tx(ansi_key_code("F10", "vt100"))
    target.expect("Press 'Y' to save and exit")
    target.console_tx("Y")


def main_boot_select_entry(target, boot_entry):
    """
    From the main menu, go to the boot menu and boot an entry

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param str boot_entry: python regular expression that describes the
      boot entry (or boot entries) that are considered PXE bootabe

    :returns bool: *True* if the entry was found and selected, *False*
      if not
    """
    # FIXME: do straight from the boot menu
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(boot_entry, str)

    # Now we are in the Boot Manager Menu; we need to check if
    # there is a UEFI PXEv4 entry -- if not, it means the network
    # is not enabled, so we have to go enable it
    r = menu_scroll_to_entry(target, "Boot Manager Menu",
                             level = "main menu")
    if not r:
        raise tcfl.tc.error_e("BIOS: can't find boot manager menu")
    entry_select(target)			# select it
    submenu_header_expect(target, "Boot Manager Menu",
                          canary_end_menu_redrawn = None)
    r = menu_scroll_to_entry(target, boot_entry,
                             level = "Boot Manager Menu",
                             # yeah, some destinations have a lot...
                             max_scrolls = 60)
    if r:
        return True			# DONE!
    return False


def boot_network_http(target, entry, url,
                      assume_in_main_menu = False):
    """
    From the main menu, select an HTTP boot entry and boot it; if
    missing, add it go to the boot menu and boot an entry

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param str entry: entry name; field *%(ID)s* will be replaced with
      a hash of *url*; if not found, it will be created as an HTTP
      boot entry with that name.

    :param bool assume_in_main_menu: (optional, default *False*)
      assume the BIOS is already in the main menu, otherwise wait for
      it to arrive.

    :returns bool: *True* if the entry was found and selected, *False*
      if not

    """
    # FIXME: do straight from the boot menu with the hot key
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(entry, str)
    assert isinstance(url, str)
    assert isinstance(assume_in_main_menu, bool)

    top = 4
    kws = dict(ID = commonl.mkid(url, l = 4))
    entry = entry % kws
    for cnt in range(top):
        if assume_in_main_menu:
            assume_in_main_menu = False
        else:
            main_menu_expect(target)
        if main_boot_select_entry(target, entry):
            entry_select(target)			# select it
            break
        target.report_info("BIOS: can't find HTTP network boot entry '%s';"
                           " attempting to enable EFI network support"
                           % entry)
        # Ensure EFI networking is on
        menu_escape_to_main(target)
        if menu_config_network_enable(target):
            # EFI Networking was disabled, now it is enabled. we need to
            # reset before we can see the network device list (once we
            # have enabled networking)
            menu_escape_to_main(target, esc_first = False)
            menu_reset(target)
            main_menu_expect(target)
        else:
            menu_escape_to_main(target, esc_first = False)

        # Now go to create our HTTP boot entry
        r = menu_dig_to(
            target,
            # FIXME: make this path object's property
            [
                "EDKII Menu",
                "Network Device List",
                # seriusly..the entry is called MAC: but the menu
                # title "Network Device MAC:"...
                (
                    "MAC:(?P<macaddr>[A-F0-9:]+)",
                    "Network Device MAC:(?P<macaddr>[A-F0-9:]+)"
                ),
                "HTTP Boot Configuration",
            ],
            # FIXME: make this default
            canary_end_menu_redrawn = "Esc=Exit")
        if not r:
            raise tcfl.tc.error_e(
                "BIOS: can't get to the menu to add HTTP boot; giving up")

        boot_network_http_boot_add_entry(target, entry, url)
        # fall through, try again
        menu_escape_to_main(target, esc_first = False)
        assume_in_main_menu = True
    else:
        raise tcfl.tc.error_e(
            "BIOS: HTTP network boot failed %s/%s; giving up"
            % (cnt, top))

def boot_network_pxe(target, entry = "UEFI PXEv4.*",
                     assume_in_main_menu = False):
    """
    From the main menu, select a PXE boot entry and boot it; if
    missing, enable EFI networking (which shall make it appear by
    default)a

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :param str entry: (optional) entry name; defaults to anything
      containing the works "UEFI PXEv4".

    :param bool assume_in_main_menu: (optional, default *False*)
      assume the BIOS is already in the main menu, otherwise wait for
      it to arrive.
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(entry, str)
    assert isinstance(assume_in_main_menu, bool)
    top = 4
    for cnt in range(top):
        if assume_in_main_menu:
            assume_in_main_menu = False
        else:
            main_menu_expect(target)
        if main_boot_select_entry(target, entry):
            entry_select(target)			# select it
            break
        target.report_info("BIOS: can't find PXE network boot entry '%s';"
                           " attempting to enable EFI network support"
                           % entry)
        menu_escape_to_main(target)
        menu_config_network_enable(target)
        menu_escape_to_main(target, esc_first = False)
        menu_reset(target)
        target.report_info("BIOS: PXE network boot failed %s/%s; retrying"
                           % (cnt, top))
    else:
        raise tcfl.tc.error_e("BIOS: PXE network boot failed %s/%s; giving up"
                              % (cnt, top))

def boot_efi_shell(target):
    """
    From the main menu, select the EFI Shell boot entry.

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)
    """
    assert isinstance(target, tcfl.tc.target_c)
    main_menu_expect(target)

    if main_boot_select_entry(target, "EFI .* Shell"):
        entry_select(target)			# select it
        target.expect("Shell>")
    else:
        raise tcfl.tc.error_e("BIOS: can't find an EFI shell entry")


main_level_entries = [
    "EDKII Menu",
    "Boot Manager Menu",
    "Boot Maintenance Manager",
    "Continue",
    "Reset",
]
