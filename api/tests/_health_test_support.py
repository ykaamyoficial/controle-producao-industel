from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.health.smoke import SmokeHttpResponse


class SmokeHttpAdapterOverTestClient:
    """Implementa o Protocol SmokeHttpClient sobre um fastapi.testclient.TestClient
    real (ASGI in-process, sem socket TCP real) -- para os testes de integracao
    exercitarem SmokeTestRunner contra a aplicacao FastAPI de verdade + PostgreSQL
    real, sem depender de um servidor uvicorn bindado numa porta."""

    def __init__(self, client: TestClient, base_url: str = "http://testserver"):
        self._client = client
        self.base_url = base_url

    def get(self, path: str, *, timeout: float) -> SmokeHttpResponse:
        response = self._client.get(path)
        try:
            body = response.json()
        except ValueError:
            body = None
        return SmokeHttpResponse(status_code=response.status_code, json_body=body, text=response.text)
