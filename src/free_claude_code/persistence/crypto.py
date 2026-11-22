"""Cryptographic utilities for Free Claude Code Cloud.

Provides AES-256-GCM authenticated encryption for provider API keys,
deterministic server-side key derivation, and secret masking.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Salt for HKDF key derivation
_HKDF_SALT: Final[bytes] = b"fcc-cloud-secret-salt-v1"


def get_encryption_key() -> bytes:
    """Derive a 256-bit AES-GCM key from server environment secrets."""
    explicit_key = os.getenv("FCC_ENCRYPTION_KEY", "").strip()
    if explicit_key:
        return hashlib.sha256(explicit_key.encode("utf-8")).digest()

    owner_pw = os.getenv("OWNER_PASSWORD", "").strip()
    admin_token = os.getenv("ADMIN_AUTH_TOKEN", "").strip()
    master_token = os.getenv("MASTER_API_TOKEN", "").strip()
    project_id = os.getenv("VERCEL_PROJECT_ID", "").strip()

    seed = f"fcc-aes-key-v1:{owner_pw}:{admin_token}:{master_token}:{project_id}"
    return hashlib.sha256(seed.encode("utf-8") + _HKDF_SALT).digest()


def encrypt_secret(plaintext: str, key: bytes | None = None) -> str:
    """Encrypt sensitive plaintext using AES-256-GCM.
    
    Returns URL-safe base64 string formatted as: nonce (12B) + ciphertext + tag (16B).
    """
    if not plaintext:
        return ""

    aes_key = key if key is not None else get_encryption_key()
    aesgcm = AESGCM(aes_key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")


def decrypt_secret(token: str, key: bytes | None = None) -> str:
    """Decrypt an AES-256-GCM encrypted token.
    
    Raises ValueError if ciphertext is invalid, corrupted, or tampered.
    """
    if not token:
        return ""

    aes_key = key if key is not None else get_encryption_key()
    aesgcm = AESGCM(aes_key)
    try:
        padding = "=" * (-len(token) % 4)
        data = base64.urlsafe_b64decode(token + padding)
        if len(data) < 28:  # 12-byte nonce + 16-byte tag minimum
            raise ValueError("Encrypted data is too short")
        nonce = data[:12]
        ciphertext = data[12:]
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Failed to decrypt secret: {exc}") from exc


def mask_secret(secret: str) -> str:
    """Mask sensitive string for display in UI, showing only brief edge characters."""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••••••"
    prefix_len = min(6, len(secret) // 3)
    suffix_len = min(4, len(secret) // 4)
    return f"{secret[:prefix_len]}...{secret[-suffix_len:]}"
