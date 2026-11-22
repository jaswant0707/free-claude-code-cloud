"""Admin endpoints for Persistent AI Model Test Playground & Chat Sessions."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from free_claude_code.application.routing import ModelRouter
from free_claude_code.core.chat_completions.request import ChatRequest
from free_claude_code.persistence.supabase_client import get_supabase_client
from .admin_security import require_loopback_admin
from .dependencies import get_services, resolve_provider
from .handlers.chat import ChatHandler
from .ports import ApiServices

router = APIRouter(dependencies=[Depends(require_loopback_admin)])


class CreateSessionPayload(BaseModel):
    title: str = Field(default="New Test Session", min_length=1, max_length=200)
    selected_model: str = Field(default="auto")
    provider_hint: str | None = None


class ChatPayload(BaseModel):
    prompt: str = Field(min_length=1)
    model: str = Field(default="auto")
    system_prompt: str | None = None


@router.get("/admin/api/playground/sessions")
async def list_playground_sessions(request: Request):
    """List all model test sessions stored in Supabase."""
    client = get_supabase_client()
    if not client.is_configured:
        return {"sessions": []}
    sessions = client.list_model_test_sessions()
    return {"sessions": sessions}


@router.post("/admin/api/playground/sessions")
async def create_playground_session(
    payload: CreateSessionPayload,
    request: Request,
):
    """Create a new model test session."""
    client = get_supabase_client()
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Database not configured")

    session_id = str(uuid.uuid4())
    record = client.upsert_model_test_session(
        session_id=session_id,
        title=payload.title,
        selected_model=payload.selected_model,
        provider_hint=payload.provider_hint,
    )
    return {"status": "created", "id": session_id, "session": record}


@router.get("/admin/api/playground/sessions/{session_id}")
async def get_playground_session(
    session_id: str,
    request: Request,
):
    """Get a model test session with all historical messages."""
    client = get_supabase_client()
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Database not configured")

    data = client.get_model_test_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Playground session not found")
    return data


@router.delete("/admin/api/playground/sessions/{session_id}")
async def delete_playground_session(
    session_id: str,
    request: Request,
):
    """Delete a playground session and all its messages."""
    client = get_supabase_client()
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Database not configured")

    success = client.delete_model_test_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Playground session not found")
    return {"status": "deleted", "session_id": session_id}


@router.post("/admin/api/playground/sessions/{session_id}/chat")
async def send_playground_chat(
    session_id: str,
    payload: ChatPayload,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    """Execute a test prompt against the proxy runtime and persist history."""
    client = get_supabase_client()
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Database not configured")

    # 1. Record user message in Supabase
    user_msg = client.add_model_test_message(
        session_id=session_id,
        role="user",
        content=payload.prompt,
    )

    # 2. Acquire request runtime lease
    lease = await services.requests.acquire()
    start_time = time.perf_counter()
    assistant_text = ""
    resolved_provider = None
    resolved_model = None
    tokens_used = None
    error_detail = None

    try:
        await lease.wait_for_token_estimation()
        
        # Determine model
        target_model = payload.model if payload.model and payload.model != "auto" else lease.settings.model
        router_inst = ModelRouter(lease.settings)
        try:
            route = router_inst.resolve(target_model)
            resolved_provider = route.primary.provider_id
            resolved_model = route.primary.provider_model
        except Exception:
            resolved_provider = "auto"
            resolved_model = target_model

        # Build messages history for context
        history_msgs = []
        if payload.system_prompt:
            history_msgs.append({"role": "system", "content": payload.system_prompt})

        # Load recent messages from Supabase
        session_data = client.get_model_test_session(session_id)
        if session_data and session_data.get("messages"):
            for m in session_data["messages"]:
                if m.get("content") and m.get("role") in ("system", "user", "assistant"):
                    history_msgs.append({"role": m["role"], "content": m["content"]})
        else:
            history_msgs.append({"role": "user", "content": payload.prompt})

        # Ensure last message is current user prompt
        if not history_msgs or history_msgs[-1].get("content") != payload.prompt:
            history_msgs.append({"role": "user", "content": payload.prompt})

        chat_handler = ChatHandler(
            lease.settings,
            lambda p_type, key_num: resolve_provider(p_type, key_num, lease=lease),
            generation_id=lease.generation_id,
            request_headers=request.headers,
            model_info_lookup=lease.model_info,
        )

        chat_req = ChatRequest.model_validate({
            "model": target_model,
            "messages": history_msgs,
            "stream": False,
        })

        resp = await chat_handler.create(chat_req, request_id=f"test_{uuid.uuid4().hex[:8]}")
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # Parse response body
        if hasattr(resp, "body"):
            try:
                body_dict = json.loads(resp.body.decode("utf-8"))
                if "choices" in body_dict and body_dict["choices"]:
                    assistant_text = body_dict["choices"][0].get("message", {}).get("content", "")
                elif "detail" in body_dict:
                    error_detail = str(body_dict["detail"])
                if "usage" in body_dict:
                    tokens_used = body_dict["usage"].get("total_tokens")
                if "model" in body_dict:
                    resolved_model = body_dict["model"]
            except Exception as e:
                assistant_text = f"[Response received with status {getattr(resp, 'status_code', 200)}]"
        else:
            assistant_text = "[Response completed]"

    except Exception as exc:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        error_detail = str(exc)
        assistant_text = f"Error executing model: {exc}"
    finally:
        await lease.release()

    # 3. Record assistant message in Supabase
    asst_msg = client.add_model_test_message(
        session_id=session_id,
        role="assistant",
        content=assistant_text,
        resolved_provider=resolved_provider,
        resolved_model=resolved_model,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
        error_detail=error_detail,
    )

    return {
        "status": "ok" if not error_detail else "error",
        "session_id": session_id,
        "content": assistant_text,
        "resolved_provider": resolved_provider,
        "resolved_model": resolved_model,
        "latency_ms": latency_ms,
        "tokens_used": tokens_used,
        "error_detail": error_detail,
        "message": asst_msg,
    }
