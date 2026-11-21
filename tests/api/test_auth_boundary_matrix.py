"""Rigorous Dual-Boundary Authentication and Authorization Matrix Tests.

Covers the complete authentication matrix:
- Valid API token: Allowed on External API, Denied on Admin API.
- Valid Admin token: Denied on External API, Allowed on Admin API.
- Owner session cookie: Denied on External API, Allowed on Admin API.
- Invalid token: Denied on both boundaries.
- Missing token: Denied on both boundaries.
- Default dev token ("freecc"): Strictly prohibited in cloud; safe default in local dev.
- Cross-boundary token reuse and bypass prevention.
- Insecure query string token rejection (?token=).
- Secret non-leakage in error messages.
"""

import os
import pytest
from starlette.testclient import TestClient

from free_claude_code.api.owner_auth import (
    SESSION_COOKIE_NAME,
    create_session_token,
    _login_attempts,
)
from free_claude_code.config.loader import clear_settings_cache, get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

API_TOKEN = "test-api-secret-token-12345"
ADMIN_TOKEN = "test-admin-secret-token-67890"
OWNER_EMAIL = "admin@example.com"
OWNER_PASSWORD = "VerySecurePassword!987"


@pytest.fixture
def matrix_app(monkeypatch):
    """Construct an ASGI application with strictly separate API, Admin, and Owner credentials."""
    monkeypatch.setenv("FCC_CLOUD_DEPLOYMENT", "1")
    monkeypatch.setenv("PROXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("MASTER_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("ADMIN_AUTH_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("OWNER_PASSWORD", OWNER_PASSWORD)
    _login_attempts.clear()
    clear_settings_cache()
    settings = get_settings()
    app = build_asgi_app(settings)
    yield app
    clear_settings_cache()
    _login_attempts.clear()


# ==============================================================================
# 1. External API Boundary Tests
# ==============================================================================


def test_matrix_api_boundary_with_valid_api_token(matrix_app):
    """Valid API token is ALLOWED on External API."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    assert response.status_code == 200
    assert "data" in response.json()


def test_matrix_api_boundary_rejects_admin_token(matrix_app):
    """Admin token is strictly DENIED on External API (cross-boundary isolation)."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 401
    assert "Invalid proxy authentication token" in response.json()["detail"]


def test_matrix_api_boundary_rejects_owner_session_cookie(matrix_app):
    """Owner browser session cookie is DENIED on External API."""
    session_token = create_session_token(OWNER_EMAIL)
    client = TestClient(
        matrix_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: session_token},
    )
    response = client.get("/v1/models")
    assert response.status_code == 401
    assert "Missing proxy authentication token" in response.json()["detail"]


def test_matrix_api_boundary_rejects_admin_cookie(matrix_app):
    """Admin cookie is DENIED on External API."""
    client = TestClient(
        matrix_app,
        base_url="https://cloud.example.com",
        cookies={"fcc_admin_token": ADMIN_TOKEN},
    )
    response = client.get("/v1/models")
    assert response.status_code == 401
    assert "Missing proxy authentication token" in response.json()["detail"]


def test_matrix_api_boundary_rejects_invalid_token(matrix_app):
    """Invalid token is DENIED on External API."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/v1/models",
        headers={"Authorization": "Bearer totally-invalid-token"},
    )
    assert response.status_code == 401
    assert "Invalid proxy authentication token" in response.json()["detail"]


def test_matrix_api_boundary_rejects_missing_token(matrix_app):
    """Missing token is DENIED on External API."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get("/v1/models")
    assert response.status_code == 401
    assert "Missing proxy authentication token" in response.json()["detail"]


def test_matrix_api_boundary_rejects_freecc_in_cloud(matrix_app):
    """Publicly guessable 'freecc' token is strictly DENIED in cloud deployment."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/v1/models",
        headers={"Authorization": "Bearer freecc"},
    )
    assert response.status_code == 401


# ==============================================================================
# 2. Admin API Boundary Tests
# ==============================================================================


def test_matrix_admin_boundary_with_valid_admin_token(matrix_app):
    """Valid Admin token is ALLOWED on Admin API."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    assert "sections" in response.json()


def test_matrix_admin_boundary_with_admin_header(matrix_app):
    """Valid Admin token via x-admin-token is ALLOWED on Admin API."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"x-admin-token": ADMIN_TOKEN},
    )
    assert response.status_code == 200
    assert "sections" in response.json()


def test_matrix_admin_boundary_with_admin_cookie(matrix_app):
    """Valid Admin cookie is ALLOWED on Admin API."""
    client = TestClient(
        matrix_app,
        base_url="https://cloud.example.com",
        cookies={"fcc_admin_token": ADMIN_TOKEN},
    )
    response = client.get("/admin/api/config")
    assert response.status_code == 200


def test_matrix_admin_boundary_with_owner_session_cookie(matrix_app):
    """Valid Owner session cookie is ALLOWED on Admin API."""
    session_token = create_session_token(OWNER_EMAIL)
    client = TestClient(
        matrix_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: session_token},
    )
    response = client.get("/admin/api/config")
    assert response.status_code == 200


def test_matrix_admin_boundary_rejects_api_token(matrix_app):
    """API token is strictly DENIED on Admin API (privilege escalation prevention)."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    assert response.status_code == 401


def test_matrix_admin_boundary_rejects_api_key_header(matrix_app):
    """x-api-key header cannot grant Admin access."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"x-api-key": API_TOKEN},
    )
    assert response.status_code == 401


def test_matrix_admin_boundary_rejects_query_token(matrix_app):
    """Insecure ?token= query parameter is strictly DENIED on Admin API."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(f"/admin/api/config?token={ADMIN_TOKEN}")
    assert response.status_code == 401


def test_matrix_admin_boundary_rejects_invalid_token(matrix_app):
    """Invalid token is DENIED on Admin API."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"Authorization": "Bearer bad-admin-token"},
    )
    assert response.status_code == 401


def test_matrix_admin_boundary_rejects_missing_token(matrix_app):
    """Missing token is DENIED on Admin API."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")
    response = client.get("/admin/api/config")
    assert response.status_code == 401


def test_matrix_error_responses_never_leak_secrets(matrix_app):
    """Error responses must never echo back or reveal secret tokens."""
    client = TestClient(matrix_app, base_url="https://cloud.example.com")

    resp1 = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert ADMIN_TOKEN not in resp1.text

    resp2 = client.get(
        "/admin/api/config",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    assert API_TOKEN not in resp2.text

    resp3 = client.get("/admin/api/config?token=my-secret-attempt")
    assert "my-secret-attempt" not in resp3.text
