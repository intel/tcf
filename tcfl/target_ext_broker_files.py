#! /usr/bin/python2
#
# Copyright (c) 2017 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
"""
Copy files from and to the server's user storage area
-----------------------------------------------------

"""

import tc

class broker_files(tc.target_extension_c):
    """\
    Extension to :py:class:`tcfl.tc.target_c` to run methods to manage
    the files available in the target broker for the current logged in
    use.

    Use as:

    >>> files = target.broker_files.list()
    >>> target.broker_files.upload(REMOTE, LOCAL)
    >>> target.broker_files.dnload(REMOTE, LOCAL)
    >>> target.broker_files.delete(REMOTE)

    Note these files are, for example:

    - images for the server to flash into targets (usually handled with
      the :class:`tcfl.target_ext_images.images` extension)

    - copying specific log files from the server (eg: downloading TCP
      dump captures form *tcpdump* as done by the
      :class:`conf_00_lib.vlan_pci` network element).

    - the storage area is commong to *all* targets of the server for
      each user, thus multiple test cases running in parallel can
      access it at the same time. Use the testcase's hash to safely
      namespace:

      >>> tc_hash = self.kws['tc_hash']
      >>> target.broker_files.upload(tc_hash + "-NAME", LOCAL)

    Presence of the *broker_file* attribute in a target indicates this
    interface is supported.

    """

    def upload(self, remote, local):
        """
        Upload a local file to a remote name

        :param str remote: name in the server
        :param str local: local file name
        """
        self.target.report_info('uploading %s -> %s'
                                % (local, remote), dlevel = 2)
        self.target.rtb.rest_tb_file_upload(remote, local)
        self.target.report_info('uploaded %s -> %s'
                                % (local, remote), dlevel = 1)

    def dnload(self, remote, local):
        """
        Download a file to a local file name

        :param str remote: name of the file to download in the server
        :param str local: local file name
        """
        self.target.report_info('downloading %s -> %s'
                                % (remote, local), dlevel = 2)
        self.target.rtb.rest_tb_file_dnload(remote, local)
        self.target.report_info('downloaded %s -> %s'
                                % (remote, local), dlevel = 1)

    def delete(self, remote):
        """
        Delete a remote file

        :param str remote: name of the file to remove from the server
        """
        self.target.report_info('deleting %s' % remote, dlevel = 2)
        self.target.rtb.rest_tb_file_delete(remote)
        self.target.report_info('deleted %s' % remote, dlevel = 1)

    def list(self):
        """
        List available files and their MD5 sums
        """
        self.target.report_info('listing', dlevel = 2)
        lst = self.target.rtb.rest_tb_file_list()
        self.target.report_info('listed', dlevel = 1)
        return lst
