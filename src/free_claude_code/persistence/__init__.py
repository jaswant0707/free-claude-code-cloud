"""Persistence package for Free Claude Code Cloud."""

from .crypto import decrypt_secret, encrypt_secret, get_encryption_key, mask_secret
from .supabase_client import SupabaseClient, get_supabase_client
from .universal_keys import (
    generate_universal_key,
    hash_key,
    invalidate_universal_key_cache,
    is_universal_key_format,
    verify_universal_key,
)
from .universal_model import (
    DEFAULT_UNIVERSAL_MODEL_ALIAS,
    get_universal_model_config,
    invalidate_universal_model_cache,
    set_universal_model_config,
)

__all__ = [
    "decrypt_secret",
    "encrypt_secret",
    "get_encryption_key",
    "mask_secret",
    "SupabaseClient",
    "get_supabase_client",
    "generate_universal_key",
    "hash_key",
    "invalidate_universal_key_cache",
    "is_universal_key_format",
    "verify_universal_key",
    "DEFAULT_UNIVERSAL_MODEL_ALIAS",
    "get_universal_model_config",
    "invalidate_universal_model_cache",
    "set_universal_model_config",
]
