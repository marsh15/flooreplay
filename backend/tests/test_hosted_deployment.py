"""Hosted browser access and response-cache boundaries."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from flooreplay.api import create_app
from flooreplay.config import Settings, settings


@pytest.mark.parametrize("origin", ["*", "https://*.vercel.app", "https://app.vercel.app/", "https://app.vercel.app/path", "http://app.vercel.app"])
def test_hosted_cors_rejects_broad_or_invalid_origins(origin):
    with pytest.raises(ValidationError):
        Settings(cors_origins=[origin])


def test_hosted_browser_preflight_and_cache_headers(monkeypatch):
    origin = "https://floorreplay.vercel.app"
    monkeypatch.setattr(settings, "cors_origins", [origin])
    client = TestClient(create_app("public"))
    response = client.options("/api/v1/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    denied = client.options("/api/v1/auth/login", headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "POST"})
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    for path in ("/api/v1/health/live", "/api/v1/auth/me"):
        response = client.get(path)
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_readiness_identifies_application_and_compatible_schema(monkeypatch):
    monkeypatch.setattr(settings, 'build_id', 'readiness-identity-test')
    response = TestClient(create_app()).get('/api/v1/health/ready')
    assert response.status_code == 200
    assert response.json() == {'status': 'ready', 'build_id': 'readiness-identity-test', 'schema_revision': '20261001_operations'}
    assert response.headers['X-Request-ID']
