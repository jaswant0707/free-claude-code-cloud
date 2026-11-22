"""Comprehensive verification suite for Single-Owner Authentication, Session Security,
and Dual-Boundary Protection in Free Claude Code Cloud.
"""

import time
import pytest
from starlette.testclient import TestClient

from free_claude_code.api.owner_auth import (
    SESSION_COOKIE_NAME,
    create_session_token,
    _login_attempts,
)
from free_claude_code.config.loader import clear_settings_cache, get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

TEST_OWNER_EMAIL = "owner@example.com"
TEST_OWNER_PASSWORD = "SuperSecretPassword123!"
TEST_MASTER_API_TOKEN = "master-api-token-xyz-789"


@pytest.fixture
def owner_app(monkeypatch):
    """Construct an isolated cloud-configured ASGI app with owner credentials."""
    monkeypatch.setenv("FCC_CLOUD_DEPLOYMENT", "1")
    monkeypatch.setenv("OWNER_EMAIL", TEST_OWNER_EMAIL)
    monkeypatch.setenv("OWNER_PASSWORD", TEST_OWNER_PASSWORD)
    monkeypatch.setenv("MASTER_API_TOKEN", TEST_MASTER_API_TOKEN)
    # Clear in-memory rate-limiting
    _login_attempts.clear()
    clear_settings_cache()
    settings = get_settings()
    app = build_asgi_app(settings)
    yield app
    clear_settings_cache()
    _login_attempts.clear()


def test_login_page_renders_for_unauthenticated_user(owner_app):
    """Verify /login renders HTML for unauthenticated browser."""
    client = TestClient(owner_app, base_url="https://cloud.example.com")
    response = client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Free Claude Code Cloud" in response.text
    assert "Sign In" in response.text


def test_login_success_sets_session_cookie(owner_app):
    """Verify valid login returns 200 and sets secure HTTP-only session cookie."""
    client = TestClient(owner_app, base_url="https://cloud.example.com")
    response = client.post(
        "/api/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["email"] == TEST_OWNER_EMAIL

    set_cookie = response.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/" in set_cookie


def test_login_invalid_password_rejected(owner_app):
    """Verify login with invalid password returns 401."""
    client = TestClient(owner_app, base_url="https://cloud.example.com")
    response = client.post(
        "/api/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_login_invalid_email_rejected(owner_app):
    """Verify login with invalid email returns 401."""
    client = TestClient(owner_app, base_url="https://cloud.example.com")
    response = client.post(
        "/api/auth/login",
        json={"email": "attacker@evil.com", "password": TEST_OWNER_PASSWORD},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_login_rate_limiting(owner_app):
    """Verify repeated failed login attempts trigger 429 rate limit."""
    client = TestClient(owner_app, base_url="https://cloud.example.com")
    for _ in range(5):
        resp = client.post(
            "/api/auth/login",
            json={"email": TEST_OWNER_EMAIL, "password": "WrongPassword"},
        )
        assert resp.status_code == 401

    # 6th attempt should be rate limited
    blocked_resp = client.post(
        "/api/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert blocked_resp.status_code == 429
    assert "Too many failed login attempts" in blocked_resp.json()["detail"]


def test_session_status_and_logout(owner_app):
    """Verify /api/auth/session reflecting authentication state and logout clearing cookie."""
    client = TestClient(owner_app, base_url="https://cloud.example.com")

    # Initially unauthenticated
    resp = client.get("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False, "email": None}

    # Log in
    login_resp = client.post(
        "/api/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert login_resp.status_code == 200
    session_token = login_resp.cookies.get(SESSION_COOKIE_NAME)
    assert session_token is not None

    # Check status with session cookie
    auth_client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: session_token},
    )
    status_resp = auth_client.get("/api/auth/session")
    assert status_resp.status_code == 200
    assert status_resp.json() == {"authenticated": True, "email": TEST_OWNER_EMAIL}

    # Log out
    logout_resp = auth_client.post("/api/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"status": "logged_out"}


def test_browser_root_redirects_unauthenticated(owner_app):
    """Verify browser requesting / without session cookie redirects to /login."""
    client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        follow_redirects=False,
    )
    resp = client.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_browser_root_redirects_authenticated_to_admin(owner_app):
    """Verify authenticated browser requesting / redirects to /admin."""
    token = create_session_token(TEST_OWNER_EMAIL)
    client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: token},
        follow_redirects=False,
    )
    resp = client.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"


def test_browser_login_redirects_if_already_authenticated(owner_app):
    """Verify authenticated user visiting /login is redirected to /admin."""
    token = create_session_token(TEST_OWNER_EMAIL)
    client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: token},
        follow_redirects=False,
    )
    resp = client.get("/login")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"


