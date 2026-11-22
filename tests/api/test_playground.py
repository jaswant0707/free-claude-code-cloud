"""Unit and integration tests for Persistent AI Model Test Playground."""

import pytest
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from free_claude_code.config.loader import clear_settings_cache, get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

ADMIN_TOKEN = "test-admin-secret-token-888"
OWNER_EMAIL = "admin@example.com"
OWNER_PASSWORD = "VerySecurePassword!987"


@pytest.fixture
def pg_app(monkeypatch):
    """Construct an ASGI application with cloud settings enabled."""
    monkeypatch.setenv("FCC_CLOUD_DEPLOYMENT", "1")
    monkeypatch.setenv("PROXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_AUTH_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("OWNER_PASSWORD", OWNER_PASSWORD)
    clear_settings_cache()
    settings = get_settings()
    app = build_asgi_app(settings)
    yield app
    clear_settings_cache()


def test_playground_requires_admin_auth(pg_app):
    """Playground routes must require loopback/admin authentication."""
    client = TestClient(pg_app, base_url="https://cloud.example.com")

    # Unauthenticated request returns 401
    res1 = client.get("/admin/api/playground/sessions")
    assert res1.status_code == 401

    # Universal key is rejected with 401 on admin playground
    res2 = client.get(
        "/admin/api/playground/sessions",
        headers={"Authorization": "Bearer fcc_uk_0123456789abcdef0123456789abcdef0123456789abcdef"},
    )
    assert res2.status_code == 401


def test_playground_sessions_crud(pg_app):
    """Admin can list, create, get, and delete playground sessions."""
    client = TestClient(pg_app, base_url="https://cloud.example.com")
    admin_headers = {"x-admin-token": ADMIN_TOKEN}

    mock_client = MagicMock()
    mock_client.is_configured = True
    mock_client.list_model_test_sessions.return_value = [
        {
            "id": "sess-1",
            "title": "Sonnet 3.7 Test",
            "selected_model": "claude-3-7-sonnet",
            "created_at": "2026-11-22T10:00:00Z",
        }
    ]
    mock_client.upsert_model_test_session.return_value = {
        "id": "sess-2",
        "title": "Gemini 2.5 Test",
        "selected_model": "gemini-2.5-pro",
    }
    mock_client.get_model_test_session.return_value = {
        "session": {"id": "sess-1", "title": "Sonnet 3.7 Test"},
        "messages": [
            {"id": "msg-1", "role": "user", "content": "Hello!"},
            {"id": "msg-2", "role": "assistant", "content": "Hi there!", "latency_ms": 320},
        ],
    }
    mock_client.delete_model_test_session.return_value = True

    with patch("free_claude_code.api.playground_routes.get_supabase_client", return_value=mock_client):
        # 1. List
        res_list = client.get("/admin/api/playground/sessions", headers=admin_headers)
        assert res_list.status_code == 200
        assert len(res_list.json()["sessions"]) == 1

        # 2. Create
        res_create = client.post(
            "/admin/api/playground/sessions",
            headers=admin_headers,
            json={"title": "Gemini 2.5 Test", "selected_model": "gemini-2.5-pro"},
        )
        assert res_create.status_code == 200
        assert res_create.json()["status"] == "created"
        assert res_create.json()["session"]["title"] == "Gemini 2.5 Test"

        # 3. Get detail
        res_get = client.get("/admin/api/playground/sessions/sess-1", headers=admin_headers)
        assert res_get.status_code == 200
        assert len(res_get.json()["messages"]) == 2

        # 4. Delete
        res_del = client.delete("/admin/api/playground/sessions/sess-1", headers=admin_headers)
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "deleted"


def test_playground_chat_execution(pg_app):
    """Admin can execute a chat prompt in a playground session and persist messages."""
    client = TestClient(pg_app, base_url="https://cloud.example.com")
    admin_headers = {"x-admin-token": ADMIN_TOKEN}

    mock_client = MagicMock()
    mock_client.is_configured = True
    mock_client.get_model_test_session.return_value = {"messages": []}
    mock_client.add_model_test_message.side_effect = lambda **kwargs: kwargs

    # Mock chat handler response
    fake_chat_resp = MagicMock()
    fake_chat_resp.body = b'{"choices":[{"message":{"content":"Test response from assistant"}}],"usage":{"total_tokens":42},"model":"claude-3-7-sonnet"}'

    with patch("free_claude_code.api.playground_routes.get_supabase_client", return_value=mock_client), \
         patch("free_claude_code.api.playground_routes.ChatHandler.create", new_callable=AsyncMock, return_value=fake_chat_resp):

        res = client.post(
            "/admin/api/playground/sessions/sess-1/chat",
            headers=admin_headers,
            json={"prompt": "Write a hello world in Python", "model": "auto"},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["content"] == "Test response from assistant"
        assert data["tokens_used"] == 42
        assert mock_client.add_model_test_message.call_count == 2  # 1 user + 1 assistant
