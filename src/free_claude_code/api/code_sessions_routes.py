"""Local Admin commands, snapshots and SSE for coding conversations."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator, Mapping
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field

from free_claude_code.application.code_sessions import (
    CodeApplicationPort,
    CodeDetail,
    CodeItem,
    CodePrompt,
    CodeRun,
    CodeSession,
    CodeUnavailableError,
    CodeValidationError,
)
from free_claude_code.application.code_sessions.models import CodeMode
from free_claude_code.application.errors import ApplicationUnavailableError
from free_claude_code.application.session_events import EventOverflowError
from free_claude_code.config.model_refs import split_provider_model_ref
from free_claude_code.core.json_types import JsonObject, JsonValue

from .admin_routes import admin_page_response
from .admin_security import (
    is_authorized_admin,
    is_cloud_environment,
    require_loopback_admin,
)
from .dependencies import get_services
from .markdown import render_markdown
from .ports import ApiServices

router = APIRouter(dependencies=[Depends(require_loopback_admin)])


class CommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreatePayload(CommandPayload):
    session_id: str
    cwd: str = Field(min_length=1, max_length=4096)
    harness: Literal["codex"] = "codex"


class FolderPickerPayload(CommandPayload):
    initial_path: str | None = Field(default=None, max_length=4096)


class ExecPayload(CommandPayload):
    command: str = Field(min_length=1, max_length=10000)
    timeout: float = Field(default=30.0, ge=1.0, le=300.0)
    background: bool = Field(default=False)


class JobPayload(CommandPayload):
    command: str = Field(min_length=1, max_length=10000)
    timeout: float = Field(default=120.0, ge=1.0, le=600.0)


class SettingsPayload(CommandPayload):
    expected_revision: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, min_length=1)
    reasoning_effort: str | None = None
    mode: CodeMode = "config"


class SendPayload(CommandPayload):
    operation_id: str
    expected_revision: int = Field(gt=0)
    expected_epoch: str
    text: str = Field(min_length=1, max_length=1_000_000)


class StopPayload(CommandPayload):
    operation_id: str


class AnswerPayload(CommandPayload):
    response_id: str
    answer: JsonObject


def _code(services: ApiServices) -> CodeApplicationPort:
    if services.code is None:
        raise CodeUnavailableError("Code sessions is unavailable in this FCC runtime.")
    return services.code


@router.get("/admin/code", include_in_schema=False)
@router.get("/admin/code/{session_id}", include_in_schema=False)
def code_page(request: Request, session_id: str | None = None):
    require_loopback_admin(request)
    return admin_page_response()


@router.get("/admin/api/code/bootstrap")
async def bootstrap(services: ApiServices = Depends(get_services)) -> JsonObject:
    code = _code(services)
    if hasattr(code, "start"):
        try:
            import asyncio
            await asyncio.wait_for(code.start(), timeout=2.0)
        except Exception:
            pass
    available, message = code.availability()
    # In cloud deployments, if SQLite storage has completed startup, expose as available
    storage = code.storage_status()
    if not available and storage.get("state") in ("ready", "starting"):
        available = True
        message = None

    catalog = code.catalog()
    models_list = [model.model_dump(mode="json") for model in catalog.models]
    if not models_list:
        try:
            from free_claude_code.application.model_catalog import read_model_catalog
            req_catalog = read_model_catalog(services.requests)
            for m in req_catalog.models:
                try:
                    pid, mname = split_provider_model_ref(m.provider_model_ref)
                except ValueError:
                    pid, mname = "fcc", m.provider_model_ref
                models_list.append({
                    "id": m.provider_model_ref,
                    "display_name": m.display_name,
                    "provider_id": pid,
                    "model_name": mname,
                    "reasoning_efforts": ("off",),
                    "default_reasoning_effort": "off",
                    "context_window_tokens": m.context_window_tokens or 128000,
                })
        except Exception:
            pass

    if not models_list:
        fallback_models = [
            ("free-claude-universal", "Universal Fast & Smart Routing", "universal", "free-claude-universal"),
            ("groq/llama-3.3-70b-versatile", "Groq / Llama 3.3 70B", "groq", "llama-3.3-70b-versatile"),
            ("open_router/anthropic/claude-3.5-sonnet", "OpenRouter / Claude 3.5 Sonnet", "open_router", "anthropic/claude-3.5-sonnet"),
            ("openai_api/gpt-4o", "OpenAI / GPT-4o", "openai_api", "gpt-4o"),
            ("gemini/gemini-2.0-flash", "Gemini 2.0 Flash", "gemini", "gemini-2.0-flash"),
            ("deepseek/deepseek-chat", "DeepSeek Chat (V3)", "deepseek", "deepseek-chat"),
        ]
        for mid, dname, pid, mname in fallback_models:
            models_list.append({
                "id": mid,
                "display_name": dname,
                "provider_id": pid,
                "model_name": mname,
                "reasoning_efforts": ("off",),
                "default_reasoning_effort": "off",
                "context_window_tokens": 128000,
            })

    return {
        "available": available,
        "message": message,
        "storage": storage,
        "startup": services.requests.catalog_status(),
        "harnesses": [{"id": "codex", "name": "Codex"}],
        "epoch": code.epoch,
        "models": models_list,
        "default_model": catalog.default_model or "free-claude-universal",
    }


@router.post("/admin/api/code/folder-picker")
async def pick_folder(
    payload: FolderPickerPayload, services: ApiServices = Depends(get_services)
) -> JsonObject:
    from free_claude_code.api.admin_security import is_cloud_environment
    from free_claude_code.runtime.cloud_workspace import get_workspaces_root

    if is_cloud_environment():
        ws_root = get_workspaces_root()
        return {"path": str(ws_root)}

    try:
        return {"path": await services.admin.pick_folder(payload.initial_path)}
    except ApplicationUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc


@router.get("/admin/api/code/events", response_class=EventSourceResponse)
async def events(
    request: Request,
    cursor: str | None = Query(default=None),
    timeout: float | None = Query(default=None),
    services: ApiServices = Depends(get_services),
) -> AsyncIterator[ServerSentEvent]:
    code = _code(services)
    subscription, ready = await code.subscribe()

    # Determine client cursor from Last-Event-ID header or query param
    raw_cursor = request.headers.get("last-event-id") or cursor
    client_cursor: int | None = None
    if raw_cursor:
        try:
            client_cursor = int(raw_cursor)
        except ValueError:
            pass

    try:
        # Reconnection branch vs Initial connection branch
        if client_cursor is not None and hasattr(code, "events_since"):
            missed_events, resync_required = code.events_since(client_cursor)
            if resync_required:
                yield ServerSentEvent(
                    event="feed.resync_required",
                    id=str(subscription.cursor),
                    retry=1000,
                    data={"cursor": subscription.cursor},
                )
            else:
                for missed in missed_events:
                    yield ServerSentEvent(
                        event=missed.event,
                        id=str(missed.id),
                        retry=1000,
                        data={**_event_payload(missed.data), "cursor": missed.id},
                    )
        else:
            summaries = ready.get("sessions")
            if isinstance(summaries, list):
                ready = {
                    **ready,
                    "sessions": [
                        _event_payload(value)
                        for value in summaries
                        if isinstance(value, Mapping)
                    ],
                }
            yield ServerSentEvent(
                event="feed.ready", id=str(subscription.cursor), retry=1000, data=ready
            )

        # Bounded streaming loop: in cloud environments (Vercel), default to 20s to
        # prevent 60-second execution timeouts. Client will reconnect with Last-Event-ID.
        is_cloud = is_cloud_environment()
        if timeout is not None:
            max_duration = min(float(timeout), 25.0) if is_cloud else float(timeout)
        else:
            max_duration = 20.0 if is_cloud else 1800.0

        loop = asyncio.get_running_loop()
        start_time = loop.time()

        while True:
            if await request.is_disconnected():
                break

            elapsed = loop.time() - start_time
            if elapsed >= max_duration:
                # Clean exit before serverless timeout
                break

            wait_slice = min(5.0, max(0.1, max_duration - elapsed))
            try:
                event = await asyncio.wait_for(subscription.next_event(), timeout=wait_slice)
                if event is None:
                    break
                yield ServerSentEvent(
                    event=event.event,
                    id=str(event.id),
                    retry=1000,
                    data={**_event_payload(event.data), "cursor": event.id},
                )
            except asyncio.TimeoutError:
                yield ServerSentEvent(comment="ping")
    except EventOverflowError as exc:
        yield ServerSentEvent(
            event="feed.resync_required",
            id=str(exc.cursor),
            retry=1000,
            data={"cursor": exc.cursor},
        )
    finally:
        await subscription.aclose()


@router.get("/admin/api/code/events/poll")
async def poll_events(
    request: Request,
    cursor: int | None = Query(default=None),
    timeout: float = Query(default=15.0, ge=0.0, le=25.0),
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    """Cursor-based event polling endpoint for serverless architectures."""
    code = _code(services)
    if cursor is None:
        _, ready = await code.subscribe()
        summaries = ready.get("sessions")
        if isinstance(summaries, list):
            ready = {
                **ready,
                "sessions": [
                    _event_payload(value)
                    for value in summaries
                    if isinstance(value, Mapping)
                ],
            }
        return {
            "ready": True,
            "epoch": getattr(code, "epoch", "default"),
            "cursor": code.cursor,
            "resync_required": False,
            "events": [],
            "data": ready,
        }

    if hasattr(code, "events_since"):
        missed, resync = code.events_since(cursor)
        if resync:
            return {
                "ready": False,
                "cursor": code.cursor,
                "resync_required": True,
                "events": [],
            }
        if missed:
            return {
                "ready": False,
                "cursor": code.cursor,
                "resync_required": False,
                "events": [
                    {"event": e.event, "id": e.id, "data": _event_payload(e.data)}
                    for e in missed
                ],
            }

    if timeout <= 0:
        return {
            "ready": False,
            "cursor": code.cursor,
            "resync_required": False,
            "events": [],
        }

    subscription, _ = await code.subscribe()
    try:
        event = await asyncio.wait_for(subscription.next_event(), timeout=timeout)
        if event is not None:
            return {
                "ready": False,
                "cursor": code.cursor,
                "resync_required": False,
                "events": [
                    {"event": event.event, "id": event.id, "data": _event_payload(event.data)}
                ],
            }
    except (asyncio.TimeoutError, EventOverflowError):
        pass
    finally:
        await subscription.aclose()

    return {
        "ready": False,
        "cursor": code.cursor,
        "resync_required": False,
        "events": [],
    }


_hydrated_cloud_sessions: bool = False


@router.get("/admin/api/code/sessions")
async def list_sessions(
    cursor: str | None = None,
    query: str = Query(default="", max_length=4096),
    limit: int = Query(default=25, ge=1, le=25),
    request: Request = None,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    code = _code(services)
    if hasattr(code, "start"):
        try:
            import asyncio
            await asyncio.wait_for(code.start(), timeout=2.0)
        except Exception:
            pass

    global _hydrated_cloud_sessions
    # Hydrate any persistent cloud sessions from Supabase once (in cloud/runtime mode, skip during unit tests)
    if not _hydrated_cloud_sessions and not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            from free_claude_code.persistence.supabase_client import get_supabase_client
            client = get_supabase_client()
            if client.is_configured:
                session_owner = "jaswanty132@gmail.com"
                if request is not None:
                    try:
                        from free_claude_code.api.owner_auth import extract_session_from_request
                        sinfo = extract_session_from_request(request)
                        if sinfo and sinfo.get("email"):
                            session_owner = sinfo["email"]
                    except Exception:
                        pass
                cloud_sessions = client.list_code_sessions(session_owner)
                for cs in cloud_sessions:
                    try:
                        await code.create_session(cs["id"], cs["workspace_dir"])
                    except Exception:
                        pass
                _hydrated_cloud_sessions = True
        except Exception:
            pass

    snapshot_cursor = code.cursor
    page = await code.list_sessions(_decode_cursor(cursor), limit, query)
    return {
        "sessions": [_session_payload(session) for session in page.sessions],
        "next_cursor": _encode_cursor(page.next_cursor),
        "epoch": code.epoch,
        "cursor": snapshot_cursor,
    }


@router.post("/admin/api/code/sessions", status_code=201)
async def create(
    payload: CreatePayload,
    request: Request,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    from free_claude_code.runtime.cloud_workspace import prepare_workspace

    session_owner = "jaswanty132@gmail.com"
    try:
        from free_claude_code.api.owner_auth import extract_session_from_request

        session_info = extract_session_from_request(request)
        if session_info and session_info.get("email"):
            session_owner = session_info["email"]
    except Exception:
        pass

    resolved_cwd = await prepare_workspace(
        payload.session_id,
        repo_url_or_path=payload.cwd,
        owner_email=session_owner,
    )

    code = _code(services)
    if hasattr(code, "start"):
        try:
            import asyncio
            await asyncio.wait_for(code.start(), timeout=2.0)
        except Exception:
            pass

    return _session_payload(
        await code.create_session(payload.session_id, resolved_cwd)
    )


@router.post("/admin/api/code/sessions/{session_id}/exec")
async def execute_session_command(
    session_id: str,
    payload: ExecPayload,
    request: Request,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    from free_claude_code.api.admin_security import is_cloud_environment
    from free_claude_code.runtime.cloud_workspace import (
        execute_command,
        start_background_command,
    )

    session_owner = "jaswanty132@gmail.com"
    try:
        from free_claude_code.api.owner_auth import extract_session_from_request

        session_info = extract_session_from_request(request)
        if session_info and session_info.get("email"):
            session_owner = session_info["email"]
    except Exception:
        pass

    # If background execution is explicitly requested OR running in cloud serverless with timeout > 25s,
    # immediately start a background task to prevent Vercel 60-second gateway timeout.
    if payload.background or (is_cloud_environment() and payload.timeout > 25.0):
        task_info = await start_background_command(
            session_id,
            payload.command,
            timeout=payload.timeout,
            owner_email=session_owner,
        )
        return {
            **task_info,
            "background": True,
            "message": "Command running as background task. Poll /runs/{task_id} or stream logs via SSE.",
        }

    return await execute_command(
        session_id,
        payload.command,
        timeout=payload.timeout,
        owner_email=session_owner,
    )


@router.post("/admin/api/code/sessions/{session_id}/jobs", status_code=202)
async def create_background_job(
    session_id: str,
    payload: JobPayload,
    request: Request,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    """Launch a non-blocking background job, returning immediately with task_id for polling/streaming."""
    from free_claude_code.runtime.cloud_workspace import start_background_command

    session_owner = "jaswanty132@gmail.com"
    try:
        from free_claude_code.api.owner_auth import extract_session_from_request

        session_info = extract_session_from_request(request)
        if session_info and session_info.get("email"):
            session_owner = session_info["email"]
    except Exception:
        pass

    return await start_background_command(
        session_id,
        payload.command,
        timeout=payload.timeout,
        owner_email=session_owner,
    )


@router.get("/admin/api/code/sessions/{session_id}/runs/{task_id}")
async def get_job_run_status(
    session_id: str,
    task_id: str,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    """Retrieve status, live partial logs, exit code, and timing for a specific run."""
    from free_claude_code.runtime.cloud_workspace import get_command_task_status

    status = await get_command_task_status(session_id, task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Background job run not found.")
    return status


@router.post("/admin/api/code/sessions/{session_id}/runs/{task_id}/cancel")
async def cancel_job_run(
    session_id: str,
    task_id: str,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    """Cancel a running background job and clean up its process tree."""
    from free_claude_code.runtime.cloud_workspace import cancel_command_task

    cancelled = await cancel_command_task(session_id, task_id)
    return {"session_id": session_id, "task_id": task_id, "cancelled": cancelled}


@router.get(
    "/admin/api/code/sessions/{session_id}/runs/{task_id}/stream",
    response_class=EventSourceResponse,
)
async def stream_job_run_logs(
    session_id: str,
    task_id: str,
    services: ApiServices = Depends(get_services),
) -> AsyncIterator[ServerSentEvent]:
    """SSE stream yielding real-time chunks of stdout/stderr and final job completion event."""
    from free_claude_code.runtime.cloud_workspace import get_command_task_status
    import asyncio

    last_stdout_len = 0
    last_stderr_len = 0
    poll_intervals = 0
    max_idle_polls = 240  # 120s max streaming connection

    while poll_intervals < max_idle_polls:
        status = await get_command_task_status(session_id, task_id)
        if not status:
            yield ServerSentEvent(event="job.error", data={"error": "Job run not found"})
            break

        cur_stdout = status.get("stdout", "")
        cur_stderr = status.get("stderr", "")
        new_stdout = cur_stdout[last_stdout_len:]
        new_stderr = cur_stderr[last_stderr_len:]

        if new_stdout or new_stderr:
            last_stdout_len = len(cur_stdout)
            last_stderr_len = len(cur_stderr)
            yield ServerSentEvent(
                event="job.chunk",
                data={
                    "task_id": task_id,
                    "stdout_chunk": new_stdout,
                    "stderr_chunk": new_stderr,
                    "status": status.get("status"),
                },
            )

        if status.get("status") in ("completed", "failed", "cancelled", "timeout"):
            yield ServerSentEvent(
                event="job.completed",
                data=status,
            )
            break

        await asyncio.sleep(0.5)
        poll_intervals += 1


@router.get("/admin/api/code/sessions/{session_id}/runs")
async def list_session_runs(
    session_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    """List historical and active code runs for a session."""
    from free_claude_code.persistence.supabase_client import get_supabase_client

    client = get_supabase_client()
    runs = client.list_code_runs(session_id, limit=limit) if client.is_configured else []
    return {"session_id": session_id, "runs": runs}


@router.post("/admin/api/code/sessions/{session_id}/cancel")
async def cancel_command(
    session_id: str,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    from free_claude_code.runtime.cloud_workspace import cancel_session_command

    cancelled = await cancel_session_command(session_id)
    return {"session_id": session_id, "cancelled": cancelled}


@router.get("/admin/api/code/sessions/{session_id}")
async def detail(
    session_id: str,
    include_item_ids: tuple[str, ...] = Query(default=()),
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    return _detail_payload(
        await _code(services).get_detail(session_id, include_item_ids=include_item_ids)
    )


@router.get("/admin/api/code/sessions/{session_id}/items")
async def older_items(
    session_id: str,
    before: str,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    return _detail_payload(
        await _code(services).get_detail(session_id, before=_decode_item_cursor(before))
    )


@router.patch("/admin/api/code/sessions/{session_id}")
async def update_settings(
    session_id: str,
    payload: SettingsPayload,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    return _session_payload(
        await _code(services).update_settings(
            session_id,
            payload.expected_revision,
            payload.model_dump(exclude={"expected_revision"}, exclude_unset=True),
        )
    )


@router.delete("/admin/api/code/sessions/{session_id}", status_code=202)
async def delete(
    session_id: str,
    expected_revision: int = Query(gt=0),
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    session = await _code(services).delete_session(session_id, expected_revision)
    return {
        "session_id": session_id,
        "deleted": session is None,
        "session": _session_payload(session) if session else None,
    }


@router.post("/admin/api/code/sessions/{session_id}/turns", status_code=202)
async def send(
    session_id: str, payload: SendPayload, services: ApiServices = Depends(get_services)
) -> JsonObject:
    return _run_payload(
        await _code(services).send(
            session_id,
            payload.operation_id,
            payload.expected_revision,
            payload.text,
            expected_epoch=payload.expected_epoch,
        )
    )


@router.post("/admin/api/code/sessions/{session_id}/stop", status_code=202)
async def stop(
    session_id: str, payload: StopPayload, services: ApiServices = Depends(get_services)
) -> JsonObject:
    return _run_payload(await _code(services).stop(session_id, payload.operation_id))


@router.post(
    "/admin/api/code/sessions/{session_id}/prompts/{prompt_id}/responses",
    status_code=202,
)
async def answer(
    session_id: str,
    prompt_id: str,
    payload: AnswerPayload,
    services: ApiServices = Depends(get_services),
) -> JsonObject:
    return _prompt_payload(
        await _code(services).answer(
            session_id, prompt_id, payload.response_id, payload.answer
        )
    )


def _session_payload(session: CodeSession) -> JsonObject:
    provider_id, model_name = split_provider_model_ref(session.model)
    return {
        **session.model_dump(
            mode="json",
            exclude={
                "native_thread_id",
                "native_may_have_input",
                "native_permission_defaults",
                "auto_title",
            },
        ),
        "provider_id": provider_id,
        "model_name": model_name,
    }


def _run_payload(run: CodeRun) -> JsonObject:
    return run.model_dump(mode="json", exclude={"native_turn_id", "submission_started"})


def _item_payload(item: CodeItem) -> JsonObject:
    return {
        **item.model_dump(
            mode="json", exclude={"raw", "native_turn_id", "native_item_id"}
        ),
        "html": render_markdown(item.text)
        if item.kind in {"text", "reasoning"}
        else None,
    }


def _prompt_payload(prompt: CodePrompt) -> JsonObject:
    return prompt.model_dump(
        mode="json",
        exclude={"raw", "generation", "request_id", "native_turn_id", "native_item_id"},
    )


def _detail_payload(detail: CodeDetail) -> JsonObject:
    return {
        "session": _session_payload(detail.session),
        "run": _run_payload(detail.run) if detail.run else None,
        "runs": [_run_payload(run) for run in detail.runs],
        "active_prompt_ids": list(detail.active_prompt_ids),
        "active_review_ids": list(detail.active_review_ids),
        "items": [_item_payload(item) for item in detail.items],
        "prompts": [_prompt_payload(prompt) for prompt in detail.prompts],
        "epoch": detail.epoch,
        "version": detail.version,
        "cursor": detail.cursor,
        "next_before": _encode_cursor(detail.next_before),
    }


def _event_payload(data: Mapping[str, JsonValue]) -> JsonObject:
    result = dict(data)
    if isinstance(data.get("session"), Mapping):
        result["session"] = _session_payload(
            CodeSession.model_validate(data["session"])
        )
    if isinstance(data.get("run"), Mapping):
        result["run"] = _run_payload(CodeRun.model_validate(data["run"]))
    if isinstance(data.get("item"), Mapping):
        result["item"] = _item_payload(CodeItem.model_validate(data["item"]))
    if isinstance(data.get("prompt"), Mapping):
        result["prompt"] = _prompt_payload(CodePrompt.model_validate(data["prompt"]))
    items = data.get("items")
    if isinstance(items, list):
        result["items"] = [
            _item_payload(CodeItem.model_validate(value)) for value in items
        ]
    prompts = data.get("prompts")
    runs = data.get("runs")
    if isinstance(runs, list):
        result["runs"] = [_run_payload(CodeRun.model_validate(value)) for value in runs]
    if isinstance(prompts, list):
        result["prompts"] = [
            _prompt_payload(CodePrompt.model_validate(value)) for value in prompts
        ]
    return result


def _encode_cursor(cursor: tuple[int, str] | tuple[int, int] | None) -> str | None:
    return (
        base64.urlsafe_b64encode(json.dumps(cursor).encode()).decode()
        if cursor
        else None
    )


def _decode_cursor(cursor: str | None) -> tuple[int, str] | None:
    if cursor is None:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor).decode())
        if (
            not isinstance(value, list)
            or len(value) != 2
            or type(value[0]) is not int
            or not isinstance(value[1], str)
        ):
            raise ValueError
        return value[0], value[1]
    except (ValueError, UnicodeError):
        raise CodeValidationError("Invalid session page cursor.") from None


def _decode_item_cursor(cursor: str) -> tuple[int, int]:
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor).decode())
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(type(part) is not int or part < 1 for part in value)
        ):
            raise ValueError
        return value[0], value[1]
    except (ValueError, UnicodeError):
        raise CodeValidationError("Invalid transcript page cursor.") from None
