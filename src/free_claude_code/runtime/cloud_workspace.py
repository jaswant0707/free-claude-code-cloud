"""Cloud Workspace Manager for Free Claude Code Cloud.

Provides isolated cloud workspaces, git repository cloning, safe path resolution
(preventing traversal attacks via is_relative_to), environment variable sanitization
(preventing host credential leakage), command validation, output capping,
cancellation support, and automatic workspace lifecycle cleanup.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from loguru import logger

from free_claude_code.config.paths import config_dir_path
from free_claude_code.persistence.supabase_client import get_supabase_client

# Maximum output allowed in command results (512 KB) to prevent DoS / memory exhaustion
_MAX_OUTPUT_BYTES: Final[int] = 512 * 1024

# Allowed git URL pattern: https://, http://, git@, ssh://
_SAFE_GIT_URL_REGEX: Final[re.Pattern[str]] = re.compile(
    r"^(https?://|git@|ssh://)[\w\.\-~:@/]+(\.git)?/?$"
)

# Active processes per session for cancellation
_active_processes: dict[str, asyncio.subprocess.Process] = {}

# Blocked SSRF hostnames and metadata endpoints
_BLOCKED_HOSTS: Final[set[str]] = {
    "169.254.169.254",
    "metadata.google.internal",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}


def get_workspaces_root() -> Path:
    """Return the base directory for cloud workspaces."""
    override = os.getenv("FCC_WORKSPACES_DIR")
    if override:
        path = Path(override).resolve()
    else:
        path = (config_dir_path() / "workspaces").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_session_id(session_id: str) -> str:
    """Sanitize session ID to strictly alphanumeric characters, dashes, and underscores."""
    clean = "".join(c for c in session_id if c.isalnum() or c in ("-", "_")).strip()
    if not clean:
        raise ValueError("Invalid session ID: must contain alphanumeric characters")
    return clean


def get_session_workspace_path(session_id: str, create: bool = False) -> Path:
    """Return the root path of an isolated session workspace, strictly verifying containment."""
    clean_id = sanitize_session_id(session_id)
    root = get_workspaces_root().resolve()
    target = (root / clean_id).resolve()
    if not target.is_relative_to(root):
        raise PermissionError("Path traversal prohibited: workspace path escapes root")
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def resolve_safe_workspace_path(session_id: str, relative_path: str = "") -> Path:
    """Resolve and enforce that relative_path is strictly contained inside the session workspace."""
    ws_root = get_session_workspace_path(session_id, create=True).resolve()
    if not relative_path or relative_path.strip() in (".", "/"):
        return ws_root

    clean_rel = relative_path.strip().lstrip("/\\")
    target = (ws_root / clean_rel).resolve()
    if not target.is_relative_to(ws_root):
        raise PermissionError(f"Access outside workspace sandbox prohibited: {relative_path}")
    return target


def validate_repo_url(repo_url: str) -> bool:
    """Validate that repository URL is safe, valid, and not an SSRF or injection vector."""
    if not repo_url or repo_url.startswith("-"):
        return False
    # Reject dangerous git protocols
    if any(repo_url.lower().startswith(p) for p in ("file:", "ext::", "fd::")):
        return False
    if not _SAFE_GIT_URL_REGEX.match(repo_url):
        return False

    # Block SSRF to cloud metadata services or private network hosts
    try:
        parsed = urlparse(repo_url)
        hostname = (parsed.hostname or "").lower()
        if hostname in _BLOCKED_HOSTS or hostname.startswith("127.") or hostname.startswith("10.") or hostname.startswith("192.168."):
            return False
    except Exception:
        return False

    return True


def get_isolated_sandbox_env(session_id: str, ws_path: Path) -> dict[str, str]:
    """Build a sanitized environment strictly excluding host secrets, credentials, and tokens.
    
    Prevents execution commands from exfiltrating cloud tokens, Supabase keys, or provider API keys.
    """
    safe_path = os.getenv("PATH", "/usr/local/bin:/usr/bin:/bin")
    if os.name == "nt":
        safe_path = os.getenv("PATH", r"C:\Windows\system32;C:\Windows;C:\Program Files\Git\bin")

    return {
        "PATH": safe_path,
        "HOME": str(ws_path),
        "USERPROFILE": str(ws_path),
        "TMPDIR": str(ws_path),
        "TEMP": str(ws_path),
        "TMP": str(ws_path),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "FCC_SESSION_ID": session_id,
        "FCC_SANDBOX": "1",
    }


async def prepare_workspace(
    session_id: str,
    repo_url_or_path: str | None = None,
    owner_email: str = "jaswanty132@gmail.com",
) -> str:
    """Prepare a cloud workspace by cloning a git repository or initializing a clean project directory."""
    ws_path = get_session_workspace_path(session_id, create=True)
    repo_url = None

    if repo_url_or_path:
        target = repo_url_or_path.strip()
        if validate_repo_url(target):
            repo_url = target
            logger.info("Cloning git repository {} into workspace {}", repo_url, ws_path)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "clone", "--depth", "1", repo_url, str(ws_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=get_isolated_sandbox_env(session_id, ws_path),
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logger.warning("Git clone failed: {}", stderr.decode(errors="replace"))
            except Exception as exc:
                logger.warning("Could not clone repository: {}", exc)
        elif Path(target).is_dir():
            # Existing local directory (local mode or test fixture)
            ws_path = Path(target).resolve()
        else:
            # Subdirectory or relative workspace name
            sub_dir = resolve_safe_workspace_path(session_id, target)
            sub_dir.mkdir(parents=True, exist_ok=True)
            ws_path = sub_dir

    # Ensure the workspace has a minimal git repo or README if empty
    readme_path = ws_path / "README.md"
    if not any(ws_path.iterdir()):
        readme_path.write_text(
            f"# Cloud Workspace: {session_id}\n\nInitialized in Free Claude Code Cloud.\n",
            encoding="utf-8",
        )

    # Persist session metadata in Supabase (in cloud/runtime mode, skip during unit tests)
    if not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            client = get_supabase_client()
            client.upsert_code_session(
                session_id=session_id,
                owner_email=owner_email,
                title=f"Session {session_id[:8]}",
                repo_url=repo_url,
                workspace_dir=str(ws_path),
                status="ready",
            )
            client.record_audit_event(
                "workspace_created",
                actor_email=owner_email,
                details={"session_id": session_id, "repo_url": repo_url, "path": str(ws_path)},
            )
        except Exception as exc:
            logger.warning("Failed to persist workspace in Supabase: {}", exc)

    return str(ws_path)


async def execute_command(
    session_id: str,
    command: str,
    timeout: float = 30.0,
    owner_email: str = "jaswanty132@gmail.com",
) -> dict[str, Any]:
    """Execute a shell or cli command inside the isolated session workspace with stripped environment."""
    ws_path = get_session_workspace_path(session_id, create=True)
    start_time = time.time()
    logger.info("Executing command in workspace {}: {}", ws_path, command)

    # Sanitize and validate command to prevent cloud metadata SSRF
    cmd_lower = command.lower()
    for blocked in _BLOCKED_HOSTS:
        if blocked in cmd_lower:
            return {
                "session_id": session_id,
                "command": command,
                "exit_code": 1,
                "stdout": "",
                "stderr": f"Execution rejected: access to internal host '{blocked}' is prohibited.",
                "duration": 0.0,
                "status": "blocked",
            }

    proc = None
    try:
        sandbox_env = get_isolated_sandbox_env(session_id, ws_path)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(ws_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=sandbox_env,
        )
        _active_processes[session_id] = proc

        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        duration = time.time() - start_time

        # Cap output at 512 KB to prevent memory exhaustion
        if len(stdout_bytes) > _MAX_OUTPUT_BYTES:
            stdout_bytes = stdout_bytes[:_MAX_OUTPUT_BYTES] + b"\n... [Output truncated at 512KB limit]"
        if len(stderr_bytes) > _MAX_OUTPUT_BYTES:
            stderr_bytes = stderr_bytes[:_MAX_OUTPUT_BYTES] + b"\n... [Stderr truncated at 512KB limit]"

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode

        result = {
            "session_id": session_id,
            "command": command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration": round(duration, 3),
            "status": "completed" if exit_code == 0 else "failed",
        }

        # Log audit and run records
        try:
            client = get_supabase_client()
            client.record_audit_event(
                "command_executed",
                actor_email=owner_email,
                details={
                    "session_id": session_id,
                    "command": command,
                    "exit_code": exit_code,
                    "duration": duration,
                },
            )
        except Exception:
            pass

        return result
    except asyncio.TimeoutError:
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                await proc.communicate()
            except Exception:
                pass
        return {
            "session_id": session_id,
            "command": command,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "duration": timeout,
            "status": "timeout",
        }
    except Exception as exc:
        return {
            "session_id": session_id,
            "command": command,
            "exit_code": 1,
            "stdout": "",
            "stderr": f"Command execution error: {exc}",
            "duration": round(time.time() - start_time, 3),
            "status": "error",
        }
    finally:
        _active_processes.pop(session_id, None)


async def cancel_session_command(session_id: str) -> bool:
    """Terminate and cancel any currently running process in the given session."""
    proc = _active_processes.get(session_id)
    if proc and proc.returncode is None:
        try:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    pass
            logger.info("Process in session {} successfully cancelled", session_id)
            for pipe in (proc.stdout, proc.stderr):
                if pipe and hasattr(pipe, "_transport") and pipe._transport:
                    try:
                        pipe._transport.close()
                    except Exception:
                        pass
            return True
        except Exception as exc:
            logger.warning("Failed to cancel process in session {}: {}", session_id, exc)
            return False
    return False


def cleanup_workspace(session_id: str) -> bool:
    """Clean up and remove an isolated session workspace."""
    try:
        clean_id = sanitize_session_id(session_id)
        root = get_workspaces_root().resolve()
        target = (root / clean_id).resolve()
        if target.exists() and target.is_relative_to(root):
            shutil.rmtree(target, ignore_errors=True)
            return True
        return False
    except Exception as exc:
        logger.warning("Error cleaning workspace {}: {}", session_id, exc)
        return False


def cleanup_expired_workspaces(max_age_hours: int = 24) -> int:
    """Remove workspaces that have not been modified within max_age_hours."""
    root = get_workspaces_root().resolve()
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    cleaned_count = 0

    try:
        for item in root.iterdir():
            if item.is_dir() and item.is_relative_to(root):
                try:
                    mtime = item.stat().st_mtime
                    if mtime < cutoff:
                        shutil.rmtree(item, ignore_errors=True)
                        cleaned_count += 1
                        logger.info("Cleaned expired workspace: {}", item.name)
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("Error during expired workspace cleanup: {}", exc)

    return cleaned_count
