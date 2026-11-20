"""Shared security boundary for Admin product surfaces with cloud authentication support."""

import ipaddress
import os
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _origin_is_local(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and _is_loopback_host(parsed.hostname)
    )


def _authority_is_local(authority: str | None) -> bool:
    if not authority:
        return False
    try:
        parsed = urlsplit(f"//{authority}")
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and _is_loopback_host(parsed.hostname)
    )


def _get_configured_admin_tokens() -> list[str]:
    """Retrieve all valid admin authentication tokens from environment or settings."""
    tokens = []
    for var in (
        "ADMIN_AUTH_TOKEN",
        "FCC_ADMIN_TOKEN",
        "MASTER_API_TOKEN",
        "PROXY_AUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        val = os.getenv(var, "").strip()
        if val and val not in tokens:
            tokens.append(val)
    if not tokens:
        try:
            from free_claude_code.config.loader import get_settings

            token = get_settings().proxy_auth_token
            if token and token not in tokens:
                tokens.append(token)
        except Exception:
            pass
    return tokens


def _is_cloud_environment() -> bool:
    """Check if the server is running in a cloud or remote deployment."""
    return bool(
        os.getenv("FCC_CLOUD_DEPLOYMENT", "").lower() in ("1", "true", "yes")
        or os.getenv("ENABLE_CLOUD_ADMIN", "").lower() in ("1", "true", "yes")
        or os.getenv("VERCEL")
        or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        or os.getenv("ADMIN_AUTH_TOKEN")
        or os.getenv("FCC_ADMIN_TOKEN")
        or os.getenv("MASTER_API_TOKEN")
        or os.getenv("OWNER_EMAIL")
    )


def is_authorized_admin(request: Request) -> bool:
    """Verify whether a request carries a valid admin credential."""
    # 0. Check single-owner session cookie
    try:
        from .owner_auth import is_authenticated_owner

        if is_authenticated_owner(request):
            return True
    except Exception:
        pass

    tokens = _get_configured_admin_tokens()
    if not tokens:
        return False

    # 1. Check Authorization: Bearer <token>
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        for expected in tokens:
            if secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
                return True

    # 2. Check Cookie: fcc_admin_token
    cookie_token = request.cookies.get("fcc_admin_token", "").strip()
    if cookie_token:
        for expected in tokens:
            if secrets.compare_digest(cookie_token.encode("utf-8"), expected.encode("utf-8")):
                return True

    # 3. Check Query parameter: ?token=
    query_token = request.query_params.get("token", "").strip()
    if query_token:
        for expected in tokens:
            if secrets.compare_digest(query_token.encode("utf-8"), expected.encode("utf-8")):
                return True

    # 4. Check x-api-key or x-admin-token headers
    for header_name in ("x-admin-token", "x-api-key"):
        header_token = request.headers.get(header_name, "").strip()
        if header_token:
            for expected in tokens:
                if secrets.compare_digest(header_token.encode("utf-8"), expected.encode("utf-8")):
                    return True

    return False


def require_loopback_admin(request: Request) -> None:
    """Allow Admin access from local loopback or authenticated remote cloud users."""
    client_host = request.client.host if request.client else None

    # Check if this is a genuine local loopback connection
    if (
        _is_loopback_host(client_host)
        and _authority_is_local(request.headers.get("host"))
        and _origin_is_local(request.headers.get("origin"))
    ):
        return

    # If not local loopback, verify cloud / remote authentication
    if is_authorized_admin(request):
        return

    if _is_cloud_environment():
        accept = request.headers.get("accept", "")
        if "text/html" in accept and request.method == "GET":
            from urllib.parse import quote

            next_path = quote(str(request.url.path))
            raise HTTPException(
                status_code=307,
                headers={"Location": f"/login?next={next_path}"},
            )
        raise HTTPException(
            status_code=401,
            detail=(
                "Unauthorized: Valid admin authentication token required. "
                "Provide via Authorization Bearer header, fcc_admin_token cookie, or ?token= query parameter."
            ),
        )

    # In local mode without cloud tokens, reject remote access
    raise HTTPException(status_code=403, detail="Admin UI is local-only")


# Canonical alias for cloud and modern routes
require_cloud_admin = require_loopback_admin
