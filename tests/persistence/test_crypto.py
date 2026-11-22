"""Unit tests for Free Claude Code Cloud cryptographic functions.

Verifies:
- AES-256-GCM authenticated encryption/decryption roundtrip
- Nonce uniqueness across repeated encryptions (probabilistic security)
- GHASH authentication tag integrity and tampering rejection
- Ciphertext bit-flipping rejection
- Wrong key rejection
- Malformed and short payload handling
- Deterministic key derivation across serverless environments
- Zero-downtime secret rotation
- Secret masking edge cases
"""

from __future__ import annotations

import base64
import os
import secrets
import pytest

from free_claude_code.persistence.crypto import (
    decrypt_secret,
    encrypt_secret,
    get_encryption_key,
    mask_secret,
    rotate_secret,
)


def test_encrypt_decrypt_roundtrip():
    """Verify arbitrary plaintext secrets encrypt and decrypt faithfully."""
    test_secrets = [
        "sk-ant-api03-abcdef1234567890",
        "gsk_my_super_secret_groq_key_99999",
        "a",
        "A" * 500,
        "special-chars: !@#$%^&*()_+~`-={}|[]\\:\";'<>?,./",
        "unicode-secrets: 🔐🔑🔒🚀",
    ]
    key = secrets.token_bytes(32)
    for plain in test_secrets:
        encrypted = encrypt_secret(plain, key=key)
        assert encrypted != plain
        decrypted = decrypt_secret(encrypted, key=key)
        assert decrypted == plain


def test_nonce_uniqueness():
    """Verify repeated encryption of identical plaintext uses distinct 96-bit nonces."""
    plain = "same_secret_key_12345"
    key = secrets.token_bytes(32)
    ciphertexts = {encrypt_secret(plain, key=key) for _ in range(50)}
    # All 50 encryptions must produce completely unique ciphertext strings
    assert len(ciphertexts) == 50

    # Also verify nonces themselves are unique
    nonces = set()
    for c in ciphertexts:
        padding = "=" * (-len(c) % 4)
        raw = base64.urlsafe_b64decode(c + padding)
        nonce = raw[:12]
        assert len(nonce) == 12
        nonces.add(nonce)
    assert len(nonces) == 50


def test_ghash_tag_tampering_rejected():
    """Verify AES-256-GCM GHASH tag verification rejects tampered authentication tags."""
    plain = "secure_provider_credential"
    key = secrets.token_bytes(32)
    token = encrypt_secret(plain, key=key)
    padding = "=" * (-len(token) % 4)
    raw = bytearray(base64.urlsafe_b64decode(token + padding))

    # The last 16 bytes are the GHASH authentication tag
    # Flip one bit in the tag
    raw[-1] ^= 0x01
    tampered_token = base64.urlsafe_b64encode(raw).decode().rstrip("=")

    with pytest.raises(ValueError, match="Failed to decrypt secret"):
        decrypt_secret(tampered_token, key=key)


def test_ciphertext_tampering_rejected():
    """Verify AES-256-GCM rejects flipped bits in the ciphertext body."""
    plain = "secure_provider_credential"
    key = secrets.token_bytes(32)
    token = encrypt_secret(plain, key=key)
    padding = "=" * (-len(token) % 4)
    raw = bytearray(base64.urlsafe_b64decode(token + padding))

    # Flip one bit in the ciphertext (byte 14, after the 12-byte nonce)
    raw[14] ^= 0x01
    tampered_token = base64.urlsafe_b64encode(raw).decode().rstrip("=")

    with pytest.raises(ValueError, match="Failed to decrypt secret"):
        decrypt_secret(tampered_token, key=key)


def test_wrong_key_rejected():
    """Verify decrypting with an incorrect key is rejected."""
    plain = "secret_value_123"
    key1 = secrets.token_bytes(32)
    key2 = secrets.token_bytes(32)

    token = encrypt_secret(plain, key=key1)
    with pytest.raises(ValueError, match="Failed to decrypt secret"):
        decrypt_secret(token, key=key2)


