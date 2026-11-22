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
