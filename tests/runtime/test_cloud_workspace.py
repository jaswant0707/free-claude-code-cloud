"""Unit tests for Cloud Workspace Manager.

Verifies:
- Path traversal rejection using is_relative_to
- Repository URL validation (preventing argument and protocol injection)
- Command execution inside isolated workspace
- Output capping at 512 KB
- Command timeout handling
- Workspace cleanup
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
import pytest

from free_claude_code.runtime.cloud_workspace import (
    cleanup_workspace,
    execute_command,
    get_session_workspace_path,
    get_workspaces_root,
    prepare_workspace,
    resolve_safe_workspace_path,
    sanitize_session_id,
    validate_repo_url,
)


def test_sanitize_session_id():
    """Verify session ID sanitization."""
    assert sanitize_session_id("session-123_abc") == "session-123_abc"
    assert sanitize_session_id("../evil/session") == "evilsession"
    with pytest.raises(ValueError, match="Invalid session ID"):
        sanitize_session_id("../..")


def test_path_traversal_prevention(tmp_path, monkeypatch):
    """Verify paths attempting to escape workspace root are blocked."""
    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-session-traversal"

    ws_root = get_session_workspace_path(session_id, create=True)
    assert ws_root.is_dir()

    # Safe subpaths
    safe_path = resolve_safe_workspace_path(session_id, "src/main.py")
    assert safe_path.is_relative_to(ws_root)

    # Traversal attempts
    with pytest.raises(PermissionError, match="Access outside workspace sandbox prohibited"):
        resolve_safe_workspace_path(session_id, "../../etc/passwd")

    with pytest.raises(PermissionError, match="Access outside workspace sandbox prohibited"):
        resolve_safe_workspace_path(session_id, "../other-session")


def test_validate_repo_url():
    """Verify repository URL validation rejects injection vectors and accepts valid URLs."""
    # Valid git URLs
    assert validate_repo_url("https://github.com/user/repo.git") is True
    assert validate_repo_url("https://gitlab.com/group/project") is True
    assert validate_repo_url("http://github.com/user/repo") is True
    assert validate_repo_url("git@github.com:user/repo.git") is True
    assert validate_repo_url("ssh://git@github.com/user/repo.git") is True

    # Injection vectors
    assert validate_repo_url("-oProxyCommand=evil") is False
    assert validate_repo_url("--upload-pack=evil") is False
    assert validate_repo_url("file:///etc/passwd") is False
    assert validate_repo_url("ext::sh -c evil") is False
    assert validate_repo_url("fd::12") is False
    assert validate_repo_url("https://github.com/user/repo; rm -rf /") is False
    assert validate_repo_url("") is False


@pytest.mark.asyncio
async def test_execute_command_in_workspace(tmp_path, monkeypatch):
    """Verify commands execute inside the isolated workspace."""
    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-session-exec"
    await prepare_workspace(session_id)

    # Execute Python one-liner printing text
    cmd = f'"{sys.executable}" -c "print(\'HELLO_WORKSPACE_TEST\')"'
    res = await execute_command(session_id, cmd, timeout=10.0)

    assert res["status"] == "completed"
    assert res["exit_code"] == 0
    assert "HELLO_WORKSPACE_TEST" in res["stdout"]

    cleanup_workspace(session_id)


@pytest.mark.asyncio
async def test_command_output_capping(tmp_path, monkeypatch):
    """Verify commands outputting large volume are capped at 512KB."""
    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-session-capping"
    await prepare_workspace(session_id)

    # Output 1MB of text
    cmd = f'"{sys.executable}" -c "print(\'X\' * (1024 * 1024))"'
    res = await execute_command(session_id, cmd, timeout=15.0)

    assert res["status"] == "completed"
    # Output must be capped around 512KB
    assert len(res["stdout"]) <= (512 * 1024 + 200)
    assert "[Output truncated at 512KB limit]" in res["stdout"]

    cleanup_workspace(session_id)


@pytest.mark.asyncio
async def test_command_timeout(tmp_path, monkeypatch):
    """Verify commands exceeding timeout are killed."""
    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-session-timeout"
    await prepare_workspace(session_id)

    # Sleep longer than timeout
    cmd = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    res = await execute_command(session_id, cmd, timeout=0.5)

    assert res["status"] == "timeout"
    assert res["exit_code"] == -1
    assert "timed out after 0.5 seconds" in res["stderr"]

    cleanup_workspace(session_id)


@pytest.mark.asyncio
async def test_environment_sanitization_in_workspace(tmp_path, monkeypatch):
    """Verify host secrets and API keys are scrubbed and not accessible in workspace execution."""
    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "super_secret_supabase_admin_key")
    monkeypatch.setenv("FCC_ENCRYPTION_KEY", "ultra_sensitive_encryption_key")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_prod_secret_123")

    session_id = "test-session-env-scrub"
    await prepare_workspace(session_id)

    # Subprocess inspects its environment
    cmd = f'"{sys.executable}" -c "import os; print(\'FCC_ENCRYPTION_KEY:\', os.getenv(\'FCC_ENCRYPTION_KEY\')); print(\'GROQ_API_KEY:\', os.getenv(\'GROQ_API_KEY\'))"'
    res = await execute_command(session_id, cmd, timeout=10.0)

    assert res["status"] == "completed"
    assert "FCC_ENCRYPTION_KEY: None" in res["stdout"]
    assert "GROQ_API_KEY: None" in res["stdout"]

    cleanup_workspace(session_id)


@pytest.mark.asyncio
async def test_ssrf_metadata_blocked(tmp_path, monkeypatch):
    """Verify attempts to reach cloud metadata IP 169.254.169.254 are rejected."""
    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-session-ssrf"
    await prepare_workspace(session_id)

    cmd = "curl -s http://169.254.169.254/latest/meta-data/"
    res = await execute_command(session_id, cmd, timeout=5.0)

    assert res["status"] == "blocked"
    assert res["exit_code"] == 1
    assert "169.254.169.254" in res["stderr"]

    cleanup_workspace(session_id)


@pytest.mark.asyncio
async def test_command_cancellation(tmp_path, monkeypatch):
    """Verify cancel_session_command terminates a running process."""
    from free_claude_code.runtime.cloud_workspace import cancel_session_command

    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-session-cancel"
    await prepare_workspace(session_id)

    # Start long running task
    cmd = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    task = asyncio.create_task(execute_command(session_id, cmd, timeout=35.0))
    await asyncio.sleep(0.5)

    cancelled = await cancel_session_command(session_id)
    assert cancelled is True

    res = await task
    assert res["status"] in ("completed", "failed", "error")

    cleanup_workspace(session_id)


def test_cleanup_expired_workspaces(tmp_path, monkeypatch):
    """Verify cleanup_expired_workspaces cleans up old folders."""
    from free_claude_code.runtime.cloud_workspace import cleanup_expired_workspaces

    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    old_dir = tmp_path / "old-session-123"
    old_dir.mkdir()
    # Set mtime to 48 hours ago
    past_time = time.time() - (48 * 3600)
    os.utime(str(old_dir), (past_time, past_time))

    fresh_dir = tmp_path / "fresh-session-456"
    fresh_dir.mkdir()

    cleaned = cleanup_expired_workspaces(max_age_hours=24)
    assert cleaned >= 1
    assert not old_dir.exists()
    assert fresh_dir.exists()


@pytest.mark.asyncio
async def test_background_command_lifecycle(tmp_path, monkeypatch):
    """Verify background commands start immediately and capture logs/status asynchronously."""
    from free_claude_code.runtime.cloud_workspace import (
        start_background_command,
        get_command_task_status,
    )

    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-bg-lifecycle"
    await prepare_workspace(session_id)

    cmd = f'"{sys.executable}" -c "import time; print(\'CHUNK_1\'); time.sleep(0.2); print(\'CHUNK_2\')"'
    res = await start_background_command(session_id, cmd, timeout=10.0)

    assert "task_id" in res
    assert res["status"] == "running"
    task_id = res["task_id"]

    # Poll status until finished
    for _ in range(30):
        status = await get_command_task_status(session_id, task_id)
        if status and status.get("status") in ("completed", "failed"):
            break
        await asyncio.sleep(0.1)

    assert status is not None
    assert status["status"] == "completed"
    assert status["exit_code"] == 0
    assert "CHUNK_1" in status["stdout"]
    assert "CHUNK_2" in status["stdout"]
    assert status["duration"] > 0

    cleanup_workspace(session_id)


@pytest.mark.asyncio
async def test_background_command_duplicate_guard(tmp_path, monkeypatch):
    """Verify starting duplicate command on the same session returns existing task."""
    from free_claude_code.runtime.cloud_workspace import (
        start_background_command,
        cancel_command_task,
    )

    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-bg-dup"
    await prepare_workspace(session_id)

    cmd = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    task1 = await start_background_command(session_id, cmd, timeout=10.0)
    task2 = await start_background_command(session_id, cmd, timeout=10.0)

    assert task1["task_id"] == task2["task_id"]
    await cancel_command_task(session_id, task1["task_id"])
    cleanup_workspace(session_id)


@pytest.mark.asyncio
async def test_background_command_cancellation(tmp_path, monkeypatch):
    """Verify background command cancellation terminates the process."""
    from free_claude_code.runtime.cloud_workspace import (
        start_background_command,
        cancel_command_task,
        get_command_task_status,
    )

    monkeypatch.setenv("FCC_WORKSPACES_DIR", str(tmp_path))
    session_id = "test-bg-cancel"
    await prepare_workspace(session_id)

    cmd = f'"{sys.executable}" -c "import time; time.sleep(15)"'
    task = await start_background_command(session_id, cmd, timeout=20.0)
    task_id = task["task_id"]

    await asyncio.sleep(0.2)
    cancelled = await cancel_command_task(session_id, task_id)
    assert cancelled is True

    status = await get_command_task_status(session_id, task_id)
    assert status is not None
    assert status["status"] == "cancelled"

    cleanup_workspace(session_id)


def test_cloud_timeout_settings_validator(monkeypatch):
    """Verify http_read_timeout is automatically capped to 45s in cloud/Vercel environments."""
    from free_claude_code.config.settings import Settings

    # Local mode: allowed to be 120s
    monkeypatch.delenv("FCC_CLOUD_DEPLOYMENT", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    local_s = Settings(http_read_timeout=120.0)
    assert local_s.http_read_timeout == 120.0

    # Cloud mode: automatically bounded to 45.0s to prevent Vercel 60s hard kill
    monkeypatch.setenv("FCC_CLOUD_DEPLOYMENT", "1")
    cloud_s = Settings(http_read_timeout=120.0)
    assert cloud_s.http_read_timeout == 45.0

