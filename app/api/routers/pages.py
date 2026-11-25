"""Web pages.

- ``/``, ``/home``: only sent to users with a valid session; otherwise → ``/login``.
- ``/js/*``: application code, only for users with a valid session; otherwise → 404.
- ``/login``: public; with a valid session it goes straight to ``/``. Its script is ``/login.js`` (public).
- ``/css/*`` stays public (used by the login page), mounted in ``main.py``.
- ``/favicon.svg`` (and ``/favicon.ico`` for browsers that ask for it anyway): public.

Pages use the session cookie only, since the browser opens them directly.

Both pages carry a Content-Security-Policy: scripts only from this site and the two pinned CDN
libraries (no inline scripts or event-handler attributes), no plugins/frames, and network calls
only to this site. It is the second line of defence if an AI answer ever slipped HTML past
DOMPurify (an answer is LLM output and the LLM reads uploaded documents).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.api.dependencies import user_from_token
from app.core.config import PROJECT_ROOT
from app.core.session import session_token_from

WEB_DIR = PROJECT_ROOT / "web-app"
JS_DIR = (WEB_DIR / "js").resolve()

# Once loaded the page holds user data: keep it out of browser/proxy caches
# so the Back button after sign-out does not show it again.
_NO_STORE = {"Cache-Control": "no-store"}

_CSP = "; ".join((
    "default-src 'self'",
    "script-src 'self' https://cdn.jsdelivr.net",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob: https://*.googleusercontent.com",  # Google profile pictures
    "media-src 'self' blob:",                                      # text-to-speech audio
    "connect-src 'self'",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
))
_PAGE_HEADERS = {
    **_NO_STORE,
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

router = APIRouter(include_in_schema=False)


def _signed_in(request: Request) -> bool:
    return user_from_token(request, session_token_from(request)) is not None


@router.get("/")
@router.get("/home")
def index(request: Request) -> Response:
    if not _signed_in(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "index.html", headers=_PAGE_HEADERS)


@router.get("/login")
def login_page(request: Request) -> Response:
    if _signed_in(request):
        return RedirectResponse("/", status_code=302)
    return FileResponse(WEB_DIR / "login.html", headers=_PAGE_HEADERS)


@router.get("/login.js")
def login_script() -> Response:
    return FileResponse(WEB_DIR / "login.js", media_type="text/javascript", headers=_NO_STORE)


@router.get("/favicon.svg")
@router.get("/favicon.ico")
def favicon() -> Response:
    return FileResponse(
        WEB_DIR / "favicon.svg", media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/js/{file_path:path}")
def app_script(file_path: str, request: Request) -> Response:
    target = _safe_js_path(file_path)
    if target is None or not _signed_in(request):
        return Response(status_code=404)
    return FileResponse(target, headers=_NO_STORE)


def _safe_js_path(file_path: str) -> Path | None:
    """Only files inside web-app/js (prevents ../ from leaving the folder)."""
    try:
        target = (JS_DIR / file_path).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_relative_to(JS_DIR) or not target.is_file():
        return None
    return target
