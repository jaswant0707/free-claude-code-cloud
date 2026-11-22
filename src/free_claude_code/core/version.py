"""Canonical installed Free Claude Code package version."""

from __future__ import annotations

import os
import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version

_DISTRIBUTION_NAME = "free-claude-code"
_BASE_VERSION = "1.0.0"
_UNKNOWN_VERSION = "0+unknown"


def package_version() -> str:
    """Return installed metadata, git commit version, or explicit release version."""
    try:
        ver = distribution_version(_DISTRIBUTION_NAME)
        if ver and ver != _UNKNOWN_VERSION:
            return ver
    except PackageNotFoundError:
        pass

    # Check Vercel / environment git commit SHA
    commit_sha = os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT_SHA")
    if commit_sha:
        return f"{_BASE_VERSION}+{commit_sha[:8]}"

    return _UNKNOWN_VERSION
