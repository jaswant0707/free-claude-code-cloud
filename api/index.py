"""Vercel Serverless Function entry point for Free Claude Code Cloud."""

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

try:
    from free_claude_code.config.loader import clear_settings_cache, get_settings
    from free_claude_code.runtime.bootstrap import build_asgi_app

    clear_settings_cache()
    settings = get_settings()
    _runtime_asgi = build_asgi_app(settings)
    app: FastAPI = _runtime_asgi.app
    app.state.runtime = _runtime_asgi.runtime

    @app.middleware("http")
    async def _vercel_path_middleware(request: Request, call_next):
        # Normalize rewritten paths from Vercel headers if needed
        matched = (
            request.headers.get("x-matched-path")
            or request.headers.get("x-forwarded-uri")
            or request.headers.get("x-invoke-path")
        )
        if matched and request.scope.get("path") in ("/api/index.py", "/api/index", "/api"):
            clean_path = matched.split("?", 1)[0]
            request.scope["path"] = clean_path
            request.scope["raw_path"] = clean_path.encode("utf-8")
        elif request.scope.get("path") in ("/api/index.py", "/api/index", "/api"):
            request.scope["path"] = "/"
            request.scope["raw_path"] = b"/"
        return await call_next(request)

except Exception:
    _err = traceback.format_exc()
    print(f"FCC Cloud Cold-Start Error:\n{_err}", file=sys.stderr, flush=True)

    app = FastAPI(title="Free Claude Code Cloud")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def _catch_all(request: Request, path: str = ""):
        return HTMLResponse(
            f"<!doctype html><html><head><title>FCC Cloud Startup Error</title></head><body>"
            f"<h2>Free Claude Code Cloud — Initialization Error</h2>"
            f"<pre style='background:#f4f4f4;padding:15px;border-radius:5px;border:1px solid #ccc;overflow-x:auto;'>{_err}</pre>"
            f"</body></html>",
            status_code=500,
        )
