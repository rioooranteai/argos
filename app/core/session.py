"""Sign-in session in an ``HttpOnly`` cookie (DESIGN_GROUP_D.md D1).

- The token never travels in a URL and cannot be read by JavaScript.
- ``SameSite=Lax``: the cookie is not sent on POST/PATCH/DELETE from other sites (CSRF),
  but it is still sent when Google redirects back to Argos after sign-in.
- ``Secure`` when the request comes over https (behind a proxy: uvicorn reads
  ``X-Forwarded-Proto`` from the IPs in ``FORWARDED_ALLOW_IPS``).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, Response
from jose import JWTError, jwt

from app.core.config import app_config, secrets


def create_session_token(user_id: str, given_name: str = "") -> str:
    """Minimal JWT: only the user ID (UUID) and first name. Everything else is read from the DB."""
    expire = datetime.now(UTC) + timedelta(minutes=app_config.JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "given_name": given_name, "exp": expire}
    return jwt.encode(payload, secrets.SECRET_KEY, algorithm=app_config.JWT_ALGORITHM)


def decode_session_token(token: str) -> dict[str, Any] | None:
    """The payload when the signature & expiry are valid, otherwise None."""
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
