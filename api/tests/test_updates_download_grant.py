from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from api.app.core.config import get_settings
from api.app.updates.download_grant import mint_download_grant, verify_download_grant
from api.app.updates.exceptions import DownloadGrantInvalidError


class DownloadGrantTests(unittest.TestCase):
    def setUp(self):
        self._previous = os.environ.get("SECRET_KEY")
        os.environ["SECRET_KEY"] = "local-test-only-secret-key-32-characters-min"
        get_settings.cache_clear()

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("SECRET_KEY", None)
        else:
            os.environ["SECRET_KEY"] = self._previous
        get_settings.cache_clear()

    def test_valid_grant_round_trips(self):
        token = mint_download_grant("2.6.0")
        verify_download_grant(token, expected_version="2.6.0")  # nao deve levantar

    def test_grant_rejected_for_different_version(self):
        token = mint_download_grant("2.6.0")
        with self.assertRaises(DownloadGrantInvalidError):
            verify_download_grant(token, expected_version="9.9.9")

    def test_expired_grant_is_rejected(self):
        token = mint_download_grant("2.6.0", expires_in_seconds=-1)
        with self.assertRaises(DownloadGrantInvalidError):
            verify_download_grant(token, expected_version="2.6.0")

    def test_garbage_token_is_rejected(self):
        with self.assertRaises(DownloadGrantInvalidError):
            verify_download_grant("not-a-real-jwt", expected_version="2.6.0")

    def test_normal_access_token_is_not_accepted_as_grant(self):
        from api.app.modules.auth.tokens import create_access_token

        access_token, _expires_at, _jti = create_access_token(user_id=1)
        with self.assertRaises(DownloadGrantInvalidError):
            verify_download_grant(access_token, expected_version="2.6.0")

    def test_grant_is_not_accepted_as_access_token(self):
        from api.app.modules.auth.tokens import decode_access_token
        from api.app.core.exceptions import AuthenticationError

        grant = mint_download_grant("2.6.0")
        with self.assertRaises(AuthenticationError):
            decode_access_token(grant)


if __name__ == "__main__":
    unittest.main()
