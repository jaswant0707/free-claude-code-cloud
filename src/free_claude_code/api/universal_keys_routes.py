"""Admin endpoints for managing Multi-Universal API Keys."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from free_claude_code.persistence.supabase_client import get_supabase_client
from free_claude_code.persistence.universal_keys import (
    generate_universal_key,
    invalidate_universal_key_cache,
)
from .admin_security import require_loopback_admin

router = APIRouter(dependencies=[Depends(require_loopback_admin)])


class CreateUniversalKeyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    default_model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    rate_limit_rpm: int = Field(default=60, ge=1, le=10000)
    expires_at: str | None = None


class ToggleUniversalKeyPayload(BaseModel):
    is_active: bool | None = None


@router.get("/admin/api/universal-keys")
async def list_universal_keys(request: Request):
    """List all universal API keys with usage stats and metadata."""
    client = get_supabase_client()
    if not client.is_configured:
        return {"keys": []}
    keys = client.list_universal_keys()
    return {"keys": keys}


@router.post("/admin/api/universal-keys")
async def create_universal_key_endpoint(
    payload: CreateUniversalKeyPayload,
    request: Request,
):
    """Generate a new universal API key.
    
    The raw secret key is only returned in this response and cannot be retrieved again.
    """
    client = get_supabase_client()
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Database not configured")

    result = generate_universal_key(
        name=payload.name,
        default_model=payload.default_model,
        fallback_models=payload.fallback_models,
        rate_limit_rpm=payload.rate_limit_rpm,
        expires_at=payload.expires_at,
    )
    return {
        "status": "created",
        "raw_key": result["raw_key"],
        "key_prefix": result["key_prefix"],
        "record": result["record"],
        "key": result["record"],
    }


@router.post("/admin/api/universal-keys/{key_id}/toggle")
async def toggle_universal_key_endpoint(
    key_id: str,
    request: Request,
    payload: ToggleUniversalKeyPayload | None = None,
):
    """Enable or revoke an existing universal API key."""
    client = get_supabase_client()
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Database not configured")

    target_active = None
    if payload and payload.is_active is not None:
        target_active = payload.is_active
    else:
        # Flip current state
        existing_keys = client.list_universal_keys()
        for k in existing_keys:
            if str(k.get("id")) == str(key_id):
                target_active = not bool(k.get("is_active", True))
                break
        if target_active is None:
            target_active = False

    success = client.toggle_universal_key(key_id, target_active)
    if not success:
        raise HTTPException(status_code=404, detail="Universal key not found")

    invalidate_universal_key_cache()
    return {"status": "ok", "key_id": key_id, "is_active": target_active}


@router.delete("/admin/api/universal-keys/{key_id}")
async def delete_universal_key_endpoint(
    key_id: str,
    request: Request,
):
    """Permanently delete a universal API key."""
    client = get_supabase_client()
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Database not configured")

    success = client.delete_universal_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail="Universal key not found")

    invalidate_universal_key_cache()
    return {"status": "deleted", "key_id": key_id}
