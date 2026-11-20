"""Single-Owner Authentication and Session Security Module for Free Claude Code Cloud."""

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


def _get_signing_key() -> bytes:
    """Derive an internal cryptographic signing key for session tokens."""
    password = get_owner_password() or "default-cloud-salt"
    token = get_master_api_token() or "fcc-session-secret"
    derived = hashlib.sha256(f"{password}:{token}".encode("utf-8")).digest()
    return derived


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
    """Validate credentials against the configured single owner."""
    configured_email = get_owner_email()
    configured_password = get_owner_password()

    # Fail closed if credentials are not configured in production
    if not configured_email or not configured_password:
        logger.error("Owner credentials are not configured in environment variables.")
        return False

    # Constant-time comparison to prevent timing side-channel attacks
    email_matches = secrets.compare_digest(
        email.strip().lower().encode("utf-8"),
        configured_email.strip().lower().encode("utf-8"),
    )
    password_matches = secrets.compare_digest(
        password.encode("utf-8"),
        configured_password.encode("utf-8"),
    )

    return email_matches and password_matches


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
    configured_email = get_owner_email()
    if configured_email and not secrets.compare_digest(
        payload.get("email", "").lower().encode("utf-8"),
        configured_email.lower().encode("utf-8"),
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
