"""Browser login and session endpoints for the single administrator."""

import hmac

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from serviceBot.services import admin_auth

router = APIRouter(prefix="/api/v1/auth", tags=["admin-auth"])
COOKIE_NAME = "admin_session"
GENERIC_LOGIN_ERROR = {"detail": "Invalid email or password"}


def same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return False
    try:
        expected = f"{request.url.scheme}://{request.url.netloc}"
    except Exception:
        return False
    return origin.rstrip("/") == expected.rstrip("/")


def _set_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=28800,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def _clear_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


async def _json_object(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@router.post("/login")
async def login(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not same_origin(request):
        raise HTTPException(status_code=403, detail="Request origin rejected")
    payload = await _json_object(request)
    email, password = payload.get("email"), payload.get("password")
    if not isinstance(email, str) or not isinstance(password, str) or len(password) > 1024:
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR["detail"])
    client_ip = request.client.host if request.client else ""
    authenticated = await run_in_threadpool(admin_auth.authenticate, email, password, client_ip)
    if not authenticated:
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR["detail"])
    normalized_email, token, csrf = authenticated
    _set_cookie(response, token, request)
    return {"authenticated": True, "email": normalized_email, "csrf_token": csrf}


@router.get("/session")
async def current_session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    token = request.cookies.get(COOKIE_NAME, "")
    try:
        session = await run_in_threadpool(admin_auth.get_session, token)
    except Exception:
        session = None
    if not session:
        _clear_cookie(response, request)
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"authenticated": True, **session}


def require_request_session(request: Request):
    """Synchronous fail-closed lookup shared by portal and auth routes."""
    token = request.cookies.get(COOKIE_NAME, "")
    session = admin_auth.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    return token, session


async def require_admin(request: Request, response: Response):
    """Protect a portal request and validate browser Origin/CSRF on mutations."""
    response.headers["Cache-Control"] = "no-store"
    try:
        token, session = await run_in_threadpool(require_request_session, request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication required") from None
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if not same_origin(request):
            raise HTTPException(status_code=403, detail="Request origin rejected")
        if not hmac.compare_digest(session["csrf_token"], request.headers.get("x-csrf-token", "")):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
    return {"email": session["email"]}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not same_origin(request):
        raise HTTPException(status_code=403, detail="Request origin rejected")
    try:
        token, session = await run_in_threadpool(require_request_session, request)
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication required") from None
    csrf = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(session["csrf_token"], csrf):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    await run_in_threadpool(admin_auth.revoke_session, token)
    _clear_cookie(response, request)


@router.post("/password", status_code=204)
async def change_password(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not same_origin(request):
        raise HTTPException(status_code=403, detail="Request origin rejected")
    try:
        token, session = await run_in_threadpool(require_request_session, request)
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication required") from None
    if not hmac.compare_digest(session["csrf_token"], request.headers.get("x-csrf-token", "")):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    payload = await _json_object(request)
    current = payload.get("current_password")
    new = payload.get("new_password")
    confirm = payload.get("new_password_confirmation")
    if not all(isinstance(value, str) and len(value) <= 1024 for value in (current, new, confirm)):
        raise HTTPException(status_code=400, detail="Password change rejected")
    if new != confirm or len(new) < admin_auth.PASSWORD_MIN_LENGTH:
        raise HTTPException(status_code=400, detail="Password change rejected")
    changed = await run_in_threadpool(admin_auth.change_password, current, new)
    if not changed:
        raise HTTPException(status_code=401, detail="Password change rejected")
    _clear_cookie(response, request)
