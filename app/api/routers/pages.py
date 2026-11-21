"""Web pages (DESIGN_GROUP_D.md D3).

- ``/``, ``/home``: only sent to users with a valid session; otherwise → ``/login``.
- ``/js/*``: application code, only for users with a valid session; otherwise → 404.
- ``/login``: public; with a valid session it goes straight to ``/``.
- ``/css/*`` stays public (used by the login page), mounted in ``main.py``.
- ``/favicon.svg`` (and ``/favicon.ico`` for browsers that ask for it anyway): public.

Pages use the session cookie only, since the browser opens them directly.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.core.config import PROJECT_ROOT
from app.api.dependencies import user_from_token
from app.core.session import session_token_from

WEB_DIR = PROJECT_ROOT / "web-app"
JS_DIR = (WEB_DIR / "js").resolve()

# Once loaded the page holds user data: keep it out of browser/proxy caches
# so the Back button after sign-out does not show it again.
_NO_STORE = {"Cache-Control": "no-store"}

router = APIRouter(include_in_schema=False)


def _signed_in(request: Request) -> bool:
    return user_from_token(request, session_token_from(request)) is not None


@router.get("/")
@router.get("/home")
def index(request: Request) -> Response:
    if not _signed_in(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "index.html", headers=_NO_STORE)


@router.get("/login")
def login_page(request: Request) -> Response:
    if _signed_in(request):
        return RedirectResponse("/", status_code=302)
    return FileResponse(WEB_DIR / "login.html", headers=_NO_STORE)


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
