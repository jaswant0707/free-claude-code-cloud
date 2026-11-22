"""Vercel Serverless Function entry point for Free Claude Code Cloud."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

# Ensure project src and root directories are available in module search path
_CURRENT_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _CURRENT_DIR.parent
_SRC_DIR = _ROOT_DIR / "src"

for _p in (str(_SRC_DIR), str(_ROOT_DIR), str(_CURRENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Enforce cloud deployment flags and redirect writable state to /tmp
os.environ.setdefault("FCC_CLOUD_DEPLOYMENT", "1")
if "FCC_CONFIG_DIR" not in os.environ:
    os.environ["FCC_CONFIG_DIR"] = "/tmp/.fcc"

try:
    _cfg_path = Path(os.environ["FCC_CONFIG_DIR"])
    _cfg_path.mkdir(parents=True, exist_ok=True)
    (_cfg_path / "logs").mkdir(parents=True, exist_ok=True)
    (_cfg_path / "code").mkdir(parents=True, exist_ok=True)
    (_cfg_path / "auth").mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# In cloud deployments, default proxy auth to enabled if not explicitly specified
if "PROXY_AUTH_ENABLED" not in os.environ:
    os.environ["PROXY_AUTH_ENABLED"] = "true"

# Top-level FastAPI instance required by Vercel's build parser (docs disabled for security in cloud production)
app = FastAPI(
    title="Free Claude Code Cloud",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

try:
    from free_claude_code.config.loader import clear_settings_cache, get_settings
    from free_claude_code.runtime.bootstrap import build_asgi_app

    clear_settings_cache()
    settings = get_settings()
    _runtime_asgi = build_asgi_app(settings, app=app)
    app.state.runtime = _runtime_asgi.runtime

    @app.middleware("http")
    async def _vercel_path_middleware(request: Request, call_next):
        # Normalize rewritten paths from Vercel headers or rewrites
        target_path = None
        for header in ("x-matched-path", "x-forwarded-uri", "x-invoke-path"):
            val = request.headers.get(header)
            if val and val not in ("/api/index.py", "/api/index", "/api", "/api/"):
                target_path = val
                break

        raw_qs = request.scope.get("query_string", b"").decode("utf-8", errors="replace")

        if not target_path and "__url_path=" in raw_qs:
            from urllib.parse import unquote
            for part in raw_qs.split("&"):
                if part.startswith("__url_path="):
                    raw_val = part[len("__url_path="):]
                    # unquote decodes %20, %2B, etc., while preserving literal '+'
                    target_path = unquote(raw_val)
                    break

        if target_path:
            path_part, *qs_part = target_path.lstrip("/").split("?", 1)
            clean_path = "/" + path_part
            request.scope["path"] = clean_path
            request.scope["raw_path"] = clean_path.encode("utf-8")

            if "__url_path=" in raw_qs:
                filtered_parts = [
                    p for p in raw_qs.split("&") if not p.startswith("__url_path=") and p
                ]
                if qs_part and qs_part[0]:
                    filtered_parts.insert(0, qs_part[0])
                request.scope["query_string"] = "&".join(filtered_parts).encode("utf-8")

            if hasattr(request, "_url"):
                delattr(request, "_url")
        elif request.scope.get("path") in ("/api/index.py", "/api/index", "/api", "/api/"):
            request.scope["path"] = "/"
            request.scope["raw_path"] = b"/"
            if hasattr(request, "_url"):
                delattr(request, "_url")

        return await call_next(request)

except Exception:
    _err = traceback.format_exc()
    print(f"FCC Cloud Cold-Start Error:\n{_err}", file=sys.stderr, flush=True)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def _catch_all(request: Request, path: str = ""):
        # In production environments, never expose full stack traces or filesystem paths to clients
        return HTMLResponse(
            "<!doctype html><html><head><title>FCC Cloud Service Unavailable</title></head><body>"
            "<h2>Free Claude Code Cloud — Service Initialization Error</h2>"
            "<p>The application encountered an error during initialization. Please check cloud server logs for details.</p>"
            "</body></html>",
            status_code=500,
        )
