"""Unit and integration tests for Multi-Universal API Key Management."""

import pytest
from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch

from free_claude_code.api.owner_auth import create_session_token
from free_claude_code.config.loader import clear_settings_cache, get_settings
from free_claude_code.persistence.universal_keys import (
    generate_universal_key,
    hash_key,
    is_universal_key_format,
    verify_universal_key,
    invalidate_universal_key_cache,
    _KEY_VERIFY_CACHE,
)
from free_claude_code.runtime.bootstrap import build_asgi_app

API_TOKEN = "test-master-api-token-999"
ADMIN_TOKEN = "test-admin-secret-token-888"
OWNER_EMAIL = "admin@example.com"
OWNER_PASSWORD = "VerySecurePassword!987"


@pytest.fixture
def uk_app(monkeypatch):
    """Construct an ASGI application with cloud settings enabled."""
    monkeypatch.setenv("FCC_CLOUD_DEPLOYMENT", "1")
    monkeypatch.setenv("PROXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("MASTER_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("ADMIN_AUTH_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("OWNER_PASSWORD", OWNER_PASSWORD)
    clear_settings_cache()
    invalidate_universal_key_cache()
    settings = get_settings()
    app = build_asgi_app(settings)
    yield app
    clear_settings_cache()
    invalidate_universal_key_cache()


# ==============================================================================
# 1. Cryptography and Format Tests
# ==============================================================================


def test_universal_key_generation_and_hashing():
    mock_client = MagicMock()
    mock_client.is_configured = True
    mock_client.create_universal_key.return_value = {"id": "test-uuid-1", "name": "Work Laptop"}

    with patch("free_claude_code.persistence.universal_keys.get_supabase_client", return_value=mock_client):
        res = generate_universal_key(
            name="Work Laptop",
            default_model="claude-3-7-sonnet",
            fallback_models=["gemini-2.5-pro"],
            rate_limit_rpm=120,
        )

        raw_key = res["raw_key"]
        prefix = res["key_prefix"]
        key_hash = res["key_hash"]

        assert is_universal_key_format(raw_key)
        assert raw_key.startswith("fcc_uk_")
        assert prefix == f"{raw_key[:14]}..."
        assert key_hash == hash_key(raw_key)
        assert mock_client.create_universal_key.called


def test_universal_key_cache_and_verification():
    mock_client = MagicMock()
    mock_client.is_configured = True
    key_record = {
        "id": "uk-123",
        "name": "Cline Test",
        "is_active": True,
        "default_model": "deepseek-chat",
    }
    mock_client.verify_universal_key.return_value = key_record

    raw_key = "fcc_uk_0123456789abcdef0123456789abcdef0123456789abcdef"
    invalidate_universal_key_cache()

    with patch("free_claude_code.persistence.universal_keys.get_supabase_client", return_value=mock_client):
        # 1st call: DB hit
        v1 = verify_universal_key(raw_key)
        assert v1 is not None
        assert v1["id"] == "uk-123"
        assert mock_client.verify_universal_key.call_count == 1

        # 2nd call: Cache hit (no DB call)
        v2 = verify_universal_key(raw_key)
        assert v2["id"] == "uk-123"
        assert mock_client.verify_universal_key.call_count == 1

        # Invalidate cache
        invalidate_universal_key_cache()
        v3 = verify_universal_key(raw_key)
        assert v3["id"] == "uk-123"
        assert mock_client.verify_universal_key.call_count == 2


# ==============================================================================
# 2. Strict Dual-Boundary Isolation Tests
# ==============================================================================


def test_universal_key_strictly_rejected_on_admin_routes(uk_app):
    """Universal keys (fcc_uk_*) MUST return 401 on /admin and /admin/api/*."""
    client = TestClient(uk_app, base_url="https://cloud.example.com")
    raw_key = "fcc_uk_0123456789abcdef0123456789abcdef0123456789abcdef"

    # Bearer header
    res1 = client.get(
        "/admin/api/config",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert res1.status_code == 401

    # x-admin-token header
    res2 = client.get(
        "/admin/api/status",
        headers={"x-admin-token": raw_key},
    )
    assert res2.status_code == 401


def test_admin_token_strictly_rejected_on_proxy_routes(uk_app):
    """Admin token (ADMIN_TOKEN) MUST return 401 on /v1/*."""
    client = TestClient(uk_app, base_url="https://cloud.example.com")

    res = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert res.status_code == 401


# ==============================================================================
# 3. Universal Gateway Authentication via fcc_uk_*
# ==============================================================================


def test_proxy_auth_allows_valid_universal_key(uk_app):
    """A valid, active Universal Key is accepted on proxy endpoints like /v1/models."""
    client = TestClient(uk_app, base_url="https://cloud.example.com")
    raw_key = "fcc_uk_0123456789abcdef0123456789abcdef0123456789abcdef"

    key_record = {
        "id": "key-uuid-99",
        "name": "Integration Test Key",
        "is_active": True,
        "default_model": None,
    }

    with patch("free_claude_code.persistence.universal_keys.verify_universal_key", return_value=key_record):
        # 1. Bearer header on standard proxy route
        res1 = client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert res1.status_code == 200

        # 2. x-api-key header on Anthropic routes
        res2 = client.head(
            "/v1/messages",
            headers={"x-api-key": raw_key},
        )
        assert res2.status_code == 204


def test_proxy_auth_rejects_inactive_universal_key(uk_app):
    """A revoked or inactive Universal Key must return 401."""
    client = TestClient(uk_app, base_url="https://cloud.example.com")
    raw_key = "fcc_uk_0123456789abcdef0123456789abcdef0123456789abcdef"

    with patch("free_claude_code.persistence.universal_keys.verify_universal_key", return_value=None):
        res = client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert res.status_code == 401


# ==============================================================================
# 4. Admin CRUD Endpoints for Universal Keys
# ==============================================================================


def test_admin_universal_keys_crud(uk_app):
    """Admin can list, create, toggle, and delete universal keys."""
    client = TestClient(uk_app, base_url="https://cloud.example.com")
    admin_headers = {"x-admin-token": ADMIN_TOKEN}

    mock_client = MagicMock()
    mock_client.is_configured = True
    mock_client.list_universal_keys.return_value = [
        {
            "id": "uk-1",
            "name": "Laptop Key",
            "key_prefix": "fcc_uk_12345678",
            "is_active": True,
            "total_requests": 15,
        }
    ]
    mock_client.create_universal_key.return_value = {
        "id": "uk-2",
        "name": "Mobile Key",
        "key_prefix": "fcc_uk_87654321",
        "is_active": True,
    }
    mock_client.toggle_universal_key.return_value = True
    mock_client.delete_universal_key.return_value = True

    with patch("free_claude_code.api.universal_keys_routes.get_supabase_client", return_value=mock_client), \
         patch("free_claude_code.persistence.universal_keys.get_supabase_client", return_value=mock_client):

        # 1. GET list
        res_list = client.get("/admin/api/universal-keys", headers=admin_headers)
        assert res_list.status_code == 200
        assert len(res_list.json()["keys"]) == 1

        # 2. POST create
        res_create = client.post(
            "/admin/api/universal-keys",
            headers=admin_headers,
            json={
                "name": "Mobile Key",
                "default_model": "claude-3-7-sonnet",
                "rate_limit_rpm": 60,
            },
        )
        assert res_create.status_code == 200
        data = res_create.json()
        assert data["status"] == "created"
        assert data["raw_key"].startswith("fcc_uk_")

        # 3. POST toggle
        res_toggle = client.post(
            "/admin/api/universal-keys/uk-1/toggle",
            headers=admin_headers,
            json={"is_active": False},
        )
        assert res_toggle.status_code == 200
        assert res_toggle.json()["is_active"] is False

        # 4. DELETE
        res_del = client.delete(
            "/admin/api/universal-keys/uk-1",
            headers=admin_headers,
        )
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "deleted"
