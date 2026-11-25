"""Sign-in session in an ``HttpOnly`` cookie.

- The token never travels in a URL and cannot be read by JavaScript.
- ``SameSite=Lax``: the cookie is not sent on POST/PATCH/DELETE from other sites (CSRF),
  but it is still sent when Google redirects back to Argos after sign-in.
- ``Secure`` when the request comes over https (behind a proxy: uvicorn reads
  ``X-Forwarded-Proto`` from the IPs in ``FORWARDED_ALLOW_IPS``).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from authlib.jose import JsonWebToken
from authlib.jose.errors import JoseError
from fastapi import Request, Response

from app.core.config import app_config, secrets

# Only the configured algorithm is accepted (no "none", no algorithm switching).
_jwt = JsonWebToken([app_config.JWT_ALGORITHM])


def create_session_token(user_id: str, given_name: str = "") -> str:
    """Minimal JWT: only the user ID (UUID) and first name. Everything else is read from the DB."""
    expire = datetime.now(UTC) + timedelta(minutes=app_config.JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "given_name": given_name, "exp": int(expire.timestamp())}
    return _jwt.encode({"alg": app_config.JWT_ALGORITHM}, payload, secrets.SECRET_KEY).decode("ascii")


def decode_session_token(token: str) -> dict[str, Any] | None:
    """The payload when the signature & expiry are valid, otherwise None."""
    try:
        claims = _jwt.decode(token, secrets.SECRET_KEY)
        claims.validate()  # exp
    except (JoseError, ValueError):
        return None
    return dict(claims)


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
