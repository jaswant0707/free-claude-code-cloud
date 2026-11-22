"""Verification tests for Cloud Background Jobs API endpoints."""

import asyncio
import sys
import httpx
import pytest
import pytest_asyncio

from free_claude_code.api.owner_auth import SESSION_COOKIE_NAME, create_session_token
from free_claude_code.config.loader import clear_settings_cache, get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

TEST_OWNER_EMAIL = "jaswanty132@gmail.com"


@pytest_asyncio.fixture
async def async_app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FCC_CLOUD_DEPLOYMENT", "1")
    monkeypatch.setenv("OWNER_EMAIL", TEST_OWNER_EMAIL)
    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    clear_settings_cache()
    settings = get_settings()
    app = build_asgi_app(settings)
    token = create_session_token(TEST_OWNER_EMAIL)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://cloud.example.com",
        cookies={SESSION_COOKIE_NAME: token},
    ) as client:
        yield client
    clear_settings_cache()


@pytest.mark.asyncio
async def test_post_background_job_and_poll(async_app_client):
    """Verify POST /admin/api/code/sessions/{session_id}/jobs returns 202 and status is pollable."""
    session_id = "test-bg-endpoint-session"
    # Launch job
    cmd = f'"{sys.executable}" -c "print(\'API_JOB_OK\')"'
    resp = await async_app_client.post(
        f"/admin/api/code/sessions/{session_id}/jobs",
        json={"command": cmd, "timeout": 15.0},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "running"
    task_id = data["task_id"]

    # Poll status
    for _ in range(40):
        await asyncio.sleep(0.1)
        status_resp = await async_app_client.get(
            f"/admin/api/code/sessions/{session_id}/runs/{task_id}"
        )
        assert status_resp.status_code == 200
        if status_resp.json().get("status") in ("completed", "failed"):
            break

    final_status = status_resp.json()
    assert final_status["status"] == "completed"
    assert "API_JOB_OK" in final_status["stdout"]
    assert final_status["exit_code"] == 0


@pytest.mark.asyncio
async def test_post_exec_with_background_flag(async_app_client):
    """Verify /exec with background=True delegates to background jobs engine."""
    session_id = "test-bg-exec-session"
    cmd = f'"{sys.executable}" -c "print(\'EXEC_BG_OK\')"'
    resp = await async_app_client.post(
        f"/admin/api/code/sessions/{session_id}/exec",
        json={"command": cmd, "timeout": 10.0, "background": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("background") is True
    assert "task_id" in data
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_cancel_background_job(async_app_client):
    """Verify POST /admin/api/code/sessions/{session_id}/runs/{task_id}/cancel cancels task."""
    session_id = "test-bg-cancel-endpoint"
    cmd = f'"{sys.executable}" -c "import time; time.sleep(15)"'
    resp = await async_app_client.post(
        f"/admin/api/code/sessions/{session_id}/jobs",
        json={"command": cmd, "timeout": 20.0},
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    cancel_resp = await async_app_client.post(
        f"/admin/api/code/sessions/{session_id}/runs/{task_id}/cancel"
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["cancelled"] is True

    status_resp = await async_app_client.get(
        f"/admin/api/code/sessions/{session_id}/runs/{task_id}"
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "cancelled"
