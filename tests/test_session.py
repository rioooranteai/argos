"""Session via an HttpOnly cookie (DESIGN_GROUP_D.md D1, D7)."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.api.routers import auth
from app.core.config import app_config, secrets
from app.core.database import Database
from app.core.dependencies import get_current_user
from app.core.errors import register_exception_handlers
from app.core.migrations import run_migrations
from app.core.session import create_session_token
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository

COOKIE = app_config.SESSION_COOKIE_NAME
GOOGLE_USER = {
    "sub": "google-777", "email": "Staff@corp.com", "email_verified": True, "hd": "corp.com",
    "name": "Staff Satu", "given_name": "Staff", "picture": "https://example.test/p.png",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(secrets, "ALLOWED_GOOGLE_DOMAIN", "corp.com")
    database = Database(db_path=tmp_path / "t.db")
    with database.get_connection() as conn:
        run_migrations(conn)
    repo = SQLiteUserRepository(database)

    google = {"user": dict(GOOGLE_USER)}

    async def fake_token(request):
        return {"userinfo": google["user"]}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", fake_token)

    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(SessionMiddleware, secret_key="s")
    app.state.user_repo = repo
    app.include_router(auth.router)

    @app.get("/me")
    def me(user=Depends(get_current_user)):
        return {"id": user.id, "email": user.email, "given_name": user.given_name}

    def client(base_url="http://testserver"):
        return TestClient(app, base_url=base_url, follow_redirects=False)

    return client, repo, database, google


def _set_cookie_header(response) -> str:
    return response.headers.get("set-cookie", "")


def test_callback_sets_httponly_cookie_without_token_in_url(env):
    client, repo, _, _ = env
    c = client()
    r = c.get("/api/v1/auth/google/callback")
    assert r.status_code == 303 and r.headers["location"] == "/"
    header = _set_cookie_header(r)
    assert header.startswith(f"{COOKIE}=")
    assert "HttpOnly" in header and "samesite=lax" in header.lower() and "Path=/" in header
    assert f"Max-Age={app_config.JWT_EXPIRE_MINUTES * 60}" in header
    assert "Secure" not in header  # http lokal
    assert "token" not in r.headers["location"]

    me = c.get("/me")  # TestClient sends cookies like a browser
    assert me.status_code == 200
    user = repo.get(me.json()["id"])
    assert user.email == "staff@corp.com" and me.json()["given_name"] == "Staff"


def test_cookie_is_secure_over_https(env):
    client, _, _, _ = env
    r = client("https://testserver").get("/api/v1/auth/google/callback")
    assert "Secure" in _set_cookie_header(r)


def test_rejected_login_sets_no_cookie(env):
    client, _, _, google = env
    google["user"] = {**GOOGLE_USER, "hd": "other.com"}
    r = client().get("/api/v1/auth/google/callback")
    assert r.headers["location"] == "/login?error=DOMAIN_NOT_ALLOWED"
    assert COOKIE not in _set_cookie_header(r)


def test_inactive_user_cannot_log_in_or_use_old_cookie(env):
    client, repo, _, _ = env
    c = client()
    c.get("/api/v1/auth/google/callback")
    user_id = c.get("/me").json()["id"]
    repo.set_active(user_id, False)
    assert c.get("/me").status_code == 403
    r = c.get("/api/v1/auth/google/callback")
    assert r.headers["location"] == "/login?error=USER_INACTIVE"


def test_bearer_header_is_rejected(env):
    # Only the cookie is accepted; a valid token in a Bearer header is still 401.
    client, repo, _, _ = env
    user = repo.upsert_on_login("google-1", "a@corp.com", "A", None)
    r = client().get("/me", headers={"Authorization": f"Bearer {create_session_token(user.id)}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("value", ["", "bukan-jwt", "a.b.c"])
def test_invalid_cookie_is_401(env, value):
    client, _, _, _ = env
    c = client()
    c.cookies.set(COOKIE, value)
    assert c.get("/me").status_code == 401


def test_expired_cookie_is_401(env):
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    client, repo, _, _ = env
    user = repo.upsert_on_login("google-1", "a@corp.com", "A", None)
    expired = jwt.encode(
        {"sub": user.id, "exp": datetime.now(UTC) - timedelta(minutes=1)},
        "test-secret", algorithm=app_config.JWT_ALGORITHM,
    )
    c = client()
    c.cookies.set(COOKIE, expired)
    assert c.get("/me").status_code == 401


def test_logout_clears_cookie(env):
    client, _, _, _ = env
    c = client()
    c.get("/api/v1/auth/google/callback")
    assert c.get("/me").status_code == 200
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 204
    header = _set_cookie_header(r)
    assert header.startswith(f"{COOKIE}=") and ("Max-Age=0" in header or "expires=" in header.lower())
    assert c.get("/me").status_code == 401


def test_token_carries_only_id_name_and_expiry(env):
    from jose import jwt

    client, _, _, _ = env
    c = client()
    c.get("/api/v1/auth/google/callback")
    payload = jwt.get_unverified_claims(c.cookies.get(COOKIE))
    assert set(payload) == {"sub", "given_name", "exp"}
