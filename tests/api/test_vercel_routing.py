"""Tests for Vercel path rewrite middleware in api/index.py."""

import os
import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse


@pytest.fixture(autouse=True)
def clean_vercel_env():
    """Ensure api/index.py import does not pollute subsequent tests with FCC_CLOUD_DEPLOYMENT."""
    old_cloud = os.environ.get("FCC_CLOUD_DEPLOYMENT")
    old_proxy = os.environ.get("PROXY_AUTH_ENABLED")
    yield
    if old_cloud is None:
        os.environ.pop("FCC_CLOUD_DEPLOYMENT", None)
    else:
        os.environ["FCC_CLOUD_DEPLOYMENT"] = old_cloud
    if old_proxy is None:
        os.environ.pop("PROXY_AUTH_ENABLED", None)
    else:
        os.environ["PROXY_AUTH_ENABLED"] = old_proxy


@pytest.mark.asyncio
async def test_vercel_path_middleware_handles_plus_and_headers():
    from api.index import _vercel_path_middleware

    async def mock_call_next(request: Request):
        return PlainTextResponse(f"path:{request.scope['path']}|qs:{request.scope['query_string'].decode('utf-8')}")

    # Case 1: x-matched-path header with literal '+'
    scope_header = {
        "type": "http",
        "method": "GET",
        "path": "/api/index.py",
        "raw_path": b"/api/index.py",
        "query_string": b"__url_path=/admin/assets/1.0.0+d8c7dc72/admin.css",
        "headers": [(b"x-matched-path", b"/admin/assets/1.0.0+d8c7dc72/admin.css")],
    }
    req = Request(scope_header)
    resp = await _vercel_path_middleware(req, mock_call_next)
    assert resp.body.decode() == "path:/admin/assets/1.0.0+d8c7dc72/admin.css|qs:"

    # Case 2: __url_path query parameter alone with literal '+'
    scope_qs = {
        "type": "http",
        "method": "GET",
        "path": "/api/index.py",
        "raw_path": b"/api/index.py",
        "query_string": b"__url_path=/admin/assets/1.0.0+d8c7dc72/admin.css&tab=keys",
        "headers": [],
    }
    req = Request(scope_qs)
    resp = await _vercel_path_middleware(req, mock_call_next)
    assert resp.body.decode() == "path:/admin/assets/1.0.0+d8c7dc72/admin.css|qs:tab=keys"

    # Case 3: __url_path query parameter with percent-encoded %2B
    scope_encoded = {
        "type": "http",
        "method": "GET",
        "path": "/api/index.py",
        "raw_path": b"/api/index.py",
        "query_string": b"__url_path=/admin/assets/1.0.0%2Bd8c7dc72/admin.css",
        "headers": [],
    }
    req = Request(scope_encoded)
    resp = await _vercel_path_middleware(req, mock_call_next)
    assert resp.body.decode() == "path:/admin/assets/1.0.0+d8c7dc72/admin.css|qs:"

    # Case 4: __url_path with percent-encoded space %20
    scope_space = {
        "type": "http",
        "method": "GET",
        "path": "/api/index.py",
        "raw_path": b"/api/index.py",
        "query_string": b"__url_path=/my%20workspace/run",
        "headers": [],
    }
    req = Request(scope_space)
    resp = await _vercel_path_middleware(req, mock_call_next)
    assert resp.body.decode() == "path:/my workspace/run|qs:"

    # Case 5: Root index path
    scope_root = {
        "type": "http",
        "method": "GET",
        "path": "/api/index.py",
        "raw_path": b"/api/index.py",
        "query_string": b"",
        "headers": [],
    }
    req = Request(scope_root)
    resp = await _vercel_path_middleware(req, mock_call_next)
    assert resp.body.decode() == "path:/|qs:"
