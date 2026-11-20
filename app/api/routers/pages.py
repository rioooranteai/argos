"""Halaman web (DESIGN_GROUP_D.md D3).

- ``/``, ``/home``: hanya dikirim ke user dengan sesi sah; selain itu → ``/login``.
- ``/js/*``: kode aplikasi, hanya untuk user dengan sesi sah; selain itu → 404.
- ``/login``: publik; bila sesi masih sah langsung → ``/``.
- ``/css/*`` tetap publik (dipakai halaman login), di-mount di ``main.py``.

Halaman memakai cookie sesi saja (bukan header Bearer), karena dibuka langsung oleh browser.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.core.config import PROJECT_ROOT
from app.core.dependencies import user_from_token
from app.core.session import session_token_from

WEB_DIR = PROJECT_ROOT / "web-app"
JS_DIR = (WEB_DIR / "js").resolve()

# Halaman berisi data user setelah dimuat: jangan disimpan cache browser/proxy,
# agar tombol Back setelah logout tidak menampilkannya lagi.
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


@router.get("/js/{file_path:path}")
def app_script(file_path: str, request: Request) -> Response:
    target = _safe_js_path(file_path)
    if target is None or not _signed_in(request):
        return Response(status_code=404)
    return FileResponse(target, headers=_NO_STORE)


def _safe_js_path(file_path: str) -> Path | None:
    """Hanya file di dalam web-app/js (mencegah ../ keluar folder)."""
    try:
        target = (JS_DIR / file_path).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_relative_to(JS_DIR) or not target.is_file():
        return None
    return target
