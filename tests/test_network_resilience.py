from __future__ import annotations

import socket
import ssl
import unittest
from unittest.mock import patch

from app.services.network_diagnostics import classify_network_error, friendly_network_message
from app.services.update_checker import check_for_updates


class NetworkResilienceTests(unittest.TestCase):
    def test_ssl_failure_is_classified_and_does_not_escape(self):
        error = ssl.SSLCertVerificationError(1, "certificate verify failed")
        result = check_for_updates(fetch_json=lambda _url, _timeout: (_ for _ in ()).throw(error))
        self.assertFalse(result["update_available"])
        self.assertEqual(result["error_kind"], "ssl_certificate")
        self.assertIn("certificado", result["user_message"].lower())

    def test_timeout_is_classified(self):
        result = check_for_updates(fetch_json=lambda _url, _timeout: (_ for _ in ()).throw(TimeoutError("timed out")))
        self.assertEqual(result["error_kind"], "timeout")

    def test_no_internet_is_classified(self):
        result = check_for_updates(fetch_json=lambda _url, _timeout: (_ for _ in ()).throw(OSError("network unreachable")))
        self.assertEqual(result["error_kind"], "connection")

    def test_invalid_url_error_is_safe(self):
        result = check_for_updates(fetch_json=lambda _url, _timeout: (_ for _ in ()).throw(OSError("invalid URL")))
        self.assertIn("error", result)
        self.assertFalse(result["update_available"])

    def test_friendly_message_never_exposes_ssl_bypass(self):
        self.assertNotIn("desativ", friendly_network_message("ssl_certificate").lower())


if __name__ == "__main__":
    unittest.main()