def test_admin_redirects_unauthenticated_browser(owner_app):
    """Verify unauthenticated browser requesting /admin redirects to /login?next=%2Fadmin."""
    client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        follow_redirects=False,
    )
    resp = client.get("/admin", headers={"Accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 307
    assert resp.headers["location"] in ("/login?next=/admin", "/login?next=%2Fadmin")


def test_admin_access_with_session_cookie(owner_app):
    """Verify authenticated owner accesses /admin and /admin/api/config."""
    token = create_session_token(TEST_OWNER_EMAIL)
    client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: token},
    )
    # Admin UI HTML page
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")

    # Admin config API
    api_resp = client.get("/admin/api/config")
    assert api_resp.status_code == 200
    assert "sections" in api_resp.json()


def test_dual_boundary_separation(owner_app):
    """CRITICAL: External API requires MASTER_API_TOKEN and strictly rejects browser session cookie."""
    token = create_session_token(TEST_OWNER_EMAIL)

    # 1. External API with ONLY browser session cookie -> REJECTED (401)
    cookie_client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: token},
    )
    reject_resp = cookie_client.get("/v1/models")
    assert reject_resp.status_code == 401
    assert "Missing proxy authentication token" in reject_resp.json()["detail"]

    # 2. External API with wrong Bearer token -> REJECTED (401)
    wrong_client = TestClient(owner_app, base_url="https://cloud.example.com")
    wrong_resp = wrong_client.get(
        "/v1/models",
        headers={"Authorization": "Bearer wrong-token-123"},
    )
    assert wrong_resp.status_code == 401
    assert "Invalid proxy authentication token" in wrong_resp.json()["detail"]

    # 3. External API with valid Bearer MASTER_API_TOKEN -> ACCEPTED (200)
    valid_bearer_resp = wrong_client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {TEST_MASTER_API_TOKEN}"},
    )
    assert valid_bearer_resp.status_code == 200
    assert "data" in valid_bearer_resp.json()

    # 4. Anthropic endpoint with Anthropic x-api-key header -> ACCEPTED (204 probe)
    valid_api_key_resp = wrong_client.head(
        "/v1/messages",
        headers={"x-api-key": TEST_MASTER_API_TOKEN},
    )
    assert valid_api_key_resp.status_code == 204


def test_tampered_and_expired_session_rejected(owner_app):
    """Verify cryptographically tampered or expired session cookies are rejected."""
    # 1. Tampered token
    valid_token = create_session_token(TEST_OWNER_EMAIL)
    payload_part, _, sig_part = valid_token.partition(".")
    tampered_token = f"{payload_part}.tampered_signature"

    tampered_client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: tampered_token},
    )
    resp = tampered_client.get("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False, "email": None}

    # 2. Expired token
    from free_claude_code.api.owner_auth import _get_signing_key
    import base64
    import json
    import hmac
    import hashlib

    expired_payload = {
        "email": TEST_OWNER_EMAIL,
        "iat": int(time.time()) - 100000,
        "exp": int(time.time()) - 1000,  # expired in the past
        "nonce": "test-nonce",
    }
    payload_json = json.dumps(expired_payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("utf-8").rstrip("=")
    sig = hmac.new(_get_signing_key(), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
    expired_token = f"{payload_b64}.{sig_b64}"

    expired_client = TestClient(
        owner_app,
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: expired_token},
    )
    exp_resp = expired_client.get("/api/auth/session")
    assert exp_resp.status_code == 200
    assert exp_resp.json() == {"authenticated": False, "email": None}


def test_account_lockout_returns_423(owner_app, monkeypatch):
    """Verify active account lockout returns HTTP 423 with time remaining."""
    from free_claude_code.api.owner_auth import AccountLockedError
    import free_claude_code.api.auth_routes as auth_mod

    def mock_locked(email, password):
        raise AccountLockedError(minutes_remaining=12)

    monkeypatch.setattr(auth_mod, "authenticate_owner", mock_locked)
    client = TestClient(owner_app, base_url="https://cloud.example.com")
    resp = client.post(
        "/api/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert resp.status_code == 423
    assert "temporarily locked" in resp.json()["detail"]
    assert "12 minute(s)" in resp.json()["detail"]


def test_database_auth_error_returns_503(owner_app, monkeypatch):
    """Verify database connection failure returns HTTP 503 rather than masking as invalid credentials."""
    from free_claude_code.api.owner_auth import DatabaseAuthError
    import free_claude_code.api.auth_routes as auth_mod

    def mock_db_err(email, password):
        raise DatabaseAuthError("Authentication database service is temporarily unavailable.")

    monkeypatch.setattr(auth_mod, "authenticate_owner", mock_db_err)
    client = TestClient(owner_app, base_url="https://cloud.example.com")
    resp = client.post(
        "/api/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert resp.status_code == 503
    assert "temporarily unavailable" in resp.json()["detail"]
