"""Verification suite for Free Claude Code Cloud deployment, security, and authentication."""

import os
import pytest
from starlette.testclient import TestClient

from free_claude_code.config.loader import clear_settings_cache, get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app


@pytest.fixture
def cloud_app(monkeypatch):
    """Construct an isolated cloud-configured ASGI application."""
    monkeypatch.setenv("FCC_CLOUD_DEPLOYMENT", "1")
    monkeypatch.setenv("PROXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "freecc_test_token")
    monkeypatch.setenv("ADMIN_AUTH_TOKEN", "admin_test_token")
    clear_settings_cache()
    settings = get_settings()
    app = build_asgi_app(settings)
    yield app
    clear_settings_cache()


def test_cloud_health_check(cloud_app):
    """Verify /health returns 200 healthy and includes security headers."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"


def test_cloud_admin_unauthorized_rejected(cloud_app):
    """Verify unauthenticated remote requests to /admin are rejected with 401."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")
    response = client.get("/admin")
    assert response.status_code == 401


def test_cloud_admin_invalid_token_rejected(cloud_app):
    """Verify remote requests with invalid token are rejected with 401."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")
    response = client.get("/admin?token=invalid_secret")
    assert response.status_code == 401


def test_cloud_admin_query_token_rejected(cloud_app):
    """Verify remote requests with query-string ?token= are rejected with 401 for security."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")
    response = client.get("/admin?token=admin_test_token")
    assert response.status_code == 401


def test_cloud_admin_header_authentication(cloud_app):
    """Verify x-admin-token header allows access to admin endpoints."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")
    response = client.get("/admin", headers={"x-admin-token": "admin_test_token"})
    assert response.status_code == 200


def test_cloud_admin_cookie_authentication(cloud_app):
    """Verify session cookie allows seamless subsequent /admin navigation."""
    client = TestClient(
        cloud_app,
        base_url="https://cloud-fcc.example.com",
        cookies={"fcc_admin_token": "admin_test_token"},
    )
    response = client.get("/admin")
    assert response.status_code == 200


def test_cloud_admin_bearer_header_authentication(cloud_app):
    """Verify Authorization: Bearer token allows API access to /admin/api/config."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")
    headers = {"Authorization": "Bearer admin_test_token"}
    response = client.get("/admin/api/config", headers=headers)
    assert response.status_code == 200


def test_cloud_proxy_unauthenticated_requests_rejected(cloud_app):
    """Verify /v1 endpoints reject unauthenticated traffic with 401."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")

    # 1. Chat completions without auth
    r_chat = client.post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4o", "messages": []},
    )
    assert r_chat.status_code == 401

    # 2. Messages without auth
    r_msg = client.post(
        "/v1/messages",
        json={"model": "anthropic/claude-3-5-sonnet", "messages": []},
    )
    assert r_msg.status_code == 401


def test_cloud_proxy_invalid_token_rejected(cloud_app):
    """Verify /v1 endpoints reject invalid bearer token with 401."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer bad-token-123"},
        json={"model": "openai/gpt-4o", "messages": []},
    )
    assert response.status_code == 401


def test_cloud_proxy_valid_token_accepted(cloud_app):
    """Verify /v1 endpoints accept valid bearer token and pass to request validation."""
    client = TestClient(cloud_app, base_url="https://cloud-fcc.example.com")
    response = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer freecc_test_token"},
        json={"model": "anthropic/claude-3-5-sonnet", "messages": []},
    )
    # Auth passes! 400 Bad Request indicates validation error (messages cannot be empty)
    assert response.status_code == 400
