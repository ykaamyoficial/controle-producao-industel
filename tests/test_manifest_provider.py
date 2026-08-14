from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.updater.manifest_provider import (
    HttpManifestProvider,
    LocalFileManifestProvider,
    ManifestFetchError,
)


class _FakeResponse:
    def __init__(self, *, status_code: int, payload=None, raise_on_json: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("invalid json")
        return self._payload


class HttpManifestProviderTests(unittest.TestCase):
    def test_rejects_file_scheme_at_construction(self):
        with self.assertRaises(ManifestFetchError):
            HttpManifestProvider("file:///etc/manifest.json")

    def test_rejects_ftp_scheme_at_construction(self):
        with self.assertRaises(ManifestFetchError):
            HttpManifestProvider("ftp://example.com/manifest.json")

    def test_successful_fetch_returns_parsed_json(self):
        response = _FakeResponse(status_code=200, payload={"manifest_schema_version": 1})
        provider = HttpManifestProvider("https://example.com/manifest.json", http_get=lambda url, timeout: response)
        self.assertEqual(provider.fetch(), {"manifest_schema_version": 1})

    def test_http_error_status_raises(self):
        response = _FakeResponse(status_code=404)
        provider = HttpManifestProvider("https://example.com/manifest.json", http_get=lambda url, timeout: response)
        with self.assertRaises(ManifestFetchError):
            provider.fetch()

    def test_redirect_status_is_treated_as_failure_not_followed(self):
        response = _FakeResponse(status_code=302)
        provider = HttpManifestProvider("https://example.com/manifest.json", http_get=lambda url, timeout: response)
        with self.assertRaises(ManifestFetchError):
            provider.fetch()

    def test_network_exception_raises_manifest_fetch_error(self):
        def failing_get(url, timeout):
            raise ConnectionError("network down")
        provider = HttpManifestProvider("https://example.com/manifest.json", http_get=failing_get)
        with self.assertRaises(ManifestFetchError):
            provider.fetch()

    def test_invalid_json_body_raises(self):
        response = _FakeResponse(status_code=200, raise_on_json=True)
        provider = HttpManifestProvider("https://example.com/manifest.json", http_get=lambda url, timeout: response)
        with self.assertRaises(ManifestFetchError):
            provider.fetch()


class LocalFileManifestProviderTests(unittest.TestCase):
    def test_reads_valid_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps({"a": 1}), encoding="utf-8")
            provider = LocalFileManifestProvider(path)
            self.assertEqual(provider.fetch(), {"a": 1})

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = LocalFileManifestProvider(Path(tmp) / "nope.json")
            with self.assertRaises(ManifestFetchError):
                provider.fetch()

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text("{not json", encoding="utf-8")
            provider = LocalFileManifestProvider(path)
            with self.assertRaises(ManifestFetchError):
                provider.fetch()


if __name__ == "__main__":
    unittest.main()
