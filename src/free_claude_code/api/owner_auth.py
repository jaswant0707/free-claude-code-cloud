"""Single-Owner Authentication and Session Security Module for Free Claude Code Cloud."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request, Response
from loguru import logger

# Session configuration
SESSION_COOKIE_NAME = "fcc_session"
SESSION_DURATION_SECONDS = 86400  # 24 hours
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_ATTEMPTS_PER_WINDOW = 5

# Ephemeral in-memory tracking for brute-force rate-limiting
_login_attempts: dict[str, list[float]] = {}


class OwnerAuthError(Exception):
    """Base exception for owner authentication errors."""
    pass


class AccountLockedError(OwnerAuthError):
    """Raised when the owner account is temporarily locked due to too many failed attempts."""

    def __init__(self, minutes_remaining: int):
        self.minutes_remaining = max(1, minutes_remaining)
        super().__init__(
            f"Account is temporarily locked due to multiple failed login attempts. "
            f"Please try again after {self.minutes_remaining} minute(s)."
        )


class DatabaseAuthError(OwnerAuthError):
    """Raised when the database service cannot be reached to verify credentials."""

    def __init__(
        self,
        message: str = "Authentication database service is temporarily unavailable. Please try again shortly.",
    ):
        super().__init__(message)


def get_owner_email() -> str | None:
    """Retrieve the single configured owner email from environment."""
    email = os.getenv("OWNER_EMAIL", "").strip()
    return email if email else None


def get_owner_password() -> str | None:
    """Retrieve the single configured owner password from environment."""
    password = os.getenv("OWNER_PASSWORD", "").strip()
    return password if password else None


def get_master_api_token() -> str | None:
    """Retrieve the independent Master API Token for external clients."""
    token = os.getenv("MASTER_API_TOKEN", "").strip()
    if not token:
        # Fallback to ANTHROPIC_AUTH_TOKEN if explicitly set
        token = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
    return token if token else None


_PROCESS_FALLBACK_SIGNING_SECRET = secrets.token_hex(32)
_PERSISTENT_SIGNING_SECRET: str | None = None


def _get_signing_key() -> bytes:
    """Derive an internal cryptographic signing key for session tokens without hardcoded fallbacks."""
    global _PERSISTENT_SIGNING_SECRET

    # 1. Check explicit environment variables
    secret = (
        os.getenv("FCC_SESSION_SECRET", "").strip()
        or os.getenv("SESSION_SECRET", "").strip()
        or os.getenv("FCC_ENCRYPTION_KEY", "").strip()
    )
    if secret:
        return hashlib.sha256(secret.encode("utf-8")).digest()

    # 2. Check cached persistent secret in memory
    if _PERSISTENT_SIGNING_SECRET:
        return hashlib.sha256(_PERSISTENT_SIGNING_SECRET.encode("utf-8")).digest()

    # 3. Fetch or persist a persistent signing key in Supabase fcc_app_settings across serverless containers
    if not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            from free_claude_code.persistence.supabase_client import get_supabase_client

            client = get_supabase_client()
            if client.is_configured:
                settings = client.get_app_settings()
                stored = settings.get("session_signing_secret")
                if stored and len(stored) >= 32:
                    _PERSISTENT_SIGNING_SECRET = stored
                    return hashlib.sha256(_PERSISTENT_SIGNING_SECRET.encode("utf-8")).digest()
                else:
                    new_secret = secrets.token_hex(32)
                    client.upsert_app_setting("session_signing_secret", new_secret, is_secret=False)
                    _PERSISTENT_SIGNING_SECRET = new_secret
                    return hashlib.sha256(_PERSISTENT_SIGNING_SECRET.encode("utf-8")).digest()
        except Exception as exc:
            logger.warning("Could not retrieve or persist session signing secret from database: {}", exc)

    # 4. Fallback to owner password/token or per-process secret
    password = get_owner_password()
    token = get_master_api_token()
    if password or token:
        secret = f"{password}:{token}"
    else:
        secret = _PROCESS_FALLBACK_SIGNING_SECRET
    return hashlib.sha256(secret.encode("utf-8")).digest()


def check_login_rate_limit(client_ip: str) -> bool:
    """Enforce rate limits on login attempts per client IP."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    # Clean stale entries
    attempts = [ts for ts in _login_attempts.get(client_ip, []) if ts > cutoff]
    if len(attempts) >= MAX_ATTEMPTS_PER_WINDOW:
        return False

    attempts.append(now)
    _login_attempts[client_ip] = attempts
    return True


