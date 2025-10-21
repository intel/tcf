#! /usr/bin/python3
#
# Copyright (c) 2019 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
# pylint: disable = missing-docstring
#
# FIXME: create an object 'bios_c' that can be used to manipulate BIOS
# settings; attach most to it
""".. _bios_menus:

Utilities for manipulating BIOS menus and UEFI
----------------------------------------------

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

.. _bios_inventory::

Inventory configuration
^^^^^^^^^^^^^^^^^^^^^^^

This library relies in the target's inventory declaring certain
values that are inherit to the BIOS:

- *bios.terminal_emulation* (string; default *vt100*): terminal
  emulation used by the BIOS; normally *vt100*, *vt200*, *rxvt*

  These are valid values in :data:`tcfl.biosl.ansi_key_codes`.

- *bios.boot_time* (positive integer; SECONDS; default 60): time in
  seconds it takes the BIOS to boot (ie: to show *bios.boot_prompt*)

- *bios.boot_menu_time* (positive integer; SECONDS; default 60):
  maximum time in seconds it takes the BIOS to go from the main menu
  to the BIOS Boot menu when selected.

- *bios.boot_prompt* (Python regular expression string; no default):
  regex defining what string the BIOS prints when it is done booting
  and is ready to take input, for example::

    Press  [F6]   to show boot menu options

  can be tackled with::

    "Press\\s+\\[F[67]\]\\s+to show boot menu options"

- *bios.boot_prompt_report_backlog* (positive integer; bytes; default
  500): how many bytes of data found before the prompt have to be
  reported.

- *bios.boot_key_main_menu* (string; no default): key to press to
  enter the main BIOS menu; eg: "he"

  The names of recognized keys are listed in
  :data:`tcfl.biosl.ansi_key_codes`.

- *bios.main_level_entries* (dictionary of strings; no defaults): list
  of entries the main BIOS menu contains:

  This is used to validate when the target is actually in the main
  BIOS menu. The entries value is a valid Python regular expression
  text (thus not compiled).

  eg::

      bios.main_level_entries.1: Main
      bios.main_level_entries.2: Advanced
      bios.main_level_entries.3: Security
      bios.main_level_entries.4: Server Management
      bios.main_level_entries.5: Error Manager
      bios.main_level_entries.6: Boot Manager
      bios.main_level_entries.7: Boot Maintenance Manager
      bios.main_level_entries.8: Save & Exit
      bios.main_level_entries.9: Tls Auth Configuration


- *bios.boot_entry_EFI_SHELL* Python regular expression string;
  defaults to *EFI .* Shell*): name of the boot entry that boots the
  EFI shell in the boot menu.

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

  \\x1b[1m\\x1b\\[37m\\x1b\\[40m\\x1b\\[[0-9]+;[0-9]+HLaunch EFI Shell

References:

- formatting:

  - https://en.wikipedia.org/wiki/ANSI_escape_code
  - https://bluesock.org/~willkg/dev/ansi.html

- keys:

  - https://invisible-island.net/xterm/xterm-function-keys.html

WARNING!!!
^^^^^^^^^^

Always use :meth:`tcfl.tc.target_c.console_tx` vs *target.console.write()*

Otherwise the send/expect gets out of sync and things don't work as expected.

"""
import collections
import math
import numbers
import re
import time

import commonl
import tcfl.tc
import tcfl.tl
import tcfl.pos

# white/grey-background menus
normal_white_fg_black_bg = r"\x1b\[0m\x1b\[37m\x1b\[40m"	# highlighted
normal_black_fg_white_bg = r"\x1b\[0m\x1b\[30m\x1b\[47m"	# normal
# blue background menus
bold_white_fg_cyan_bg =    r"\x1b\[1m\x1b\[37m\x1b\[46m"	# highlighted
normal_white_fg_blue_bg =  r"\x1b\[0m\x1b\[37m\x1b\[44m" # normal

