#! /usr/bin/python3
#
# Copyright (c) 2021 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
A simple mixed-radix to integer (and back) converter

References:

- Knuth's Algorith M

- https://en.wikipedia.org/wiki/Mixed_radix

- https://charlesreid1.github.io/lets-generate-permutations.html

- Example: https://github.com/Miladiouss/MixedRadix
"""
import collections
import collections.abc
import commonl
import itertools
import pprint
import random

class mrn_c(object):
    """Mixed-radix-number-to-decimal and back conversor

    :param axes: digits this mixed radix number will have (digitN,
      digitN-1...digit2, digit1, digit0); each
      digit entry is an interable describing each digit (and it
      can be anything)

    Examples:

      - >>> mrn_c("ABCD", 'abcdef', '01234')

        would compose digits whose digits would be things like 4bD

      - >>> mrn_c([ 'red', 'green', 'blue' ], [ 0, 1, 2 ], "ABC")

        would yield::

          ['red', 0, 'A']
          ['red', 0, 'B']
          ['red', 0, 'C']
          ['red', 1, 'A']
          ['red', 1, 'B']
          ['red', 1, 'C']
          ['red', 2, 'A']
          ['red', 2, 'B']
          ['red', 2, 'C']
          ['green', 0, 'A']
          ['green', 0, 'B']
          ['green', 0, 'C']
          ['green', 1, 'A']
          ['green', 1, 'B']
          ['green', 1, 'C']
          ['green', 2, 'A']
          ['green', 2, 'B']
          ['green', 2, 'C']
          ['blue', 0, 'A']
          ['blue', 0, 'B']
          ['blue', 0, 'C']
          ['blue', 1, 'A']
          ['blue', 1, 'B']
          ['blue', 1, 'C']
          ['blue', 2, 'A']
          ['blue', 2, 'B']
          ['blue', 2, 'C']


    **Implementation details**

    The way to make it is basically a polynomial algorithm; for
    example, decimal 267 is::

         2 * 10 * 10
      +       6 * 10
      +            7

    which if i is the digit (eg: 2, 6, 7) multiplied by the
    product of the previous bases/radixes (eg: 10 for digit #1, 10
    also for digit number #0).

    So if a number with whose radixes for digit #s are 10, 3, and
    5, thus valid digits are ABCDEFGHIK for digit2, xyz for digit1
    and 01234 for digit0 (with digit order being 210). Converting
    Cy4 to decimal would be 39::

         C (ordinal 2)   2 * 3 * 5
         y (ordinal 1) +     1 * 5
         4 (ordinal 4) +         4

    Conversely, to convert 39 to that mixed-radix-number we would
    do integer division for digit#2 and take the reminder::

      39 // (3 * 5) = 2 -> digit2 is 2, ordinal for C
      39 % (3 * 5) = 9

      9 // 5 = 1        -> digit1 is 1, ordinal for y
      9 % 5 = 4

      4                 -> digit0 is 4, ordinal for 4

    """
    def __init__(self, *digits):
        #commonl.assert_list_of_types(axes, "axes", "axis", [ str, tuple, list ] )

        # two arrays for fast calculation, one that has each digit
        # list and another that has the bases/radix for each.
        # Note that internally indexing is reversed: digit0 from the
        # command line is to the rightmost, where internall it is N
        #
        # Also calculates the maximum number of integers we can
        # represent with this mr number, which is basically the
        # permutations.
        self.digit = collections.OrderedDict()
        self.base = collections.OrderedDict()
        axis_count = 0
        self._max_integer = 1
        for values in digits:
            assert isinstance(values, collections.abc.Iterable), \
                f"digit #{axis_count}: especification has to be iterable"
            # check like this because the digit list shall be short
            if not isinstance(values, set):	# no repetirions on sets
                assert all(values.count(i) == 1 for i in values), \
                    f"digit #{axis_count}: especification contains repeated digits"

            self.base[axis_count] = len(values)
            self._max_integer *= self.base[axis_count]
            self.digit[axis_count] = list(values)
            axis_count += 1
        # How many digits do we have
        self._digits = len(self.base)

        # Calculated combosed bases/radixes (eg: for digit N that
        # radixN-1 * radix N-2 * ... * radix2 * radix1 * radix0)
        self._Bi = collections.OrderedDict()
        bases = list(self.base.values())
        for i in range(self._digits):
            digit_number = self._digits - i
            self._Bi[i] = 1
            for cnt in range(i + 1, self._digits):
                self._Bi[i] *= bases[cnt]

    def _digit_ordinal(self, i, digit):
        # produces the order of this digit on the list of digits
        #
        # eg:
        #
        # - in the list 012345, the ordinal of 3 is #3
        # - in the list 52325, the ordinal of 3 is #2
        return self.digit[i].index(digit)

    def max_integer(self):
        """
        Return the maximum integer that can be encoded with the digits.
        """
        return self._max_integer


    def digits(self):
        """
        Return how many digits this mixed-radix object has

        :return int: number of digits
        """
        return self._digits


    def to_integer(self, number):
        """
        Convert a multi-radix number to integer

        :param list number: multi-radix-number to convert

        :return int: integer in base 10
        """
        assert isinstance(number, collections.abc.Iterable)

        count = 0
        integer = 0
        for digit in number:
            digit_number = count
            integer += self._digit_ordinal(digit_number, digit) * self._Bi[digit_number]
            count += 1
        return integer


    def from_integer(self, integer):
        """
        Convert integer to a multiple-radix-number

        >>>

        :param int integer: integer to conver to multi-radix-number

        :return list: list of digits composing the multi-radix-number
          corresponding to integer
        """
        assert isinstance(integer, int)
        r = integer
        l = []
        for i in range(self._digits):
            Bi = self._Bi[i]
            d = int(r // Bi)
            r = r % Bi
            if d >= self.base[i]:
                raise ValueError(
                    f"integer {integer} is too large to be represented with"
                    " given digits")
            digit = self.digit[i][d]
            l.append(digit)
        return l



if __name__ == "__main__":

    import unittest

    vectors = [
        {
            'mrn': mrn_c(
                [ 'AA', 'BB', 'CC', 'DD', 'EE' ],
                [ 'aaa', 'bbb', 'ccc' ],
                [ '11', '22', '33', '44', '55', '66' ],
            ),
            'values': [
                ( 0, [ 'AA', 'aaa', '11' ] ),
                ( 89, [ 'EE', 'ccc', '66' ] ),
            ]
        },

        {
            'mrn': mrn_c(
                [ 'red', 'green', 'blue' ],
                "abcdefghijklmno",
                [
                    { 'A': 1 },
                    { 'B': 2 },
                    { 'C': 3 },
                ],
            ),
            'values': [
                ( 0, [ 'red', 'a', { 'A': 1 } ] ),
                ( 134, [ 'blue', 'o', { 'C': 3 } ] ),
            ]
        },

    ]

    class _test(unittest.TestCase):

        def _run_vector(self, vector):
            mrn = vector['mrn']
            values = vector['values']
            for value in values:
                integer = value[0]
                number = value[1]
                self.assertEqual(integer, mrn.to_integer(number))
                self.assertEqual(number, mrn.from_integer(integer))

        def test_0(self):
            self._run_vector(vectors[0])

        def test_1(self):
            self._run_vector(vectors[1])


    mrn =  mrn_c(
        [ 'AA', 'BB', 'CC', 'DD', 'EE' ],
        [ 'aaa', 'bbb', 'ccc' ],
        [ '11', '22', '33', '44', '55', '66' ],
    )
    for i in range(mrn.max_integer()):
        print(f"DEBUG i {i} mrn {mrn.from_integer(i)}")

    mrn = mrn_c([ 'red', 'green', 'blue' ], [ 0, 1, 2 ], "ABC")
    for i in range(mrn.max_integer()):
        print(f"DEBUG i {i} mrn {mrn.from_integer(i)}")

    unittest.main()

