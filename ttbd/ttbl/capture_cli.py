#! /usr/bin/python3
#
# Copyright (c) 2020 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
import datetime
import json
import numbers
import signal
import sys
import time


def main(outputfilename, sample_function, xlat, *args,
         period_s = 1, **kwargs):
    r"""
    Shell to call sampling functions and report as JSON

    This is a simple wrapper that allows quickly implementing a
    program that will call a function that will gather values from
    anywhere and report it as a list of JSON records (as described in
    :mod:`ttbl.capture`).

    >>> [
    >>>     {
    >>>         "timestamp": "YYYYMMDDHHMMSS",  # UTC
    >>>         "sequence": MONOTONIC-COUNT,
    >>>         "raw":  { <DATA> },
    >>>         "field1":  VAL1,
    >>>         "field2":  VAL2,
    >>>         ...
    >>>     },
    >>>     ...
    >>> ]

    Each *period_s*, *sample_function* is called and it returns a dict
    of values (and maybe errors). Those values are reported in the
    *raw* entry of the record.

    The *xlat* function is called next to take some of that raw data
    and transform it into upper fields *field1*, *field2*... etc (that
    might be more common or cooked, like for example in an agreed set
    of units)

    When the script receives SIGTERM, it properly terminates the JSON
    output and closes the file.

    :param str outputfilename: where to dump the JSON output
    :param callable xlat: function to translate records; receives two
      dictionaries:

        - *destination*: dictionary where to place translated records,
          just set them there:

        - *raw*: dictionary of data returned by *sample_function*

      >>> def xlat(destination, raw):
      >>>     destination['field1'] = raw['fielda'] / raw['fieldb']

    :param callable sample_function: function that samples the data
      source; receives *\*args* and *\*\*kwargs*.

      Returns two dictionaries:

      - *data*: a dictionary of sampled values
      - *errors*: *None* or a dictionary describing an error condition

    :param float period_s: (optional; default 1s) sampling period (in
      seconds)
    """
    assert isinstance(outputfilename, str)
    assert callable(xlat)
    assert callable(sample_function)
    assert isinstance(period_s, numbers.Real) and period_s > 0

    # SIGTERM will just exit and we'll print proper JSON
    def _sigterm(signum, _b):
        # Note testcases rely on this message to see we terminated
        # properly or not (tests/test_capture_*)
        sys.stderr.write("INFO: signalled %d, flushing!\n" % signum)
        raise SystemExit

    signal.signal(signal.SIGINT, _sigterm)
    signal.signal(signal.SIGQUIT, _sigterm)
    signal.signal(signal.SIGTERM, _sigterm)

    # Main loop, keep reading power until we stop
    first = True
    with open(outputfilename, "w") as of:
        try:
            of.write("[\n")
            ts0 = time.time()
            sequence = 0
            while True:
                ts = time.time()
                if ts - ts0 < period_s:
                    time.sleep(period_s)
                    ts = time.time()
                ts0 = ts
                print(f"INFO: calling sample function @{ts}", file = sys.stderr)
                data, errors = sample_function(*args, **kwargs)
                assert isinstance(data, dict), \
                    f"BUG in sampling function {sample_function}:" \
                    f" data returned is not a dict; got {type(data)}"
                assert errors == None or isinstance(errors, dict), \
                    f"BUG in sampling function {sample_function}:" \
                    f" errors returned is not a dict or None;" \
                    f" got {type(errors)}"
                # This output follows the convention dictated in ttbl.capture

                if period_s < 1:
                    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                else:
                    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")

                d = dict(
                    sequence = sequence,
                    timestamp = timestamp,
                    raw = data,
                )
                # Now place the raw data in the dictionary as cooked data
                xlat(d, data)

                if first:
                    first = False
                else:
                    of.write(",\n")
                of.flush()
                json.dump(d, of, indent = 4)
                # flush now, to make sure this gets synced to disk
                of.flush()
                sequence += 1
        except ( SystemExit, KeyboardInterrupt ):
            # ugly hack so we print the "]" to terminate the JSON array when
            # we Ctrl-C or we send SIGTERM -- If I don't catch this then the
            # finally ...won't work -- some detail I am missing.
            pass
        finally:
            # Note testcases rely on this message to see we terminated
            # properly or not (tests/test_capture_*)
            print("INFO: terminating JSON!", file = sys.stderr)
            of.write("\n]")
            of.flush()
