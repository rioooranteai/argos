"""Sesi login lewat cookie ``HttpOnly`` (DESIGN_GROUP_D.md D1).

- Token tidak pernah lewat URL dan tidak bisa dibaca JavaScript.
- ``SameSite=Lax``: cookie tidak ikut pada POST/PATCH/DELETE dari situs lain (CSRF),
  tetapi tetap ikut saat Google mengalihkan kembali ke Argos setelah login.
- ``Secure`` bila request datang lewat https (di belakang proxy: uvicorn membaca
  ``X-Forwarded-Proto`` dari IP di ``FORWARDED_ALLOW_IPS``).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, Response
from jose import JWTError, jwt

from app.core.config import app_config, secrets


def create_session_token(user_id: str, given_name: str = "") -> str:
    """JWT minimal: hanya ID user (UUID) dan nama depan. Data lain dibaca dari DB."""
    expire = datetime.now(UTC) + timedelta(minutes=app_config.JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "given_name": given_name, "exp": expire}
    return jwt.encode(payload, secrets.SECRET_KEY, algorithm=app_config.JWT_ALGORITHM)


def decode_session_token(token: str) -> dict[str, Any] | None:
    """Payload bila tanda tangan & masa berlaku sah, selain itu None."""
    try:
        return jwt.decode(token, secrets.SECRET_KEY, algorithms=[app_config.JWT_ALGORITHM])
    except JWTError:
        return None


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=app_config.SESSION_COOKIE_NAME,
        value=token,
        max_age=app_config.JWT_EXPIRE_MINUTES * 60,
        path="/",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=app_config.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )


def session_token_from(request: Request) -> str | None:
    return request.cookies.get(app_config.SESSION_COOKIE_NAME) or None
