"""Vercel diagnostic and entry point for Free Claude Code Cloud."""

import os
import sys
import json
import traceback
from pathlib import Path
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        diag = []
        diag.append(f"<b>Python Version:</b> {sys.version}")
        diag.append(f"<b>CWD:</b> {os.getcwd()}")
        diag.append(f"<b>sys.path:</b> {sys.path}")

        try:
            cwd_files = os.listdir(".")
            diag.append(f"<b>Files in CWD:</b> {cwd_files}")
        except Exception as e:
            diag.append(f"<b>CWD list error:</b> {e}")

        try:
            import fastapi
            diag.append(f"<b>fastapi:</b> OK (version {fastapi.__version__})")
        except Exception:
            diag.append(f"<b>fastapi import error:</b><pre>{traceback.format_exc()}</pre>")

        try:
            _root = Path(__file__).resolve().parent.parent
            _src = _root / "src"
            for p in (str(_src), str(_root)):
                if p not in sys.path:
                    sys.path.insert(0, p)
            import free_claude_code
            diag.append("<b>free_claude_code:</b> OK")
        except Exception:
            diag.append(f"<b>free_claude_code import error:</b><pre>{traceback.format_exc()}</pre>")

        try:
            os.environ.setdefault("FCC_CLOUD_DEPLOYMENT", "1")
            os.environ.setdefault("FCC_CONFIG_DIR", "/tmp/.fcc")
            from free_claude_code.config.loader import clear_settings_cache, get_settings
            from free_claude_code.runtime.bootstrap import build_asgi_app
            clear_settings_cache()
            s = get_settings()
            app_inst = build_asgi_app(s)
            diag.append(f"<b>build_asgi_app:</b> OK ({type(app_inst)})")
        except Exception:
            diag.append(f"<b>build_asgi_app error:</b><pre>{traceback.format_exc()}</pre>")

        body = "<h1>FCC Cloud Vercel Diagnostic Probe</h1><ul>" + "".join(f"<li>{item}</li>" for item in diag) + "</ul>"
        self.wfile.write(body.encode("utf-8"))

    def do_POST(self):
        self.do_GET()
