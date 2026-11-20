"""Vercel Serverless Function entry point for Free Claude Code Cloud."""

import os
import sys
from pathlib import Path

# Ensure project src directory is available in the module search path
_ROOT_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _ROOT_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Enforce cloud deployment flags and redirect writable state to /tmp
os.environ.setdefault("FCC_CLOUD_DEPLOYMENT", "1")
if "FCC_CONFIG_DIR" not in os.environ:
    os.environ["FCC_CONFIG_DIR"] = "/tmp/.fcc"

try:
    Path(os.environ["FCC_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# In cloud deployments, default proxy auth to enabled if not explicitly specified
if "PROXY_AUTH_ENABLED" not in os.environ:
    os.environ["PROXY_AUTH_ENABLED"] = "true"

from free_claude_code.config.loader import clear_settings_cache, get_settings
from free_claude_code.runtime.bootstrap import build_asgi_app

clear_settings_cache()
settings = get_settings()
app = build_asgi_app(settings)
