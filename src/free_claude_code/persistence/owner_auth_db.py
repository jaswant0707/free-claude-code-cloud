"""Database-backed owner authentication, secure PBKDF2 hashing, and master token verification."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from .supabase_client import get_supabase_client

PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with random salt."""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    salt_b64 = base64.b64encode(salt).decode("utf-8")
    key_b64 = base64.b64encode(key).decode("utf-8")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${key_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against PBKDF2-HMAC-SHA256 hash or fallback plaintext."""
    if not stored_hash or not password:
        return False

    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            parts = stored_hash.split("$")
            if len(parts) != 4:
                return False
            _, iterations_str, salt_b64, key_b64 = parts
            iterations = int(iterations_str)
            salt = base64.b64decode(salt_b64)
            expected_key = base64.b64decode(key_b64)
            actual_key = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, iterations
            )
            return secrets.compare_digest(actual_key, expected_key)
        except Exception as exc:
            logger.warning("Error verifying password hash: {}", exc)
            return False

    # Fallback to constant-time comparison for legacy plaintext migration
    return secrets.compare_digest(password.encode("utf-8"), stored_hash.encode("utf-8"))


def get_owner_record(email: str) -> dict[str, Any] | None:
    """Fetch owner account record from Supabase."""
    client = get_supabase_client()
    if not client.is_configured:
        return None
    return client._rpc("fcc_get_owner_account", {"p_email": email.strip().lower()})


def upsert_owner_record(
    email: str, password_hash: str, master_token_hash: str | None = None
) -> dict[str, Any] | None:
    """Create or update owner account in Supabase."""
    client = get_supabase_client()
    if not client.is_configured:
        return None
    return client._rpc(
        "fcc_upsert_owner_account",
        {
            "p_email": email.strip().lower(),
            "p_password_hash": password_hash,
            "p_master_token_hash": master_token_hash,
        },
    )


def update_owner_login(email: str, success: bool) -> dict[str, Any] | None:
    """Update owner login attempt counter and lockout timestamp."""
    client = get_supabase_client()
    if not client.is_configured:
        return None
    return client._rpc(
        "fcc_update_owner_login",
        {"p_email": email.strip().lower(), "p_success": success},
    )


def verify_master_token_hash(token: str) -> bool:
    """Check if token hash matches the master token in Supabase."""
    if not token or len(token) < 16:
        return False
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    client = get_supabase_client()
    if not client.is_configured:
        return False
    return bool(client._rpc("fcc_verify_master_token_hash", {"p_token_hash": token_hash}))
