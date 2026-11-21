"""Single-Owner Authentication Router for Free Claude Code Cloud."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .owner_auth import (
    authenticate_owner,
    check_login_rate_limit,
    clear_session_cookie,
    create_session_token,
    extract_session_from_request,
    is_authenticated_owner,
    set_session_cookie,
)

router = APIRouter()
LOGIN_HTML_PATH = Path(__file__).resolve().parent / "login_static" / "login.html"


class LoginPayload(BaseModel):
    email: str
    password: str


@router.get("/login", include_in_schema=False)
def login_page(request: Request):
    """Serve the owner login page or redirect to admin if already authenticated."""
    if is_authenticated_owner(request):
        next_path = request.query_params.get("next") or "/admin"
        return RedirectResponse(url=next_path, status_code=303)
    content = LOGIN_HTML_PATH.read_text(encoding="utf-8")
    return HTMLResponse(content)


@router.post("/api/auth/login")
def login(payload: LoginPayload, request: Request, response: Response):
    """Authenticate single owner credentials and set secure session cookie."""
    client_ip = request.client.host if request.client else "unknown"
    if not check_login_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please wait a minute before trying again.",
        )

    if not authenticate_owner(payload.email, payload.password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_session_token(payload.email)
    set_session_cookie(response, token, request)
    return {"status": "ok", "email": payload.email.strip().lower()}


@router.post("/api/auth/logout")
def logout(response: Response):
    """Clear session cookie and invalidate client-side session."""
    clear_session_cookie(response)
    return {"status": "logged_out"}


@router.get("/api/auth/session")
def session_status(request: Request):
    """Return current session authentication status."""
    session = extract_session_from_request(request)
    if session:
        return {"authenticated": True, "email": session.get("email")}
    return {"authenticated": False, "email": None}
