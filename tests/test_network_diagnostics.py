from __future__ import annotations

import http.server
import threading
import unittest

from app.services.network_diagnostics import diagnose_update_endpoint


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    captured_headers: dict[str, str] = {}

    def do_GET(self):
        _RecordingHandler.captured_headers = dict(self.headers)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Date", self.date_time_string())
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class DiagnoseUpdateEndpointTests(unittest.TestCase):
    def setUp(self):
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _RecordingHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)

    def test_probes_the_given_url_host_not_github(self):
        result = diagnose_update_endpoint(f"http://127.0.0.1:{self.port}/api/v1/system/health", timeout=3)
        self.assertTrue(result["internet"])
        self.assertTrue(result["update_url"])
        self.assertEqual(result["errors"], [])

    def test_sends_generic_json_accept_header_not_github_vendor_type(self):
        diagnose_update_endpoint(f"http://127.0.0.1:{self.port}/api/v1/system/health", timeout=3)
        accept_header = _RecordingHandler.captured_headers.get("Accept", "")
        self.assertNotIn("github", accept_header.lower())

    def test_unreachable_host_reports_error_without_raising(self):
        result = diagnose_update_endpoint("http://127.0.0.1:1/api/v1/system/health", timeout=1)
        self.assertFalse(result["internet"])
        self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