def authenticate_owner(email: str, password: str) -> bool:
    """Validate credentials against the configured owner in database or environment."""
    if not email or not password:
        return False

    clean_email = email.strip().lower()
    configured_email = (get_owner_email() or "jaswanty132@gmail.com").strip().lower()

    # Verify target email matches configured single owner
    email_matches_config = secrets.compare_digest(
        clean_email.encode("utf-8"),
        configured_email.encode("utf-8"),
    )

    # In unit tests or for non-production example domains, skip remote Supabase owner checks
    # to ensure isolated, repeatable test execution without cross-worker database lockouts.
    if os.getenv("PYTEST_CURRENT_TEST") and (clean_email.endswith("@example.com") or not email_matches_config):
        if not email_matches_config:
            return False
        configured_password = get_owner_password()
        if configured_password:
            return secrets.compare_digest(
                password.encode("utf-8"),
                configured_password.encode("utf-8"),
            )
        return False

    # 1. Check Supabase database owner record
    db_failed = False
    try:
        from free_claude_code.persistence.owner_auth_db import (
            get_owner_record,
            hash_password,
            update_owner_login,
            upsert_owner_record,
            verify_password,
        )
        from free_claude_code.persistence.supabase_client import get_supabase_client

        record = get_owner_record(clean_email)
        if record:
            # Check lockout
            locked_until = record.get("locked_until")
            if locked_until:
                from datetime import datetime, timezone

                try:
                    lock_time = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    if now < lock_time:
                        seconds_remaining = (lock_time - now).total_seconds()
                        mins_remaining = int(seconds_remaining // 60) + 1
                        logger.warning(
                            "Owner account is temporarily locked ({} minute(s) remaining).",
                            mins_remaining,
                        )
                        raise AccountLockedError(minutes_remaining=mins_remaining)
                except AccountLockedError:
                    raise
                except Exception as parse_err:
                    logger.warning("Could not parse locked_until timestamp: {}", parse_err)

            pw_hash = record.get("password_hash")
            if pw_hash and verify_password(password, pw_hash):
                update_owner_login(clean_email, success=True)
                get_supabase_client().record_audit_event("owner_login_success", actor_email=clean_email)
                return True
            else:
                update_owner_login(clean_email, success=False)
                get_supabase_client().record_audit_event("owner_login_failure", actor_email=clean_email)
                return False
    except AccountLockedError:
        raise
    except Exception as exc:
        db_failed = True
        logger.warning("Database authentication check encountered an error: {}", exc)

    # 2. Fallback to configured environment password
    configured_password = get_owner_password()
    if configured_password and email_matches_config:
        password_matches = secrets.compare_digest(
            password.encode("utf-8"),
            configured_password.encode("utf-8"),
        )
        if password_matches:
            # Upgrade and persist hash to Supabase
            try:
                from free_claude_code.persistence.owner_auth_db import (
                    hash_password,
                    upsert_owner_record,
                )

                upsert_owner_record(clean_email, hash_password(password))
            except Exception:
                pass
            return True

    # If database lookup failed due to network/RPC error and no env fallback succeeded
    if db_failed and not configured_password:
        raise DatabaseAuthError("Authentication database service is temporarily unavailable. Please try again shortly.")

    return False


def create_session_token(email: str) -> str:
    """Generate an HMAC-SHA256 signed tamper-proof session token."""
    now = int(time.time())
    payload = {
        "email": email.strip().lower(),
        "iat": now,
        "exp": now + SESSION_DURATION_SECONDS,
        "nonce": secrets.token_hex(16),
    }

    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("utf-8").rstrip("=")

    signature = hmac.new(
        _get_signing_key(),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")

    return f"{payload_b64}.{signature_b64}"


def verify_session_token(token: str) -> dict[str, Any] | None:
    """Verify cryptographic signature and expiration of session token."""
    if not token or "." not in token:
        return None

    payload_b64, _, signature_b64 = token.partition(".")
    if not payload_b64 or not signature_b64:
        return None

    # Verify HMAC signature
    expected_sig = hmac.new(
        _get_signing_key(),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_sig_b64 = (
        base64.urlsafe_b64encode(expected_sig).decode("utf-8").rstrip("=")
    )

    if not secrets.compare_digest(
        signature_b64.encode("utf-8"), expected_sig_b64.encode("utf-8")
    ):
        return None

    # Decode and validate payload
    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

    # Verify expiration
    now = int(time.time())
    if payload.get("exp", 0) < now:
        return None

    # Verify owner email matches
    token_email = payload.get("email", "").strip().lower()
    configured_email = (get_owner_email() or "jaswanty132@gmail.com").strip().lower()
    if not secrets.compare_digest(
        token_email.encode("utf-8"),
        configured_email.encode("utf-8"),
    ):
        return None

    return payload


def extract_session_from_request(request: Request) -> dict[str, Any] | None:
    """Extract and verify session token from cookies or Authorization header."""
    # 1. Cookie check
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME, "").strip()
    if cookie_token:
        session = verify_session_token(cookie_token)
        if session:
            return session

    # 2. Authorization Bearer check (for browser API calls)
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()
        session = verify_session_token(bearer_token)
        if session:
            return session

    return None


def is_authenticated_owner(request: Request) -> bool:
    """Check if the current request is authenticated as the owner."""
    return extract_session_from_request(request) is not None


def set_session_cookie(response: Response, token: str, request: Request) -> None:
    """Set secure session cookie on response."""
    is_secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
        or os.getenv("VERCEL") is not None
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_DURATION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Clear session cookie on logout."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )


def require_owner_session(request: Request) -> dict[str, Any]:
    """Dependency for routes requiring owner session authentication."""
    session = extract_session_from_request(request)
    if session is not None:
        return session

    # Check if request prefers HTML (browser navigation) -> redirect to login
    accept = request.headers.get("accept", "")
    if "text/html" in accept and request.method == "GET":
        from fastapi.responses import RedirectResponse

        next_path = quote(str(request.url.path))
        raise HTTPException(
            status_code=307,
            headers={"Location": f"/login?next={next_path}"},
        )

    raise HTTPException(
        status_code=401,
        detail="Owner authentication required. Please log in at /login",
    )
