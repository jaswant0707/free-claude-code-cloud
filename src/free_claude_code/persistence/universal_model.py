"""Universal Default Model configuration, persistence, and resolution."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from loguru import logger

from .supabase_client import get_supabase_client

DEFAULT_UNIVERSAL_MODEL_ALIAS = "free-claude-universal"
_SETTING_ALIAS_KEY = "fcc_universal_model_alias"
_SETTING_TARGET_KEY = "fcc_universal_model_target"
_SETTING_FALLBACKS_KEY = "fcc_universal_model_fallbacks"

# In-memory cache for high-throughput gateway routing (TTL 15 seconds)
_CONFIG_CACHE: dict[str, Any] | None = None
_CACHE_TIMESTAMP: float = 0.0
_CACHE_TTL_SECONDS: float = 15.0

_ALIAS_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{2,64}$")


def is_valid_model_alias(alias: str) -> bool:
    """Validate model alias format."""
    return bool(alias and _ALIAS_PATTERN.match(alias.strip()))


def get_universal_model_config() -> dict[str, Any]:
    """Retrieve the current universal model alias and target routing config.
    
    Returns a dictionary with keys:
      - alias: str (default 'free-claude-universal')
      - target_model: str | None
      - fallback_models: list[str]
    """
    global _CONFIG_CACHE, _CACHE_TIMESTAMP

    now = time.monotonic()
    if _CONFIG_CACHE is not None and (now - _CACHE_TIMESTAMP) < _CACHE_TTL_SECONDS:
        return dict(_CONFIG_CACHE)

    alias = os.getenv("FCC_UNIVERSAL_MODEL_ALIAS", "").strip() or DEFAULT_UNIVERSAL_MODEL_ALIAS
    target_model = os.getenv("FCC_UNIVERSAL_MODEL_TARGET", "").strip() or None
    fallback_models: list[str] = []

    client = get_supabase_client()
    if client.is_configured:
        try:
            settings = client.get_app_settings()
            db_alias = settings.get(_SETTING_ALIAS_KEY, "").strip()
            if db_alias:
                alias = db_alias
            db_target = settings.get(_SETTING_TARGET_KEY, "").strip()
            if db_target:
                target_model = db_target
            db_fallbacks = settings.get(_SETTING_FALLBACKS_KEY, "").strip()
            if db_fallbacks:
                try:
                    parsed = json.loads(db_fallbacks)
                    if isinstance(parsed, list):
                        fallback_models = [str(m).strip() for m in parsed if m]
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Error fetching universal model config from Supabase: {}", exc)

    config = {
        "alias": alias,
        "target_model": target_model,
        "fallback_models": fallback_models,
    }
    _CONFIG_CACHE = config
    _CACHE_TIMESTAMP = now
    return dict(config)


def set_universal_model_config(
    alias: str,
    target_model: str | None = None,
    fallback_models: list[str] | None = None,
) -> dict[str, Any]:
    """Update and persist the universal model configuration.
    
    Raises ValueError on invalid alias.
    """
    clean_alias = alias.strip() if alias else DEFAULT_UNIVERSAL_MODEL_ALIAS
    if not is_valid_model_alias(clean_alias):
        raise ValueError(
            f"Invalid model alias '{alias}'. Must be 2-64 characters containing only letters, numbers, hyphens, underscores, or dots."
        )

    clean_target = target_model.strip() if target_model else None
    if clean_target in {"", "auto", "default"}:
        clean_target = None

    clean_fallbacks = [m.strip() for m in (fallback_models or []) if m and m.strip()]

    client = get_supabase_client()
    if client.is_configured:
        client.upsert_app_setting(_SETTING_ALIAS_KEY, clean_alias)
        client.upsert_app_setting(_SETTING_TARGET_KEY, clean_target or "")
        client.upsert_app_setting(
            _SETTING_FALLBACKS_KEY, json.dumps(clean_fallbacks)
        )

    # Invalidate and update local cache
    global _CONFIG_CACHE, _CACHE_TIMESTAMP
    config = {
        "alias": clean_alias,
        "target_model": clean_target,
        "fallback_models": clean_fallbacks,
    }
    _CONFIG_CACHE = config
    _CACHE_TIMESTAMP = time.monotonic()
    return dict(config)


def invalidate_universal_model_cache() -> None:
    """Force cache refresh on next access."""
    global _CONFIG_CACHE, _CACHE_TIMESTAMP
    _CONFIG_CACHE = None
    _CACHE_TIMESTAMP = 0.0


def resolve_incoming_model_request(
    requested_model: str | None,
    key_default_model: str | None = None,
) -> str:
    """Resolve incoming model identifier against key override, universal alias, and global target.
    
    Precedence:
      1. Explicit provider/model in request (unless it matches the universal alias or auto/empty).
      2. Per-key default model override (if request model is empty, auto, or universal alias).
      3. Global Universal Default Model (if request model is empty, auto, or universal alias).
      4. Fallback to requested_model or alias.
    """
    cfg = get_universal_model_config()
    alias = cfg.get("alias", "") or DEFAULT_UNIVERSAL_MODEL_ALIAS
    clean_req = (requested_model or "").strip()
    is_universal_or_auto = (
        not clean_req
        or clean_req.casefold() in {
            "auto",
            alias.casefold(),
            DEFAULT_UNIVERSAL_MODEL_ALIAS.casefold(),
        }
    )

    if not is_universal_or_auto:
        # 1. Explicit model requested
        return clean_req

    # 2. Per-key default model override
    if key_default_model and key_default_model.strip():
        return key_default_model.strip()

    # 3. Global Universal Default Model
    target = cfg.get("target_model")
    if target and target.strip():
        return target.strip()

    # 4. Fallback
    return clean_req or alias
