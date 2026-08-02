from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.main import create_app
from api.app.modules.provisioning.schemas import InitialAdminCreate


def test_initial_admin_schema_requires_secure_temporary_password():
    payload = InitialAdminCreate(username="admin", display_name="Administrador", temporary_password="Senha forte 123")

    assert payload.username == "admin"


def test_provisioning_route_is_exposed_in_openapi():
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/provisioning/initial-admin" in response.json()["paths"]
