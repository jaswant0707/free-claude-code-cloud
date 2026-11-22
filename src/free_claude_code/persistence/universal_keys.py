"""Universal API Key management, cryptographic hashing, and caching."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any
from loguru import logger

from .supabase_client import get_supabase_client

_KEY_PREFIX = "fcc_uk_"
# Cache verified key hashes for 15 seconds to reduce database roundtrips during streaming
_KEY_VERIFY_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_CACHE_TTL_SECONDS = 15.0


def is_universal_key_format(token: str) -> bool:
    """Check if token matches Universal Key format."""
    return bool(token and token.startswith(_KEY_PREFIX) and len(token) >= 24)


def hash_key(raw_key: str) -> str:
    """Compute SHA-256 hex digest of raw key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_universal_key(
    name: str,
    default_model: str | None = None,
    fallback_models: list[str] | None = None,
    rate_limit_rpm: int = 60,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Generate a cryptographically secure Universal API Key.
    
    Returns a dict containing the raw key (only returned once upon generation)
    and persisted metadata.
    """
    random_part = secrets.token_hex(24)
    raw_key = f"{_KEY_PREFIX}{random_part}"
    prefix = f"{raw_key[:14]}..."
    key_h = hash_key(raw_key)

    client = get_supabase_client()
    record = None
    if client.is_configured:
        record = client.create_universal_key(
            name=name,
            key_prefix=prefix,
            key_hash=key_h,
            default_model=default_model,
            fallback_models=fallback_models or [],
            rate_limit_rpm=rate_limit_rpm,
            expires_at=expires_at,
        )

    # Invalidate cache
    _KEY_VERIFY_CACHE.pop(key_h, None)

    return {
        "raw_key": raw_key,
        "key_prefix": prefix,
        "key_hash": key_h,
        "record": record,
    }


def verify_universal_key(raw_key: str) -> dict[str, Any] | None:
    """Verify raw universal key against Supabase.
    
    Returns key metadata dict if valid and active, None otherwise.
    """
    if not is_universal_key_format(raw_key):
        return None

    key_h = hash_key(raw_key)
    now = time.monotonic()

    cached = _KEY_VERIFY_CACHE.get(key_h)
    if cached is not None:
        cache_time, data = cached
        if now - cache_time < _CACHE_TTL_SECONDS:
            return data

    client = get_supabase_client()
    if not client.is_configured:
        return None

    try:
        data = client.verify_universal_key(key_h)
        _KEY_VERIFY_CACHE[key_h] = (now, data)
        return data
    except Exception as exc:
        logger.warning("Error verifying universal key: {}", exc)
        return None


def invalidate_universal_key_cache(key_hash: str | None = None) -> None:
    """Clear key verification cache."""
    if key_hash:
        _KEY_VERIFY_CACHE.pop(key_hash, None)
    else:
        _KEY_VERIFY_CACHE.clear()
