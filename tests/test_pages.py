"""Web pages only for signed-in users (DESIGN_GROUP_D.md D3, D5, D6)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import health, pages
from app.core.config import app_config, secrets
from app.core.database import Database
from app.core.migrations import run_migrations
from app.core.session import create_session_token
from app.tools.storage.sqlite.user import SQLiteUserRepository

COOKIE = app_config.SESSION_COOKIE_NAME


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRET_KEY", "test-secret")
    database = Database(db_path=tmp_path / "t.db")
    with database.get_connection() as conn:
        run_migrations(conn)
    repo = SQLiteUserRepository(database)
    user = repo.upsert_on_login("google-1", "a@corp.com", "A", None)

    app = FastAPI()
    app.state.user_repo = repo
    app.include_router(pages.router)
    app.include_router(health.router)
    client = TestClient(app, follow_redirects=False)
    return client, repo, user


def _login(client, user):
    client.cookies.set(COOKIE, create_session_token(user.id))


@pytest.mark.parametrize("path", ["/", "/home"])
def test_app_page_requires_session(env, path):
    client, _, user = env
    r = client.get(path)
    assert r.status_code == 302 and r.headers["location"] == "/login"
    _login(client, user)
    r = client.get(path)
    assert r.status_code == 200 and "<html" in r.text.lower()
    assert r.headers["cache-control"] == "no-store"


def test_app_script_requires_session(env):
    client, _, user = env
    assert client.get("/js/main.js").status_code == 404
    _login(client, user)
    r = client.get("/js/main.js")
    assert r.status_code == 200 and "function" in r.text


@pytest.mark.parametrize("path", ["/js/../../app/main.py", "/js/..%2F..%2Fapp%2Fmain.py",
                                  "/js/tidak-ada.js", "/js/"])
def test_script_route_cannot_escape_or_guess(env, path):
    client, _, user = env
    _login(client, user)
    assert client.get(path).status_code == 404


def test_login_page_public_and_skips_when_signed_in(env):
    client, _, user = env
    assert client.get("/login").status_code == 200
    _login(client, user)
    r = client.get("/login")
    assert r.status_code == 302 and r.headers["location"] == "/"


def test_invalid_or_inactive_session_goes_to_login(env):
    client, repo, user = env
    client.cookies.set(COOKIE, "rusak")
    assert client.get("/").headers["location"] == "/login"
    _login(client, user)
    repo.set_active(user.id, False)
    assert client.get("/").headers["location"] == "/login"
    assert client.get("/js/main.js").status_code == 404


def test_health_live_is_public(env):
    client, _, _ = env
    assert client.get("/health/live").json() == {"status": "ok"}


def test_docs_are_public_in_the_real_app():
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/docs", "/redoc", "/openapi.json"} <= paths
    # Pages & scripts do not appear in the API docs.
    schema_paths = set(app.openapi()["paths"])
    assert "/" not in schema_paths and "/js/{file_path}" not in schema_paths


@pytest.mark.parametrize("path", ["/favicon.svg", "/favicon.ico"])
def test_favicon_is_public(env, path):
    client, _, _ = env
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
