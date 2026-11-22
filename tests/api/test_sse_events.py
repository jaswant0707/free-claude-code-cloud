"""Tests for serverless-native SSE event delivery and cursor-based polling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from free_claude_code.application.session_events import EventPublisher, PublishedEvent


class _MockCodeSessions:
    def __init__(self):
        self._events = EventPublisher()
        self.epoch = "test-epoch-1"

    @property
    def cursor(self) -> int:
        return self._events.cursor

    def events_since(self, cursor: int):
        return self._events.events_since(cursor)

    async def subscribe(self):
        sub = self._events.subscribe()
        ready = {
            "epoch": self.epoch,
            "cursor": sub.cursor,
            "sessions": [{"session_id": "s1", "status": "ready"}],
        }
        return sub, ready

    def publish(self, event: str, data: dict):
        return self._events.publish(event, data)


@pytest.fixture
def mock_app(monkeypatch):
    monkeypatch.setenv("ADMIN_AUTH_TOKEN", "test-admin-token")
    from free_claude_code.config.loader import clear_settings_cache
    clear_settings_cache()
    from tests.api.support import create_test_app

    code = _MockCodeSessions()
    app = create_test_app(code=code)
    yield app, code
    clear_settings_cache()


@pytest.mark.asyncio
async def test_events_initial_connection_receives_feed_ready(mock_app):
    app, code = mock_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        # Request events with short timeout (0.5s) to exit cleanly
        async with client.stream(
            "GET",
            "/admin/api/code/events?timeout=0.5",
            headers={"Authorization": "Bearer test-admin-token"},
        ) as response:
            assert response.status_code == 200
            lines = []
            async for line in response.aiter_lines():
                lines.append(line)
                if "feed.ready" in line:
                    break

            feed_ready_found = any("event: feed.ready" in l for l in lines)
            assert feed_ready_found, f"Expected feed.ready in lines: {lines}"


@pytest.mark.asyncio
async def test_events_reconnect_with_last_event_id_replays_events_without_feed_ready(mock_app):
    app, code = mock_app
    # Publish 3 events
    e1 = code.publish("session.updated", {"session_id": "s1", "version": 1})
    e2 = code.publish("run.updated", {"session_id": "s1", "run_id": "r1"})
    e3 = code.publish("item.updated", {"session_id": "s1", "item_id": "i1"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        # Reconnect with Last-Event-ID: 1 (should replay e2 and e3, and NOT send feed.ready)
        async with client.stream(
            "GET",
            "/admin/api/code/events?timeout=0.5",
            headers={
                "Authorization": "Bearer test-admin-token",
                "Last-Event-ID": "1",
            },
        ) as response:
            assert response.status_code == 200
            lines = []
            async for line in response.aiter_lines():
                lines.append(line)
                if "item.updated" in line:
                    break

            # Should NOT have feed.ready
            assert not any("event: feed.ready" in l for l in lines)
            # Should have run.updated and item.updated
            assert any("event: run.updated" in l for l in lines)
            assert any("event: item.updated" in l for l in lines)


@pytest.mark.asyncio
async def test_events_reconnect_with_cursor_query_param(mock_app):
    app, code = mock_app
    e1 = code.publish("session.updated", {"session_id": "s1", "version": 1})
    e2 = code.publish("run.updated", {"session_id": "s1", "run_id": "r1"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        # Reconnect with ?cursor=1
        async with client.stream(
            "GET",
            "/admin/api/code/events?cursor=1&timeout=0.5",
            headers={"Authorization": "Bearer test-admin-token"},
        ) as response:
            assert response.status_code == 200
            lines = []
            async for line in response.aiter_lines():
                lines.append(line)
                if "run.updated" in line:
                    break

            assert not any("event: feed.ready" in l for l in lines)
            assert any("event: run.updated" in l for l in lines)


@pytest.mark.asyncio
async def test_events_reconnect_with_invalid_cursor_emits_resync_required(mock_app):
    app, code = mock_app
    code.publish("session.updated", {"session_id": "s1", "version": 1})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        # Reconnect with cursor 9999 (future cursor -> invalid -> resync required)
        async with client.stream(
            "GET",
            "/admin/api/code/events?cursor=9999&timeout=0.5",
            headers={"Authorization": "Bearer test-admin-token"},
        ) as response:
            assert response.status_code == 200
            lines = []
            async for line in response.aiter_lines():
                lines.append(line)
                if "feed.resync_required" in line:
                    break

            assert any("event: feed.resync_required" in l for l in lines)


@pytest.mark.asyncio
async def test_poll_events_endpoint(mock_app):
    app, code = mock_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        # 1. Initial poll without cursor returns ready snapshot
        r1 = await client.get(
            "/admin/api/code/events/poll",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["ready"] is True
        assert data1["epoch"] == "test-epoch-1"
        assert data1["cursor"] == 0

        # 2. Publish an event
        code.publish("session.updated", {"session_id": "s1", "status": "running"})

        # 3. Poll with cursor=0 returns the missed event
        r2 = await client.get(
            "/admin/api/code/events/poll?cursor=0&timeout=0",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["ready"] is False
        assert data2["cursor"] == 1
        assert len(data2["events"]) == 1
        assert data2["events"][0]["event"] == "session.updated"

        # 4. Poll with cursor=1 (up to date) returns empty events
        r3 = await client.get(
            "/admin/api/code/events/poll?cursor=1&timeout=0",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert r3.status_code == 200
        data3 = r3.json()
        assert data3["events"] == []
        assert data3["resync_required"] is False
