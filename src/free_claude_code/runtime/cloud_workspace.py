"""Cloud Workspace Manager for Free Claude Code Cloud.

Provides isolated cloud workspaces, git repository cloning, safe path resolution
(preventing traversal attacks), and command execution inside session workspaces.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from loguru import logger

from free_claude_code.config.paths import config_dir_path
from free_claude_code.persistence.supabase_client import get_supabase_client


def get_workspaces_root() -> Path:
    """Return the base directory for cloud workspaces."""
    override = os.getenv("FCC_WORKSPACES_DIR")
    if override:
        path = Path(override)
    else:
        path = config_dir_path() / "workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_session_id(session_id: str) -> str:
    """Sanitize session ID to prevent path injection."""
    clean = "".join(c for c in session_id if c.isalnum() or c in ("-", "_")).strip()
    if not clean:
        raise ValueError("Invalid session ID")
    return clean


def get_session_workspace_path(session_id: str, create: bool = False) -> Path:
    """Return the root path of an isolated session workspace."""
    clean_id = sanitize_session_id(session_id)
    root = get_workspaces_root().resolve()
    target = (root / clean_id).resolve()
    if not str(target).startswith(str(root)):
        raise PermissionError("Path traversal prohibited")
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
    if not str(target).startswith(str(ws_root)):
        raise PermissionError(f"Access outside workspace sandbox prohibited: {relative_path}")
    return target


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
        if target.startswith(("http://", "https://", "git@", "ssh://")):
            repo_url = target
            logger.info("Cloning git repository {} into workspace {}", repo_url, ws_path)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "clone", "--depth", "1", repo_url, str(ws_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
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
    """Execute a real shell or cli command inside the isolated session workspace."""
    ws_path = get_session_workspace_path(session_id, create=True)
    start_time = time.time()
    logger.info("Executing command in workspace {}: {}", ws_path, command)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(ws_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        duration = time.time() - start_time

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
        try:
            proc.kill()
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


def cleanup_workspace(session_id: str) -> bool:
    """Clean up and remove an isolated session workspace."""
    try:
        clean_id = sanitize_session_id(session_id)
        root = get_workspaces_root().resolve()
        target = (root / clean_id).resolve()
        if target.exists() and str(target).startswith(str(root)):
            shutil.rmtree(target, ignore_errors=True)
            return True
        return False
    except Exception as exc:
        logger.warning("Error cleaning workspace {}: {}", session_id, exc)
        return False