def test_malformed_and_short_inputs():
    """Verify short or invalid payloads are safely rejected."""
    key = secrets.token_bytes(32)

    # Empty token returns empty string
    assert decrypt_secret("", key=key) == ""
    assert encrypt_secret("", key=key) == ""

    # Short payload (< 28 bytes)
    short_raw = secrets.token_bytes(20)
    short_token = base64.urlsafe_b64encode(short_raw).decode().rstrip("=")
    with pytest.raises(ValueError, match="Failed to decrypt secret: Encrypted data is too short"):
        decrypt_secret(short_token, key=key)

    # Invalid base64
    with pytest.raises(ValueError, match="Failed to decrypt secret"):
        decrypt_secret("not-valid-base64!@#$%", key=key)


def test_secret_rotation():
    """Verify rotate_secret seamlessly re-encrypts from old_key to new_key."""
    plain = "sk-rotation-test-token"
    old_key = secrets.token_bytes(32)
    new_key = secrets.token_bytes(32)

    old_token = encrypt_secret(plain, key=old_key)
    rotated_token = rotate_secret(old_token, old_key=old_key, new_key=new_key)

    # Rotated token must be different
    assert rotated_token != old_token

    # Old key cannot decrypt rotated token
    with pytest.raises(ValueError):
        decrypt_secret(rotated_token, key=old_key)

    # New key decrypts rotated token successfully
    assert decrypt_secret(rotated_token, key=new_key) == plain


def test_deterministic_key_derivation(monkeypatch):
    """Verify key derivation is consistent across distributed serverless instances."""
    monkeypatch.setenv("FCC_ENCRYPTION_KEY", "custom_secret_key_fixed_321")
    key_a = get_encryption_key()
    key_b = get_encryption_key()
    assert key_a == key_b
    assert len(key_a) == 32

    # Verify fallback key from Supabase key is also deterministic
    monkeypatch.delenv("FCC_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon_key_test_fixed_123")
    key_c = get_encryption_key()
    key_d = get_encryption_key()
    assert key_c == key_d
    assert len(key_c) == 32
    assert key_c != key_a


def test_mask_secret():
    """Verify secret masking hides sensitive characters."""
    assert mask_secret("") == ""
    assert mask_secret("short") == "••••••••"
    assert mask_secret("12345678") == "••••••••"

    masked = mask_secret("gsk_f300123456789abcdefO4tJ")
    assert masked.startswith("gsk_f3")
    assert masked.endswith("O4tJ")
    assert "..." in masked
    assert "123456789abcdef" not in masked


def test_key_versioning_and_migration(monkeypatch):
    """Verify legacy secrets encrypted under v1 decrypt cleanly under v2 with migration."""
    from free_claude_code.persistence.crypto import get_legacy_encryption_key, migrate_secret

    monkeypatch.delenv("FCC_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "legacy_anon_key_for_testing_123")
    legacy_key = get_legacy_encryption_key()

    plain_secret = "gsk_prod_live_credential_999"
    # Legacy ciphertext generated with legacy key
    legacy_ciphertext = encrypt_secret(plain_secret, key=legacy_key)

    # Now simulate setting the dedicated FCC_ENCRYPTION_KEY
    monkeypatch.setenv("FCC_ENCRYPTION_KEY", "brand_new_dedicated_secret_key_888")
    new_active_key = get_encryption_key()
    assert new_active_key != legacy_key

    # Automatic fallback decryption of legacy ciphertext
    decrypted = decrypt_secret(legacy_ciphertext)
    assert decrypted == plain_secret

    # Migration to new active key
    migrated_ciphertext = migrate_secret(legacy_ciphertext)
    assert migrated_ciphertext != legacy_ciphertext

    # Migrated secret decrypts with new key
    assert decrypt_secret(migrated_ciphertext) == plain_secret
    assert decrypt_secret(f"v2:{migrated_ciphertext}") == plain_secret

