#! /usr/bin/python3
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#

import logging

import yaml

#
#
def load(filename):
    """
    Safely load a YAML document

    Follows recomendations from
    https://security.openstack.org/guidelines/dg_avoid-dangerous-input-parsing-libraries.html.

    :param str filename: filename to load
    :raises yaml.scanner: On YAML scan issues
    :raises: any other exception on file access erors
    :return: dictionary representing the YAML document
    """
    try:
        with open(filename, 'r') as f:
            return yaml.safe_load(f)
    except yaml.scanner.ScannerError as e:	# For errors parsing schema.yaml
        logging.error("YAML errror: %s ", e)
        raise

# If pykwalify is installed, then the validate function will work --
# otherwise, it is a stub and we'd warn about it.
try:
    import pykwalify.core
    # Don't print error messages yourself, let us do it
    logging.getLogger("pykwalify.core").setLevel(50)

    e = pykwalify.errors.PyKwalifyException
    def validate(data, schema):
        if not schema:
            return
        c = pykwalify.core.Core(source_data = data, schema_data = schema)
        c.validate(raise_exception = True)

except ImportError as e:
    logging.warning("can't import pykwalify; won't validate YAML (%s)", e)
    e = Exception
    def validate(_data, _schema):
        pass


def load_verify(filename, schema):
    """
    Safely load a testcase/sample yaml document and validate it
    against the YAML schema, returing in case of success the YAML data.

    :param str filename: name of the file to load and process
    :param dict schema: loaded YAML schema (can load with :func:`load`)

    # 'document.yaml' contains a single YAML document.
    :raises yaml.scanner.ScannerError: on YAML parsing error
    :raises pykwalify.errors.SchemaError: on Schema violation error
    """
    # 'document.yaml' contains a single YAML document.
    y = load(filename)
    try:
        validate(y, schema)
    except e as ex:
        ex.filename = filename	# yeah, fugly
        raise
    return y

def parse_verify(data, schema):
    """
    Safely load a testcase/sample yaml document and validate it
    against the YAML schema, returing in case of success the YAML data.

    :param str filename: name of the file to load and process
    :param dict schema: loaded YAML schema (can load with :func:`load`)

    # 'document.yaml' contains a single YAML document.
    :raises yaml.scanner.ScannerError: on YAML parsing error
    :raises pykwalify.errors.SchemaError: on Schema violation error
    """
    y = yaml.safe_load(data)
    validate(y, schema)
    return y
