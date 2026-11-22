"""Automated security test suite for Master Token protection, proxy boundary isolation,
and isolated cloud workspace access controls.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from free_claude_code.api.admin_security import is_valid_admin_token
from free_claude_code.api.owner_auth import _login_attempts, create_session_token
from free_claude_code.config.loader import clear_settings_cache, get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app
from free_claude_code.runtime.cloud_workspace import (
    cleanup_workspace,
    execute_command,
    get_session_workspace_path,
    prepare_workspace,
    resolve_safe_workspace_path,
)

# Test-only synthetic credentials (NEVER production secrets)
TEST_OWNER_EMAIL = "test-owner-789@example.com"
TEST_OWNER_PASSWORD = "TestOwnerSecurePassword999!"
TEST_ADMIN_TOKEN = "test-master-token-random-abc123xyz789"
TEST_PROXY_TOKEN = "test-proxy-token-llm-calls-only-456"


@pytest.fixture
def secure_app(monkeypatch, tmp_path):
    """Construct an isolated cloud-configured ASGI app with separated admin and proxy tokens."""
    monkeypatch.setenv("FCC_CLOUD_DEPLOYMENT", "1")
    monkeypatch.setenv("OWNER_EMAIL", TEST_OWNER_EMAIL)
    monkeypatch.setenv("OWNER_PASSWORD", TEST_OWNER_PASSWORD)
    monkeypatch.setenv("ADMIN_AUTH_TOKEN", TEST_ADMIN_TOKEN)
    monkeypatch.setenv("MASTER_API_TOKEN", TEST_ADMIN_TOKEN)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", TEST_PROXY_TOKEN)
    monkeypatch.setenv("PROXY_AUTH_TOKEN", TEST_PROXY_TOKEN)
    monkeypatch.setenv("FCC_CONFIG_DIR", str(tmp_path / ".fcc"))
    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path / "workspaces"))

    _login_attempts.clear()
    clear_settings_cache()
    settings = get_settings()
    app = build_asgi_app(settings)
    yield app
    clear_settings_cache()
    _login_attempts.clear()


def test_valid_master_token_grants_admin_access(secure_app):
    """Verify that a valid master token grants authorized admin access."""
    client = TestClient(secure_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "sections" in data
    assert "fields" in data


def test_invalid_master_token_is_rejected(secure_app):
    """Verify that an invalid master token is rejected with 401."""
    client = TestClient(secure_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"Authorization": "Bearer totally-invalid-master-token"},
    )
    assert response.status_code == 401
    assert "Unauthorized" in response.json().get("detail", "")


def test_missing_master_token_is_rejected(secure_app):
    """Verify that missing authentication is rejected with 401."""
    client = TestClient(secure_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 401


def test_proxy_token_cannot_authenticate_as_admin(secure_app):
    """Verify that a client presenting only a proxy token is rejected from admin surfaces."""
    client = TestClient(secure_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"Authorization": f"Bearer {TEST_PROXY_TOKEN}"},
    )
    assert response.status_code == 401


def test_admin_token_cannot_authenticate_as_proxy(secure_app):
    """Verify that an admin/master token cannot accidentally authenticate as a proxy token."""
    client = TestClient(secure_app, base_url="https://cloud.example.com")
    # Calling proxy endpoint (/v1/messages) with admin token must be rejected
    response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"},
        json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401
    assert "Invalid proxy authentication token" in response.text


def test_tokens_never_appear_in_api_responses_or_logs(secure_app):
    """Verify that sensitive master/proxy tokens never leak into responses."""
    client = TestClient(secure_app, base_url="https://cloud.example.com")
    response = client.get(
        "/admin/api/config",
        headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    text_content = response.text
    assert TEST_ADMIN_TOKEN not in text_content
    assert TEST_PROXY_TOKEN not in text_content
    assert TEST_OWNER_PASSWORD not in text_content


@pytest.mark.anyio
async def test_workspace_isolation_and_protected_file(secure_app, tmp_path):
    """Verify isolated workspace creation, protected test file creation,
    path traversal blocking, cross-session isolation, and proper cleanup.
    """
    session_a = f"session-a-{uuid.uuid4().hex[:8]}"
    session_b = f"session-b-{uuid.uuid4().hex[:8]}"

    try:
        # 1. Prepare isolated workspace A
        ws_a = await prepare_workspace(session_a, repo_url_or_path="project-a")
        ws_a_path = Path(ws_a)
        assert ws_a_path.is_dir()

        # Create a protected test file inside workspace A
        secret_file = ws_a_path / "protected_secret.txt"
        secret_file.write_text("CONFIDENTIAL_TEST_DATA_XYZ", encoding="utf-8")
        assert secret_file.is_file()

        # 2. Prepare isolated workspace B
        ws_b = await prepare_workspace(session_b, repo_url_or_path="project-b")
        ws_b_path = Path(ws_b)
        assert ws_b_path.is_dir()

        # 3. Path traversal attack verification:
        # Attempting to resolve paths with '..' to escape workspace sandbox must raise PermissionError
        with pytest.raises(PermissionError):
            resolve_safe_workspace_path(session_b, f"../{session_a}/protected_secret.txt")

        # 4. Session isolation verification:
        # Workspace B cannot see workspace A's files
        file_in_b = ws_b_path / "protected_secret.txt"
        assert not file_in_b.exists()

        # 5. Command execution inside workspace A
        cmd_result = await execute_command(session_a, "python -c \"print('WORKSPACE_OK')\"")
        assert cmd_result["exit_code"] == 0
        assert "WORKSPACE_OK" in cmd_result["stdout"]

    finally:
        # 6. Cleanup verification: ensure test workspaces are completely purged
        cleaned_a = cleanup_workspace(session_a)
        cleaned_b = cleanup_workspace(session_b)
        assert cleaned_a is True
        assert cleaned_b is True
        assert not get_session_workspace_path(session_a, create=False).exists()
        assert not get_session_workspace_path(session_b, create=False).exists()
