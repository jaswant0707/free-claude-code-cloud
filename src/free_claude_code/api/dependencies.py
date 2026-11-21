"""FastAPI dependencies for the explicit runtime service boundary."""

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


def require_proxy_auth(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Require the configured proxy token as HTTP bearer authorization."""
    if not is_proxy_auth_required(settings):
        return

    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing proxy authentication token",
        )

    if not _proxy_token_matches(
        authorization,
        settings.proxy_auth_token,
        require_bearer=True,
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

    authorization = request.headers.get("authorization")
    if authorization is not None:
        if _proxy_token_matches(
            authorization,
            settings.proxy_auth_token,
            require_bearer=True,
        ):
            return
        raise HTTPException(
            status_code=401,
            detail="Invalid proxy authentication token",
        )

    x_api_key = request.headers.get("x-api-key")
    if x_api_key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing proxy authentication token",
        )

    if not _proxy_token_matches(
        x_api_key,
        settings.proxy_auth_token,
        require_bearer=False,
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
    credential = request.headers.get("authorization")
    bearer = credential is not None
    if credential is None:
        credential = request.headers.get("x-goog-api-key")
    if credential is None:
        credential = keys[0] if keys else None
    if credential is None:
        raise HTTPException(
            status_code=401, detail="Missing proxy authentication token"
        )
    if not _proxy_token_matches(
        credential, settings.proxy_auth_token, require_bearer=bearer
    ):
        raise HTTPException(
            status_code=401, detail="Invalid proxy authentication token"
        )


def _proxy_token_matches(
    credential: str,
    configured_token: str,
    *,
    require_bearer: bool,
) -> bool:
    token = credential.strip()
    if require_bearer:
        parts = token.split(maxsplit=1)
        if len(parts) != 2 or parts[0].casefold() != "bearer":
            return False
        token = parts[1].strip()

    if not token:
        return False

    from .admin_security import is_cloud_environment

    is_cloud = is_cloud_environment()
    valid_tokens: list[str] = []

    # 1. Configured token from Settings
    # In cloud environments, the publicly guessable default 'freecc' is strictly disallowed.
    if configured_token:
        if not is_cloud or configured_token != "freecc":
            valid_tokens.append(configured_token)

    # 2. External API tokens from environment (Admin tokens are strictly excluded)
    for env_var in (
        "MASTER_API_TOKEN",
        "PROXY_AUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        env_val = os.getenv(env_var, "").strip()
        if env_val and env_val not in valid_tokens:
            if not is_cloud or env_val != "freecc":
                valid_tokens.append(env_val)

    # 3. In local development mode, if no custom token was configured, allow configured default
    if not valid_tokens and not is_cloud and configured_token:
        valid_tokens.append(configured_token)

    return any(
        secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
        for expected in valid_tokens
    )
