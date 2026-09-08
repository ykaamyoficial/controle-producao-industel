from __future__ import annotations

import httpx

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.services.performance_metrics import clear_performance_samples, measure_operation, performance_snapshot


def _settings():
    return DesktopApiSettings(enabled=True, base_url="http://127.0.0.1:8000", connect_timeout=1, read_timeout=1)


def test_phase10_metrics_expose_p95_and_slow_count():
    clear_performance_samples()
    with measure_operation("phase10.fast", screen="Test", action="fast"):
        pass
    with measure_operation("phase10.slow", screen="Test", action="slow"):
        pass
    result = performance_snapshot(screen="Test")
    assert result["count"] == 2
    assert result["p95_ms"] is not None
    assert result["max_ms"] >= result["p50_ms"]


def test_phase10_safe_get_retries_but_write_is_never_repeated():
    calls = {"get": 0, "post": 0}

    def handler(request: httpx.Request):
        key = "get" if request.method == "GET" else "post"
        calls[key] += 1
        if calls[key] == 1:
            raise httpx.ConnectError("temporarily offline")
        return httpx.Response(200, json={"ok": True})

    client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
    assert client.get("/api/v1/production/proposals").status_code == 200
    assert calls["get"] == 2
    try:
        client.post("/api/v1/production/proposals", json_payload={})
    except Exception:
        pass
    assert calls["post"] == 1
    client.close()
