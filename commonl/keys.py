#! /usr/bin/env python3
#
# Copyright (c) 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0
#
import logging
import os
import subprocess

import keyring
import keyring.backend
import keyring.errors

log = logging.getLogger("keyring_keyctl")

class keyring_keyctl_c(keyring.backend.KeyringBackend):
    """
    Simple keyring implementation that stores keys in the kernel's
    session keyring for the current user.

    :param str keyring_id: (optional; defaults to *@s*) id of keyring to
       use; see keyctl(1) and
       https://man7.org/linux/man-pages/man7/keyrings.7.html

    To use:

    >> import keyring
    >> keyring.set_keyring(keyring_keyctl_c())
    """
    def __init__(self, keyring_id: str = "@s"):
        assert isinstance(keyring_id, str)
        keyring.backend.KeyringBackend.__init__(self)
        self.keyring = keyring_id


    @staticmethod
    def _escape_semicolon(service, username):
        # note keyctl doesn't seem to accept semicolons, so we just encode'em
        return service.replace(";", "%3b"), username.replace(";", "%3b")


    def get_password(self, service, username):
        # service TARGET_ID.interfaces.console.paramter_password
        # username username
        # keyctl pipe <type> <desc> <keyring>
        service, username = self._escape_semicolon(service, username)
        try:
            env = dict(os.environ)
            env['LC_ALL'] = 'C'	# ensure we have default messages
            key_id = subprocess.run(
                [ "keyctl", "request", "user", f"{service}:{username}" ],
                check = True, capture_output = True, text = True)
        except subprocess.CalledProcessError as e:
            if 'Required key not available' in e.stderr:
                return None
            raise keyring.errors.KeyringError(
                f"password for '{service}:{username}' does not"
                f" exist in kernel's {self.keyring} keyring: {e.stderr}") from e

        try:
            key = subprocess.run(
                [ "keyctl", "pipe", key_id.stdout.strip() ],
                check = True, text = True, capture_output = True)
            return key.stdout
        except subprocess.CalledProcessError as e:
            raise keyring.errors.KeyringError(
                f"can't get password for '{service}:{username}' from"
                f" kernel's {self.keyring} keyring: {e.stderr}") from e


    def set_password(self, service, username, password):
        # service TARGET_ID.interfaces.console.paramter_password
        # username username
        # type: user (see https://man7.org/linux/man-pages/man7/keyrings.7.html)
        # keyctl padd <type> <desc> <keyring>
        service, username = self._escape_semicolon(service, username)
        try:
            subprocess.run(
                [ "keyctl", "padd", "user", f"{service}:{username}", self.keyring ],
                input = password,
                check = True, capture_output = True, text = True)
        except subprocess.CalledProcessError as e:
            raise keyring.errors.PasswordSetError(
                f"can't set password for '{service}:{username}' in"
                f" kernel's {self.keyring} keyring?: {e.stderr}") from e


    def delete_password(self, service, username):
        # service TARGET_ID.interfaces.console.paramter_password
        # username username
        # keyctl purge [-i] [-p] <type> <desc>
        # keyctl purge user {service}:{username}
        service, username = self._escape_semicolon(service, username)
        subprocess.run(
            [ "keyctl", "purge", "user", f"{service}:{username}" ],
            check = True, capture_output = True)



if __name__ == "__main__":
    import random
    import string

    # https://stackoverflow.com/a/21666621
    def get_random_unicode(length):

        try:
            get_char = unichr
        except NameError:
            get_char = chr

        # Update this to include code point ranges to be sampled
        include_ranges = [
            ( 0x0021, 0x0021 ),
            ( 0x0023, 0x0026 ),
            ( 0x0028, 0x007E ),
            ( 0x00A1, 0x00AC ),
            ( 0x00AE, 0x00FF ),
            ( 0x0100, 0x017F ),
            ( 0x0180, 0x024F ),
            ( 0x2C60, 0x2C7F ),
            ( 0x16A0, 0x16F0 ),
            ( 0x0370, 0x0377 ),
            ( 0x037A, 0x037E ),
            ( 0x0384, 0x038A ),
            ( 0x038C, 0x038C ),
        ]

        alphabet = [
            get_char(code_point) for current_range in include_ranges
                for code_point in range(current_range[0], current_range[1] + 1)
        ]
        return ''.join(random.choice(alphabet) for i in range(length))


    keyring.set_keyring(keyring_keyctl_c())
    k = keyring
    # k = keyring_keyctl_c() also

    for l in range(2, 500):
        username = get_random_unicode(l)
        password = get_random_unicode(l)
        service = get_random_unicode(l)

        k.set_password(service, username, password)
        password_read = k.get_password(service, username)

        assert password == password_read,  \
            f"{l}: password read differs from password:\n" \
            f"password      {password}\n" \
            f"  --{password.encode('unicode-escape')}--\n\n" \
            f"password_read {password_read}\n" \
            f"  --{password_read.encode('unicode-escape')}--\n\n"
        k.delete_password(service, username)

        password_read = k.get_password(service, username)
        assert password_read == None, \
            f"{l}: password-get-after delete; expected none, got {password_read}; service {service} username {username} password {password} "