ansi_key_codes = {
    "arrow_down": {
        "\x1b[B": [ "rxvt", 'vt100', "xterm" ],
    },
    "arrow_up": {
        "\x1b[A": [ "rxvt", 'vt100', "xterm" ],
    },
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
        # 24, not 23 https://en.wikipedia.org/wiki/ANSI_escape_code#Terminal_input_sequences
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
    raise unknown_key_code_e(
        "tcfl.biosl.ansi_key_codes: unknown key code %s for term %s"
        % (key, term))

def entry_select(target, wait = 0.5):
    # sometimes it needs to wait a wee bit for the menu to settle; so
    # do it here
    # in the future this will include more things, BIOS specific, to
    # select entries
    target.console_tx("\r")    # USE CONSOLE_TX!!! see file header



def scroll_up(target, terminal: str = None):
    # in vt100 and most others, \x1b[A
    if terminal == None:
        terminal = target.kws.get("bios.terminal_emulation", "vt100")
    # USE CONSOLE_TX!!! see file header
    target.console_tx(ansi_key_code("arrow_up", terminal))



def scroll_down(target, terminal: str = None):
    # in vt100 and most others, \x1b[B
    if terminal == None:
        terminal = target.kws.get("bios.terminal_emulation", "vt100")
    # USE CONSOLE_TX!!! see file header
    target.console_tx(ansi_key_code("arrow_down", terminal))



def scroll_updown(target,
                  # FIXME: bool | str -> newer Python only, so leave
                  # without spec until we can deprecate support for
                  # older Python versions
                  direction,
                  terminal: str = None):
    """
    Send a press arrow up or down to the target's default console

    :param str|bool direction: what to press; this can be a string
      (more descriptive) or a bool, for easy manipulation.

      - bool:True or str:up: send an arrow/cursor up
      - bool:False or str:down: send an arrow/cursor down

    :param str terminal: (optional, default from target's property
      *bios.terminal_emulation* which will be defaulted to *vt100*.

    """
    if isinstance(direction, str):
        direction = direction.lower()
    if direction == True or direction == "up":
        scroll_up(target, terminal = terminal)
    elif direction == False or direction in ( "down", "dn" ):
        scroll_down(target, terminal = terminal)
    else:
        raise AssertionError(
            "direction: unknown direction, expected (up|True, down|false),"
            f" got {direction}")



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

        \\\\x1b[0m\\\\x1b\\[37m\\\\x1b\\[40m


    :param str normal_string: (optional) sequence that prefixes an
      entry not highlighted; defaults to ANSI normal, black
      foreground, white background::

        \\\\x1b[0m\\\\x1b\\[30m\\\\x1b\\[47m

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
    assert isinstance(entry_string, (str, bytes))
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
    #
    # This fugly regex supports entries with value and entries with
    # values; it's complicated, but it is what allows to support an
    # scenario such as (from the QEMU EFI shell):
    #
    ##
    ##  Standard PC (i440FX + PIIX, 1996)
    ##  pc-i440fx-7.0                                       2.00 GHz
    ##  edk2-20230524-3.fc37                                10240 MB RAM
    ##
    ##
    ##
    ##    Select Language            <Standard English>         This is the option
    ##                                                          one adjusts to change
    ##  ► Device Manager                                        the language for the
    ##  ► Boot Manager                                          current system
    ##  ► Boot Maintenance Manager
    ##
    ##    Continue
    ##    Reset
    ##
    #
    # The entries with value are rendered in a really weird way (value
    # first, key later). Really messy.
    #
    # Since we can't have repeated keys, we have
    # <NAME>_{value|novalue}_<MORENAME> and then we decode them as
    # needed later on.
    selected_regex = re.compile(
        highlight_string.encode('utf-8') + b"("
        + (
            # this takes care of (2) in the function doc
            rb"\x1b\[(?P<row_value>[0-9]+);(?P<column_value>[0-9]+)H"
            # value is anything that is not an ANSI escape char
            + rb"(?P<value>[^\x1b]+)"
            # the rest for us is fluf until the entry name(key) comes
            + normal_string.encode('utf-8')
            # not sure if these two space sequences are optional
            # note we force with (?P=row) that they are all in the
            # same column; this will cause problem for multiline
            # entries...
            + rb"\x1b\[(?P=row_value);[0-9]+H\s+"
            + rb"\x1b\[(?P=row_value);[0-9]+H\s+"	# yup, this is doubled
            + rb"\x1b\[(?P=row_value);(?P<column_value_key>[0-9]+)H"
            # Some entries do start with a space, but it is not *all* spaces
            + rb"(?P<key_value>[^\x1b]*[^ \x1b][^\x1b]*)"
        )
        + b"|"
        + (
            # takes care of (1) in the function doc
            # This won't work when we have multi line values in key/values
            # :/
            rb"\x1b\[(?P<row_novalue>[0-9]+);(?P<column_novalue_key>[0-9]+)H"
            # Some entries do start with a space, but it is not *all*
            # spaces; they might finish with a string of spaces, but
            # definitely in a escape sequence
            + rb"(?P<key_novalue>[^\x1b]*[^ \x1b][^\x1b]*) *\x1b"
        )
        + b")")

    if isinstance(entry_string, str):
        # convert to bytes
        entry_string = entry_string.encode('utf-8')
    entry_regex = re.compile(entry_string)
    seen_entries = collections.defaultdict(int)
    last_seen_entry = None
    last_seen_entry_count = 0
    # we have either a bug or a feature, not clear and we miss the
    # first line that has the first entry selected; so the first time
    # we just go back and go fo
    first_scroll = True

    # wiggle the cursor so the loop will refresh whichever entry we
    # might be highlighted on -- note this is the opposite of what we
    # do in the loop
    target.report_info(f"{name}: reverse scrolling")
    scroll_updown(target, "up" if direction == "down" else "down")
    # WAIT for the scroll to settle; otherwise we'll break havoc on
    # the state machine since it'll half draw and confuse the expectation
    target.console.wait_for_no_output(
        target.console.default, silence_period = 0.6, poll_period = 0.2,
        reason = f"display to settle before scrolling '{entry_string}'")

    for count in range(max_scrolls):
        target.report_info(f"{name}: scrolling {count}/{max_scrolls}")
        scroll_updown(target, direction)
        # alway give some time after scrolling because it takes time
        # to redraw and things get out of sync otherwise
        target.console.wait_for_no_output(
            target.console.default, silence_period = 0.6, poll_period = 0.2,
            reason = f"menu to render, scrolling for entry '{entry_string}'")

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
                # sometimes these are caused by bad serial lines, with
                # key characters missed, so we just try to reverse
                # scroll and try again; we don't try to go up and
                # down because it confuses the state machine.
                skips += 0.5
                # wiggle the cursor so the loop will refresh whichever entry we
                # might be highlighted on -- note this is the opposite of what we
                # do in the loop
                target.report_info(f"{name}: reverse scrolling bc /timeout")
                scroll_updown(target, "up" if direction == "down" else "down")
                # WAIT for the scroll to settle; otherwise we'll break havoc on
                # the state machine since it'll half draw and confuse the expectation
                target.console.wait_for_no_output(
                    target.console.default, silence_period = 0.6, poll_period = 0.2,
                    reason = f"menu to render, wiggled looking for entry '{entry_string}'")
                continue
            # the key always matches spaces all the way to the end, so it
            # needs to be stripped
            key_value = r[name]['groupdict']['key_value']
            key_novalue = r[name]['groupdict']['key_novalue']
            if key_novalue == None:
                key = key_value.strip()
                key_at_column = int(r[name]['groupdict']['column_value_key'])
            else:
                key = key_novalue.strip()
                key_at_column = int(r[name]['groupdict']['column_novalue_key'])

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
        level = "top", do_flush: bool = True):
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

        \\\\x1b[0m\\\\x1b\\[37m\\\\x1b\\[40m

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

    if do_flush:
        target.report_info(f"BIOS/menu_dig_to: flushing console {target.console.default}")
        target.console.send_expect_sync(target.console.default)

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
            menu_title = entry_next[1]
            entry_next = entry_next[0]
        else:
            menu_title = entry_next
        cnt += 1	# important this is here for later

        # Do not flush/sync here! let menu_scroll_to_entry() do it
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
            target.console.wait_for_no_output(
                target.console.default, silence_period = 0.6, poll_period = 0.2,
            reason = f"menu to settle after selecting entry '{entry_next}'")

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
                timeout = 160,	# some menu entries can take long to load
                canary_end_menu_redrawn = canary_end_menu_redrawn,
                menu_name = _menu_name, wait_for_no_output = False)
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
        menu_name = None,
        timeout = None,
        wait_for_no_output: bool = True):
    """
    Wait for a submenu header to show up

    When a submenu or dialog box is printed, it is prefixed by a
    header like::

      /------------------------------------\\
      |                                    |
      |           Submenu title            |
      |                                    |
      \\------------------------------------/

    wider or narrower or depending on the dialog or full  width (for a
    submenu).

    However is not that easy, because depending on the terminal/BIOS
    (eg: QEMU), it might use other chars (eg: 0xc4 instead of -) and
    no \\ or /... so we need to stick to just look for the row of
    ----- or (0xc40xc40xc40xc40xc40xc4)


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

    # wait for the menu to finish drawing
    if wait_for_no_output:
        target.console.wait_for_no_output(
            target.console.default, silence_period = 0.6, poll_period = 0.2,
            reason = f"menu '{menu_title}' to render before detecting it")
    # note some versions of EDKII use --, others UTF-9 chars...not
    # fun, deps on the encoding, so this regex means to try to pick'em
    # all
    # try to do as little calls to expect() as possible, as they
    # delay the process a lot -- so we compose a single regex
    # where we look for all the components of the menu.
    pattern = \
        r"(----+|──────+|\xc4\xc4\xc4\xc4+).*" \
        f"{menu_title}" \
        ".*(----+|──────+|\xc4\xc4\xc4\xc4+)"
    if canary_end_menu_redrawn:
        pattern += ".*" + canary_end_menu_redrawn

    target.expect(re.compile(pattern),
                  name = menu_name + ":menu-dialog",
                  timeout = timeout)
    target.report_info("BIOS:%s: found menu header" % menu_name)


def multiple_entry_select_one(
        target,
        select_entry,
        max_scrolls = 30,
        # regex format, to put inside (?P<values>VALUES)
        wait = 0.5, timeout = 10,
        highlight_string = "\x1b\\[1m\x1b\\[37m\x1b\\[46m",
        skip_first_scroll: bool = True,
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
      \\------------/

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
       ^[[13;34H\\------------/

    selection highlight here is ^[[1m^[[37m^[[46m; this function thus
    waits for:

      - ^[[1m^[[37m^[[46m as highlight (selected)
      - ^[[0m^[[37m^[[44m as normal (not selected)
      - end of menu at \\------------/

    and scroll until what we want is selected
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert isinstance(select_entry, str)
    assert isinstance(max_scrolls, int) and max_scrolls > 0
    assert isinstance(wait, numbers.Real) and wait > 0
    assert isinstance(timeout, numbers.Real) and timeout > 0
    assert isinstance(level, str)

    # so this assumes the whole box is redrawn every time we move the
    # cursor -- hence why we look for /---- ANSICRUFT+KEYSANSI+CRUFT
    # HIGHLIGHT KEY ANSICRUFT ----/
    entry_highlighted_regex = re.compile(
        b"/-+"
        + b".*"
        + highlight_string.encode('utf-8')
        + rb"\x1b\[[0-9]+;[0-9]+H"
        + rb"(?P<key>[^\x1b]+)"
        + rb".*"
        + rb"-+/")
    target.report_info("BIOS: %s: scrolling for '%s'"
                       % (level, select_entry))
    last_seen_entry = None
    last_seen_entry_count = 0
    direction = False   # down -- we'll toggle it later
    # wiggle the cursor in the opposite direction to refresh the
    # current entry
    scroll_updown(target, not direction)
    # WAIT for the scroll to settle; otherwise we'll break havoc on
    # the state machine since it'll half draw and confuse the expectation
    target.console.wait_for_no_output(
        target.console.default, silence_period = 0.6, poll_period = 0.2,
        reason = f"multiple/entry: display to settle before scrolling to '{select_entry}'")

    for toggle in range(0, max_scrolls):
        if skip_first_scroll:
            skip_first_scroll = False
        else:
            scroll_updown(target, direction)
            # WAIT for the scroll to settle; otherwise we'll break havoc on
            # the state machine since it'll half draw and confuse the expectation
            target.console.wait_for_no_output(
                target.console.default, silence_period = 0.6, poll_period = 0.2,
                reason = f"multiple/entry: display to settle before scrolling to '{select_entry}'")

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
            scroll_updown(target, not direction)
            # WAIT for the scroll to settle; otherwise we'll break havoc on
            # the state machine since it'll half draw and confuse the expectation
            target.console.wait_for_no_output(
                target.console.default, silence_period = 0.6, poll_period = 0.2,
                reason = f"multiple/entry: display to settle before scrolling to '{select_entry}'")
            scroll_updown(target, direction)
            # WAIT for the scroll to settle; otherwise we'll break havoc on
            # the state machine since it'll half draw and confuse the expectation
            target.console.wait_for_no_output(
                target.console.default, silence_period = 0.6, poll_period = 0.2,
                reason = f"multiple/entry: display to settle before scrolling to '{select_entry}'")
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
            target.report_info("BIOS: %s: entry '%s' found %s times,"
                               " reversing scroll direction"
                               % (level, key, last_seen_entry_count))
            direction = not direction
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
    main_level_entries = main_level_entries_get(target)
    for entry in main_level_entries:
        regexl.append(r"\[[0-9]+;[0-9]+H" + entry)
    main_menu_regex = re.compile(".*".join(regexl))

    for level in range(max_levels):
        # All menus print this after printing, so this is how we know
        # the menu has redrawn
        try:
            target.console.wait_for_no_output(
                target.console.default, silence_period = 0.6, poll_period = 0.2,
                reason = "(possibly main) menu to render")
            # FIXME: move this to BIOS profile canary/end/menu/redrawn
            target.expect(main_menu_regex,
                          name = "main-menu-entries", timeout = 2)
            target.report_info(
                "BIOS/escaping-to-main: found all main entries,"
                " escaped to main")
            return
        except tcfl.tc.fail_e:
            # didn't find all the expected entries, not there yet,
            # press ESC again
            target.report_info(
                "BIOS/escaping-to-main: pressing ESC after timeout"
                " looking for main menu entries %d/%d"
                % (level, max_levels))
            target.console_tx("\x1b")
            continue

    # nothing found, raise it
    raise tcfl.tc.error_e(
        "BIOS: escaping to main: pressed ESC %d and didn't find"
        " all the main menu entries (%s)"
        % (max_levels, ",".join(main_level_entries)))


def dialog_changes_not_saved_expect(target, action, timeout = 20):
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
      \\---------------------------------------------------------------------/
    """
    assert isinstance(target, tcfl.tc.target_c)
    assert action in [ "y", "Y", "n", "N", "0x1b" ]

    submenu_header_expect(
        target, "Changes have not saved. Save Changes and exit",
        canary_end_menu_redrawn = None, timeout = timeout)
    # if we send the action too soon, sometimes it gets hung...so
    # let's be patient
    time.sleep(0.5)
    target.console_tx(action)
    time.sleep(0.25)


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
    if b"Disable" not in value:
        target.report_info("BIOS: %s: already enabled (%s)" % (entry, value))
        time.sleep(0.25)
        target.console_tx("\x1b")	# ESC one menu up
        time.sleep(0.25)
        return False

    target.report_info("BIOS: %s: enabling (was: %s)" % (entry, value))
    # it's disabled, let's enable
    entry_select(target)			# select it
    # geee ... some do Enable, some Enabled (see the missing d)
    multiple_entry_select_one(target, "Enabled?")
    entry_select(target)			# select it
    # hit F10 to save -- this way we don't have to deal with the
    # "changes not saved" dialog, which is very error prone
    bios_terminal = target.kws.get("bios.terminal_emulation", "vt100")
    target.console.write(ansi_key_code("F10", bios_terminal))
    dialog_changes_not_saved_expect(target, "Y")
    # when this is succesful saving, we end up in this menu
    submenu_header_expect(
        target, "Platform Configuration",
        canary_end_menu_redrawn = None)
    return True


def menu_config_network_disable(target):
    """
    With the BIOS menu at the top level, disable the configuration option

      *EDKII Menu > Platform Configuration > Network Configuration > EFI Network*

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)

    :returns: *True* if changed, *False* if it was already disabled.
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
    if b"Enable" not in value:
        target.report_info("BIOS: %s: already disabled (%s)" % (entry, value))
        time.sleep(0.25)
        target.console_tx("\x1b")	# ESC one menu up
        time.sleep(0.25)
        return False
    target.report_info("BIOS: %s: disabling (was: %s)" % (entry, value))
    # it's enabled, let's disable
    tcfl.biosl.entry_select(target)			# select it
    # geee ... some do Disable, some Disabled (see the missing d) so
    # use ? as a regex
    tcfl.biosl.multiple_entry_select_one(target, "Disable?")
    tcfl.biosl.entry_select(target)			# select it
    # hit F10 to save -- this way we don't have to deal with the
    # "changes not saved" dialog, which is very error prone
    # Need to hit ESC twice to get the "save" menu
    time.sleep(0.25)
    target.console_tx("\x1b\x1b")
    time.sleep(0.25)
    # Need to hit ESC twice to get the "save" menu
    bios_terminal = target.kws.get("bios.terminal_emulation", "vt100")
    target.console.write(ansi_key_code("F10", bios_terminal))
    dialog_changes_not_saved_expect(target, "Y")
    # when this is succesful saving, we end up in this menu
    submenu_header_expect(
        target, "Platform Configuration",
        canary_end_menu_redrawn = None)
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

    bios_boot_time = target.kws.get('bios.boot_time', 180)

    ts0 = time.time()
    boot_prompt = target.kws.get("bios.boot_prompt",
                                 target.kws.get("bios_boot_prompt", None))
    if boot_prompt == None:
        raise tcfl.tc.blocked_e(
            r"%s: target does not declare what the BIOS boot prompt looks"
            r" like (in the serial console) in property bios.boot_prompt;"
            r" thus I do not know what to wait for; please do set it"
            r" (eg: 'Press\s+\[F6\]\s+to show boot menu options')"
            % target.id,
            dict(target = target))
    if not boot_prompt:
        target.report_info("BIOS: not waiting for boot prompt"
                           " (declared empty in bios.boot_prompt)")
        return
    target.report_info("BIOS: waiting for main menu after power on"
                       f" (up to {bios_boot_time}s)")
    report_backlog = target.kws.get(
        "bios.boot_prompt_report_backlog", 500)
    target.expect(re.compile(boot_prompt.encode('utf-8')),
                  # this prints a lot, so when reporting, report
                  # only the previous 500 or per spend so much
                  # time reporting we miss the rest
                  report = report_backlog,
                  # can take a long time w/ some BIOSes
                  timeout = bios_boot_time)
    target.report_data("Boot statistics %(type)s", "BIOS boot time (s)",
                       time.time() - ts0)


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
    bios_terminal = target.kws.get("bios.terminal_emulation", "vt100")
    key_main_menu = target.kws.get("bios.boot_key_main_menu", None)
    if key_main_menu == None:
        raise tcfl.tc.blocked_e(
            "%s: target does not declare what the BIOS key to press to"
            " go to the main menu in property bios.boot_key_main_menu"
            " (eg: F2, F6, F12...)" % target.id,
            dict(target = target))
    for _ in range(10):
        target.console.write(ansi_key_code(key_main_menu, bios_terminal))
        time.sleep(0.25)

    # This means we have reached the BIOS main menu
    target.report_info("BIOS: confirming we are at toplevel menu")
    for entry in main_level_entries_get(target):
        target.expect(entry, name = "BIOS-toplevel/" + entry, timeout = 120)
        target.report_info(f"BIOS: toplevel: found expected entry {entry}")



def _paced_send(target, text):
    # FIXME: remove this, use pacing
    cs = 5
    for i in range(math.ceil((len(text) + cs - 1) / cs)):
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
    bios_terminal = target.kws.get("bios.terminal_emulation", "vt100")
    target.console_tx(ansi_key_code("F10", bios_terminal))
    target.expect("Press 'Y' to save and exit")
    time.sleep(0.25)
    target.console_tx("y")
    time.sleep(0.25)


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
    assert isinstance(boot_entry, (str, bytes))

    # Now we are in the Boot Manager Menu; we need to check if
    # there is a UEFI PXEv4 entry -- if not, it means the network
    # is not enabled, so we have to go enable it
    # note some places call the menu Boot Manager, others Boot Manager Menu
    boot_manager_menu_name = target.kws.get('bios.boot_manager_menu_name',
                                            "Boot Manager Menu")
    r = menu_scroll_to_entry(target, boot_manager_menu_name,
                             level = "main menu")
    if not r:
        raise tcfl.tc.error_e("BIOS: can't find boot manager menu")
    entry_select(target)			# select it
    submenu_header_expect(target, boot_manager_menu_name,
                          canary_end_menu_redrawn = None,
                          timeout = target.kws.get('bios.boot_menu_time', 120))
    max_scrolls = target.kws.get("bios.boot_menu_max_scrolls", 60)
    r = menu_scroll_to_entry(target, boot_entry,
                             level = boot_manager_menu_name,
                             # yeah, some destinations have a lot...
                             max_scrolls = max_scrolls)
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
            # reset expect engine; otherwise we might have back
            # history and then we are out of sync
            target.expect("")
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

def boot_efi_shell(target, in_main_menu = False):
    """
    From the main menu, select the EFI Shell boot entry.

    :param tcfl.tc.target_c target: target on which to operate (uses
      the default console)
    """
    assert isinstance(target, tcfl.tc.target_c)
    if not in_main_menu:
        main_menu_expect(target)

    entry_efi_shell = target.kws.get(
        "boot.boot_entry_EFI_shell", "EFI .* Shell")
    if main_boot_select_entry(target, entry_efi_shell.encode('utf-8')):
        entry_select(target)			# select it
        target.expect("Shell>")
    else:
        raise tcfl.tc.error_e("BIOS: can't find an EFI shell entry")


def main_level_entries_get(target):
    """
    Return the list of main entries we want to find in the top level
    BIOS menu

    These are exposed on the target's BIOS data in the inventory (see
    above) *bios.main_level_entries*.

    :param tcfl.tc.target_c target: target where to find them
    """
    # bios.main_level_entries won't work because we either access the
    # full flat dictionary or not (and main_level_entreies has subentries)
    entries = target.kws.get("bios", {}).get("main_level_entries", None)
    if entries == None:
        raise tcfl.tc.blocked_e(
            "%s: target does not declare the list of entries in the"
            " main BIOS menu in property bios.main_level_entries;"
            " thus I do not know what to look for; please do set it"
            % target.id,
            dict(target = target))
    if not isinstance(entries, collections.abc.Mapping):
        raise tcfl.tc.blocked_e(
            "%s: target's property bios.main_level_entries shall be a"
            " dictionary keyed by entry order"
            % target.id,
            dict(target = target))

    # entries will look like (eg: from EDKII)
    #
    #   $ tcf get r50s03 -p bios
    #   {
    #       "bios": {
    #           "boot_key_main_menu": "F2",
    #           "boot_prompt": "Press\\s+\\[F[67]\\]\\s+to show boot menu options",
    #           "boot_prompt_report_backlog": 500,
    #           "boot_time": 800,
    #           "main_level_entries": {
    #               "1": "EDKII Menu",
    #               "2": "Boot Manager Menu",
    #               "3": "Boot Maintenance Manager",
    #               "4": "Continue",
    #               "5": "Reset"
    #           }
    #       }
    #   }
    #
    # Or in Python form:
    #
    #   $ tcf property-get r50s03 bios.main_level_entries
    #   OrderedDict([('1', 'EDKII Menu'), ('2', 'Boot Manager Menu'), ('3', 'Boot Maintenance Manager'), ('4', 'Continue'), ('5', 'Reset')])
    #
    # note the order matters and it is given by sorting the keys
    return [ entry[1] for entry in sorted(entries.items(), key = lambda x: x[0]) ]


def uefi_dh_extract(dh_output: str):
    """
    Extract fields from the output of the EFI dh command.

    WARNING! Only single line fields in the form *KEY:VALUE *are handled!

    :param str dh_output: output of *dh -v HANDLE* EFI command, such as::
        20F: 5F86BD18
        E3161450-AD0F-11D9-9669-0800200C9A66(5EAB3050)
        PCIIO(5F83F428)
          Segment #.....: 00
          Bus #.........: 2A
          Device #......: 00
          Function #....: 00
          ROM Size......: 0
          ROM Location..: 0
          Vendor ID.....: 8086
          Device ID.....: 1533
          Class Code....: 00 00 02
          Configuration Header :
               86803315470110000300000220000000
               0000309C00000000015000000000389C
               000000000000000000000000FFFF0000
               000000004000000000000000FF010000
        DevicePath(5F846F98)
          PciRoot(0x11)/Pci(0x6,0x0)/Pci(0x0,0x0)

    :returns: dictionary keyed by field name with value; both strings
    """
    regex_dh = re.compile("^\w*(?P<field>[^:]+): (?P<value>.*)$")
    d = {}
    for line in dh_output.splitlines():
        m = regex_dh.search(line)
        if not m:
            continue
        # why they had to add periods to trail the field name beats me
        field = m.group("field").strip().rstrip(".")
        value = m.group("value").strip()
        d[field] = value
    return d



def uefi_devtree_extract_dhs_from_mac(devtree_output: str):

    """Parse the output of EFI's devtree command to extract MAC
    addresses and what device handles they map to.

    :param str devtree_output: a string from the output of running
      'devtree' in EFI, which looks like::

        Ctrl[^[[1m^[[37m^[[40mC0^[[0m^[[37m^[[40m] PciRoot(0x11)
          Ctrl[^[[1m^[[37m^[[40m20A^[[0m^[[37m^[[40m] PciRoot(0x11)/Pci(0x0,0x0)
          Ctrl[^[[1m^[[37m^[[40m20B^[[0m^[[37m^[[40m] PciRoot(0x11)/Pci(0x0,0x1)
          Ctrl[^[[1m^[[37m^[[40m20C^[[0m^[[37m^[[40m] PciRoot(0x11)/Pci(0x0,0x2)
          Ctrl[^[[1m^[[37m^[[40m20D^[[0m^[[37m^[[40m] PciRoot(0x11)/Pci(0x0,0x4)
          Ctrl[^[[1m^[[37m^[[40m20E^[[0m^[[37m^[[40m] PciRoot(0x11)/Pci(0x6,0x0)
          Ctrl[^[[1m^[[37m^[[40m20F^[[0m^[[37m^[[40m] Intel(R) I210 Gigabit  Network Connection
            Ctrl[^[[1m^[[37m^[[40m3B5^[[0m^[[37m^[[40m] Intel(R) I210 Gigabit  Network Connection
              Ctrl[^[[1m^[[37m^[[40m3B6^[[0m^[[37m^[[40m] PciRoot(0x11)/Pci(0x6,0x0)/Pci(0x0,0x0)/MAC(A4BF018D0DB0,0x1)/VenHw(D79DF6B0-EF44-43BD-9797-43E93BCF5FA8)
              Ctrl[^[[1m^[[37m^[[40m3B7^[[0m^[[37m^[[40m] MNP (MAC=A4-BF-01-8D-0D-B0, ProtocolType=0x806, VlanId=0)

      without ANSI it looks like::

        Ctrl[C0] PciRoot(0x11)
          Ctrl[20A] PciRoot(0x11)/Pci(0x0,0x0)
          Ctrl[20B] PciRoot(0x11)/Pci(0x0,0x1)
          Ctrl[20C] PciRoot(0x11)/Pci(0x0,0x2)
          Ctrl[20D] PciRoot(0x11)/Pci(0x0,0x4)
          Ctrl[20E] PciRoot(0x11)/Pci(0x6,0x0)
          Ctrl[20F] Intel(R) I210 Gigabit  Network Connection
            Ctrl[3B5] Intel(R) I210 Gigabit  Network Connection
              Ctrl[3B6] PciRoot(0x11)/Pci(0x6,0x0)/Pci(0x0,0x0)/MAC(A4BF018D0DB0,0x1)/VenHw(D79DF6B0-EF44-43BD-9797-43E93BCF5FA8)
              Ctrl[3B7] MNP (MAC=A4-BF-01-8D-0D-B0, ProtocolType=0x806, VlanId=0)

      - ^[ is an escape char in there--the ANSI control sequences might
        or not might show up (dep on the machine), so we make them
        optional in the regexes

      - we latch to the first mention of something that looks like a mac
        address *MAC(A4BF018D0DB0* and use that

      - note each level adds two spaces of depth

      :returns: dictionary of sets, keyed by macaddress as parsed from
        the output and then moved to lowercase. All values are strings

        >>> {
        >>>     '40a6b78d8898': {'424', 'B3', '2FA', '44D', '423', '42E', '425'},
        >>>     '40a6b79fc4f0': {'3F0', '21C', 'B3', '3F1', '419', '3EF', '3FA'},
        >>>     'a4bf018d0db0': {'B3', '3B7', '3C0', '3B6', '3B5', '20F', '3DF'}
        >>> }

      """

    regex_entry = re.compile("^(?P<level> +)Ctrl\[(\x1b.+40m)?(?P<dh>[0-9A-F]+)(\x1b.+40m)?\] (?P<device_str>.*)$")
    regex_devicestr = re.compile("MAC\((?P<macaddr>[0-9A-Fa-f]+),0x[0-9]+\)/VenHw.*$")

    dh = None
    dhs = []
    level0 = 0
    level = None
    dhs_by_mac = collections.defaultdict(set)
    for line in devtree_output.splitlines():
        m = regex_entry.search(line)
        if not m:
            continue
        dh = m.group("dh")
        level = len(m.group("level"))
        if level == level0:		# no change in level
            if dhs:			# replace current DH in the stack
                dhs.pop()
            dhs.append(dh)
        elif level > level0:		# went up one level, append current
            dhs.append(dh)
        elif level < level0:		# went down in levels
            # the level string gets incremented two spaces for each level
            # and it can decrease in a single shot multiple levels, so
            # calculate how many levels we are up to remove them from the
            # stack
            for i in range((level0 - level) // 2):
                dhs.pop()

        # check now the device string; if it looks like a MAC, report
        # the stack of DHs so far accumulated
        device_str = m.group("device_str")
        m = regex_devicestr.search(device_str)
        if m:
            macaddr = m.group("macaddr")
            dhs_by_mac[macaddr].update(dhs)
        level0 = level

    return { mac.lower(): dhs for mac, dhs in  dhs_by_mac.items() }



def uefi_shell_extract_mac_info(target):
    """
    Generate a map of EFI interfaces


    :param tcfl.tc.target_c target: machine where to operate; must be
      in the EFI shell.

    :returns: a tuple of two dictionaries:

      - *ifaces*: as returned by
        :func:`tcfl.biosl.uefi_ifconfig_l_parse`, which looks like::

           {
             'eth1': {
               '': True,
               'DNS server': '',
               'Media State': 'Media present',
               'default gateway': '0.0.0.0',
               'ipv4 address': '0.0.0.0',
               'mac addr': '00:07:E9:34:8A:AA',
               'name': 'eth1',
               'policy': 'static',
               'subnet mask': '0.0.0.0'
             }
           }


      - dictionary by MAC address (lower case, no colons) of all
      fields we could extract from the DH commands in the EFI shell;
      if available, for example the PCI fields will show as::


        {
          '40a6b78d8898': {
        ...
            'Bus #': 'B8',
            'Device #': '00',
            'Function #': '00',
            'Segment #': '00',
        ...
            'Vendor ID': '8086',
            'Device ID': '1592',
          },
        }


    """
    target.shell.run("cls")
    output = target.shell.run(
        "ifconfig -l", output = True, trim = True)
    ifaces = tcfl.biosl.uefi_ifconfig_l_parse(target, output)
    if not ifaces:
        raise tcfl.tc.failed_e(
            "UEFI's `ifconfig -l` didn't find any network interfaces"
            " (this usually means EFI networking is disabled)" ,
            {
                "output": output,
                "target": target,
            })

    # ifaces is a simple parsing of the output by interface
    #
    ## {
    ##     'eth0': {
    ##         '': True,
    ##         '  Routes (0 entries)': '',
    ##         'DNS server': '',
    ##         'Media State': 'Media disconnected',
    ##         'default gateway': '0.0.0.0',
    ##         'ipv4 address': '0.0.0.0',
    ##         'mac addr': '40:A6:B7:8D:9F:28',
    ##         'name': 'eth0',
    ##         'policy': 'static',
    ##         'subnet mask': '0.0.0.0'
    ##     },
    ##     'eth1': {
    ##         '': True,
    ##         '  Routes (0 entries)': '',
    ##         'DNS server': '',
    ##         'Media State': 'Media present',
    ##         'default gateway': '0.0.0.0',
    ##         'ipv4 address': '0.0.0.0',
    ##         'mac addr': '00:07:E9:34:8A:AA',
    ##         'name': 'eth1',
    ##         'policy': 'static',
    ##         'subnet mask': '0.0.0.0'
    ##     }
    ## }
    #
    # make each interface configure w/ DHCP, see what IPs they
    # get; the one that gets an IP address which resolves to the name of hte SUT is the main IT connection

    # mac here is lower case, no :, matching the mac_data bus info
    # we'll calculate later
    mac_to_ifname = {}
    ifname_to_mac = {}
    for ifname, ifdata in ifaces.items():
        mac_addr = ifdata.get('mac addr', "").lower()
        if mac_addr:
            target.report_info(
                f"EFI found mac {mac_addr} for {ifname}", dlevel = -1)
            mac_to_ifname[mac_addr.lower().replace(":", "")] = ifname
            ifname_to_mac[ifname] = mac_addr.lower().replace(":", "")

    # Use now the EFI shell command dh to get bus information about
    # the macs; this is kinda tricky because there is no direct way to
    # do it. So first we use EFI shell devtree to print the tree of
    # dvices/drivers -> from there find the ones that look like
    # MAC(MACADDR)/HwVenblablah, and query all the device handles in
    # its chain for the device info

    devtree_output = target.shell.run(
        "devtree  # getting device infos to find network interfaces",
        timeout = 400,	# this can be long
        # FIXME: use progress regex
        output = True, trim = True)
    dhs_by_mac = uefi_devtree_extract_dhs_from_mac(devtree_output)

    # dhs_by_mac looks like
    ##  {
    ##    '40a6b78d8898': {'424', 'B3', '2FA', '44D', '423', '42E', '425'},
    ##    '40a6b79fc4f0': {'3F0', '21C', 'B3', '3F1', '419', '3EF', '3FA'},
    ##    'a4bf018d0db0': {'B3', '3B7', '3C0', '3B6', '3B5', '20F', '3DF'}
    ## }
    #
    # note the MAC address is regularized to lower case, no colons

    mac_bus_info = {}
    for macaddr, dhs in dhs_by_mac.items():
        # MACADDR in 001122334455 form
        # DHS is list of handles
        ifname = mac_to_ifname[macaddr]
        mac_bus_info[macaddr] = { "ifname": ifname }
        for dh in dhs:
            target.report_info(f"EFI: getting info for {ifname} MAC {macaddr} DH {dh}")
            dh_output = target.shell.run(
                f"dh -v {dh}  # getting info for {ifname} MAC {macaddr}",
                output = True, trim = True)
            # merge all the fields we get from the different DHs
            mac_bus_info[macaddr].update(uefi_dh_extract(commonl.ansi_strip(dh_output)))

            # the fields we care for most is
            #
            # {
            #   '40a6b78d8898': {
            # ...
            #     'Bus #': 'B8',
            #     'Device #': '00',
            #     'Function #': '00',
            #     'Segment #': '00',
            # ...
            #     'Vendor ID': '8086',
            #     'Device ID': '1592',
            #   },
            # }
            #
            # Which are what we need to identify against our
            #configuration mapping; but let's also make it easy and
            #set the interface name


    return ifaces, mac_bus_info



def uefi_ifconfig_l_parse(target, output):
    """
    Parse the output of UEFI's *ifconfig -l* into a dictionary

    :param tcfl.tc.target_c target: target we parsed this from (for
      reporting)

    :param str output: output of execution *ifconfig -l* which we are
      to parse

    :returns dict: dictionary keyed by interface name with the name of
      each field and its value (with all the ANSI stripped).

    The output of the ifconfig -l command resembles someting like::

      -----------------------------------------------------------------
      name         : eth0
      Media State  : Media disconnected
      policy       : dhcp
      mac addr     : 98:4F:EE:00:3E:7F
      -----------------------------------------------------------------
      name         : eth1
      Media State  : Media disconnected
      policy       : dhcp
      mac addr     : 98:4F:EE:00:3E:80
      ...

    with the following caveats:

      - some fields are multiline (PENDING: parse those properly)

      - a lot of ANSI characters are in the middle (we try to purge
        those)

    """
    ifaces = {}
    recordl = output.split("-----------------------------------------------------------------")
    for record in recordl:
        # cleanup empty lines and stuff, there is a lot of cruft
        # after parsing that the human eye doesn't see
        record = record.strip()
        if not record:
            continue
        lines = record.split("\n")
        data = {}
        for line in lines:
            # very primitive field parsin, won't catch routes and dns
            # servers properly
            line = line.strip()
            if not line:
                continue
            if ':' in line:
                field, value = line.split(":", 1)
                field = commonl.ansi_strip(field.strip())
                value = commonl.ansi_strip(value.strip())
            else:
                field = commonl.ansi_strip(line)
                value = True
            data[field] = value
        iface_name = data.get("name", None)
        if not iface_name:
            target.report_error(
                "WARNING: ignoring entry which has no interface name",
                dict(output = output, data = data))
            continue
        ifaces[iface_name] = data
    return ifaces
