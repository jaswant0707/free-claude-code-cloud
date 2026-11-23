"""Atomic text-file replacement for local client configuration."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import cast

import json5

from free_claude_code.core.json_types import JsonObject, JsonValue


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    document: JsonObject = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Duplicate configuration key")
        document[key] = value
    return document


def _reject_constant(value: str) -> JsonValue:
    raise ValueError("Nonfinite configuration value")


def decode_json(source: str) -> JsonValue:
    """Decode native JSON/JSON5 without duplicate or nonfinite values."""
    try:
        document = json.loads(
            source, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except json.JSONDecodeError:
        document = json5.loads(source, allow_duplicate_keys=False)
    json.dumps(document, allow_nan=False)
    return cast(JsonValue, document)


def ensure_private_permissions(path: Path) -> None:
    """Restrict POSIX access; Windows files inherit their profile directory ACL."""
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
        path.chmod(0o600)


def backup_config(path: Path) -> Path | None:
    """Create a .bak copy of an existing configuration file before modifying it."""
    try:
        if path.is_file():
            backup_path = path.with_suffix(path.suffix + ".bak")
            backup_path.write_bytes(path.read_bytes())
            return backup_path
    except OSError:
        pass
    return None


def is_cloud_environment() -> bool:
    """Detect whether FCC is executing in a serverless or cloud container environment."""
    return (
        os.getenv("FCC_CLOUD_DEPLOYMENT", "").lower() in ("1", "true", "yes")
        or os.getenv("ENABLE_CLOUD_ADMIN", "").lower() in ("1", "true", "yes")
        or bool(os.getenv("VERCEL"))
        or bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    )


def get_fallback_path(path: Path) -> Path:
    """Return a writable mirror path in temp directory for read-only cloud filesystems."""
    return Path(tempfile.gettempdir()) / "fcc_configs" / path.name


def read_config_text(path: Path, encoding: str = "utf-8") -> str:
    """Read configuration text from path, falling back to temp mirror in cloud mode."""
    try:
        return path.read_text(encoding=encoding)
    except (FileNotFoundError, OSError):
        if is_cloud_environment():
            fallback = get_fallback_path(path)
            if fallback != path and fallback.is_file():
                return fallback.read_text(encoding=encoding)
        raise FileNotFoundError(f"Config file not found: {path}")


def delete_config(path: Path) -> bool:
    """Safely unlink path and any temp fallback copy without raising OSError."""
    deleted = False
    try:
        if path.is_file():
            path.unlink()
            deleted = True
    except OSError:
        pass
    if is_cloud_environment():
        try:
            fallback = get_fallback_path(path)
            if fallback != path and fallback.is_file():
                fallback.unlink()
                deleted = True
        except OSError:
            pass
    return deleted


def atomic_write_text(
    path: Path,
    content: str,
    *,
    private: bool = False,
    backup: bool = False,
    **kwargs: object,
) -> None:
    if backup and not os.getenv("PYTEST_CURRENT_TEST"):
        backup_config(path)
    target = path
    if is_cloud_environment():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            target = get_fallback_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if private and os.name != "nt":
            ensure_private_permissions(temporary)
        elif target.exists():
            temporary.chmod(stat.S_IMODE(target.stat().st_mode))
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            # Windows cannot delete a temporary file after copying a read-only mode.
            temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
            temporary.unlink()
