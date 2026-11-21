"""Vercel Serverless Function entry point for Free Claude Code Cloud."""

import os
import sys
import traceback
from pathlib import Path

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

_init_error = None
_real_app = None

try:
    from free_claude_code.config.loader import clear_settings_cache, get_settings
    from free_claude_code.runtime.bootstrap import build_asgi_app

    clear_settings_cache()
    settings = get_settings()
    _real_app = build_asgi_app(settings)
except Exception:
    _init_error = traceback.format_exc()


async def app(scope, receive, send):
    """ASGI entrypoint with diagnostic error capture."""
    if _init_error is not None:
        if scope["type"] == "http":
            body = (
                f"<!doctype html><html><head><title>FCC Cloud Startup Error</title></head><body>"
                f"<h2>Free Claude Code Cloud — Initialization Error</h2>"
                f"<pre style='background:#f4f4f4;padding:15px;border-radius:5px;border:1px solid #ccc;overflow-x:auto;'>{_init_error}</pre>"
                f"</body></html>"
            ).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
        elif scope["type"] == "lifespan":
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.failed", "message": _init_error})
        return

    try:
        await _real_app(scope, receive, send)
    except Exception:
        err_msg = traceback.format_exc()
        if scope["type"] == "http":
            body = (
                f"<!doctype html><html><head><title>FCC Cloud Runtime Error</title></head><body>"
                f"<h2>Free Claude Code Cloud — Runtime Error</h2>"
                f"<pre style='background:#f4f4f4;padding:15px;border-radius:5px;border:1px solid #ccc;overflow-x:auto;'>{err_msg}</pre>"
                f"</body></html>"
            ).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
        else:
            raise
