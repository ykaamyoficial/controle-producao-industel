from __future__ import annotations

import time
import unittest

import httpx

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.services.performance_metrics import current_scope, measure_operation, request_context


class PerformanceMetricsTests(unittest.TestCase):
    def test_operation_context_is_available_to_api_layer(self):
        self.assertIsNone(current_scope())
        with measure_operation("fiscal_refresh", screen="FiscalPage", action="refresh") as scope:
            self.assertEqual(current_scope(), scope)
            context = request_context()
            self.assertEqual(context["operation_id"], scope.operation_id)
            self.assertEqual(context["screen"], "FiscalPage")
            self.assertEqual(context["action"], "refresh")
        self.assertIsNone(current_scope())

    def test_operation_context_is_restored_after_nested_scope(self):
        with measure_operation("outer") as outer:
            with measure_operation("inner") as inner:
                self.assertEqual(current_scope(), inner)
            self.assertEqual(current_scope(), outer)
        self.assertIsNone(current_scope())

    def test_slow_threshold_is_measurement_only(self):
        with measure_operation("slow_operation"):
            time.sleep(0.31)
        self.assertIsNone(current_scope())

    def test_api_request_receives_operation_correlation_headers(self):
        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            for key in ("X-UI-Operation-ID", "X-UI-Screen", "X-UI-Action"):
                seen[key] = request.headers.get(key)
            return httpx.Response(200, json={"status": "healthy"})

        settings = DesktopApiSettings(True, "http://testserver", 1.0, 1.0)
        client = DesktopApiClient(settings, transport=httpx.MockTransport(handler))
        try:
            with measure_operation("fiscal_refresh", screen="FiscalPage", action="refresh") as scope:
                client.get("/api/v1/system/health")
            self.assertEqual(seen["X-UI-Operation-ID"], scope.operation_id)
            self.assertEqual(seen["X-UI-Screen"], "FiscalPage")
            self.assertEqual(seen["X-UI-Action"], "refresh")
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
