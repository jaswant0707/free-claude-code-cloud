"""FastAPI dependencies for the explicit runtime service boundary."""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, Request
from loguru import logger

from free_claude_code.application.errors import UnknownProviderError
from free_claude_code.application.ports import ProviderPort, RequestRuntimeLease
from free_claude_code.config.settings import Settings

from .ports import ApiServices


def get_services(request: Request) -> ApiServices:
    """Return the complete services supplied when the app was constructed."""
    return request.app.state.services


def get_settings(services: ApiServices = Depends(get_services)) -> Settings:
    """Return the current request-runtime settings snapshot."""
    return services.requests.current_settings()


async def resolve_provider(
    provider_type: str,
    api_key_number: int = 1,
    *,
    lease: RequestRuntimeLease,
) -> ProviderPort:
    """Resolve a provider through one retained generation."""
    should_log_init = not lease.is_provider_cached(provider_type, api_key_number)
    try:
        provider = await lease.resolve_provider(provider_type, api_key_number)
    except UnknownProviderError:
        logger.error(
            "Unknown provider_type: '{}'. Supported: {}",
            provider_type,
            ", ".join(f"'{key}'" for key in lease.settings.provider_ids),
        )
        raise
    if should_log_init:
        logger.info("Provider initialized: {} Key {}", provider_type, api_key_number)
    return provider


def is_proxy_auth_required(settings: Settings) -> bool:
    """Determine whether external API gateway proxy authentication is required."""
    if settings.proxy_auth_enabled:
        return True
    if os.getenv("MASTER_API_TOKEN", "").strip():
        return True
    if os.getenv("PROXY_AUTH_TOKEN", "").strip():
        return True
    if (
        os.getenv("FCC_CLOUD_DEPLOYMENT", "").lower() in ("1", "true", "yes")
        or os.getenv("VERCEL")
        or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    ):
        return True
    return False


def _extract_proxy_credential(request: Request) -> tuple[str | None, bool]:
    """Extract proxy credential from Authorization, x-api-key, or api-key headers.
    
    Returns (cleaned_token, had_bearer_prefix).
    """
    # 1. Check Authorization header
    auth = request.headers.get("authorization")
    if auth:
        auth_clean = auth.strip()
        if auth_clean.lower().startswith("bearer "):
            token = auth_clean[7:].strip().strip("'\"")
            if token:
                return token, True
        # Direct token in Authorization header without Bearer prefix
        token = auth_clean.strip("'\"")
        if token:
            return token, False

    # 2. Check x-api-key header (standard Anthropic & external gateway client header)
    x_api_key = request.headers.get("x-api-key")
    if x_api_key:
        token = x_api_key.strip().strip("'\"")
        if token:
            return token, False

    # 3. Check api-key header
    api_key = request.headers.get("api-key")
    if api_key:
        token = api_key.strip().strip("'\"")
        if token:
            return token, False

    return None, False


def require_proxy_auth(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Require the configured proxy token or active universal key as HTTP authorization."""
    if not is_proxy_auth_required(settings):
        return

    token, had_bearer = _extract_proxy_credential(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing proxy authentication token",
        )

    if not _validate_proxy_token(
        token,
        settings.proxy_auth_token,
        require_bearer=False if token.startswith("fcc_uk_") else True,
        had_bearer=had_bearer,
        request=request,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid proxy authentication token",
        )


def require_anthropic_proxy_auth(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Require Bearer or Anthropic ``x-api-key`` proxy authentication."""
    if not is_proxy_auth_required(settings):
        return

    token, had_bearer = _extract_proxy_credential(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing proxy authentication token",
        )

    if not _validate_proxy_token(
        token,
        settings.proxy_auth_token,
        require_bearer=False,
        had_bearer=had_bearer,
        request=request,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid proxy authentication token",
        )


def require_gemini_proxy_auth(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    keys = request.query_params.getlist("key")
    if len(keys) > 1:
        raise HTTPException(
            status_code=400, detail="Repeated key query credentials are unsupported"
        )
    if not is_proxy_auth_required(settings):
        return

    token, had_bearer = _extract_proxy_credential(request)
    if token is None:
        raw_key = request.headers.get("x-goog-api-key") or (keys[0] if keys else None)
        if raw_key:
            token = raw_key.strip().strip("'\"")
            had_bearer = False

    if not token:
        raise HTTPException(
            status_code=401, detail="Missing proxy authentication token"
        )

    if not _validate_proxy_token(
        token,
        settings.proxy_auth_token,
        require_bearer=False,
        had_bearer=had_bearer,
        request=request,
    ):
        raise HTTPException(
            status_code=401, detail="Invalid proxy authentication token"
        )


def _validate_proxy_token(
    token: str,
    configured_token: str,
    *,
    require_bearer: bool = False,
    had_bearer: bool = False,
    request: Request | None = None,
) -> bool:
    clean_token = token.strip().strip("'\"")
    if not clean_token:
        return False

    from .admin_security import is_cloud_environment, is_valid_admin_token

    # Admin tokens are strictly disallowed from authenticating as proxy tokens
    if is_valid_admin_token(clean_token):
        return False

    # Check active Universal Key (fcc_uk_ prefix)
    if clean_token.startswith("fcc_uk_"):
        try:
            from free_claude_code.persistence.universal_keys import verify_universal_key

            key_info = verify_universal_key(clean_token)
            if key_info is not None:
                if request is not None:
                    request.state.universal_key = key_info
                return True
            return False
        except Exception:
            return False

    # If endpoint strictly requires Bearer prefix for legacy proxy tokens
    if require_bearer and not had_bearer:
        return False

    is_cloud = is_cloud_environment()
    valid_tokens: list[str] = []

    # 1. Configured token from Settings
    # In cloud environments, the publicly guessable default 'freecc' is strictly disallowed.
    if configured_token:
        if not is_cloud or configured_token != "freecc":
            valid_tokens.append(configured_token)

    # 2. External API tokens from environment (Proxy-only tokens)
    for env_var in (
        "PROXY_AUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
        "MASTER_API_TOKEN",
    ):
        env_val = os.getenv(env_var, "").strip()
        if env_val and env_val not in valid_tokens:
            if not is_cloud or env_val != "freecc":
                if not is_valid_admin_token(env_val):
                    valid_tokens.append(env_val)

    # 3. Persistent proxy auth token from Supabase in cloud deployments
    if is_cloud and not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            from free_claude_code.persistence.supabase_client import get_supabase_client

            client = get_supabase_client()
            if client.is_configured:
                cloud_settings = client.get_app_settings()
                cloud_token = cloud_settings.get("ANTHROPIC_AUTH_TOKEN") or cloud_settings.get("PROXY_AUTH_TOKEN")
                if cloud_token and cloud_token not in valid_tokens and cloud_token != "freecc":
                    if not is_valid_admin_token(cloud_token):
                        valid_tokens.append(cloud_token)
        except Exception:
            pass

    # 4. In local development mode, if no custom token was configured, allow configured default
    if not valid_tokens and not is_cloud and configured_token:
        valid_tokens.append(configured_token)

    return any(
        secrets.compare_digest(clean_token.encode("utf-8"), expected.encode("utf-8"))
        for expected in valid_tokens
    )


def _proxy_token_matches(
    credential: str,
    configured_token: str,
    *,
    require_bearer: bool,
    request: Request | None = None,
) -> bool:
    """Backward-compatible wrapper for credential string matching."""
    token = credential.strip()
    had_bearer = False
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
        had_bearer = True

    return _validate_proxy_token(
        token,
        configured_token,
        require_bearer=require_bearer,
        had_bearer=had_bearer,
        request=request,
    )
