"""Rate limit per user per kelompok endpoint (DESIGN_GROUP_D.md D9)."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppConfig
from app.core.dependencies import get_current_user
from app.core.errors import RateLimited, register_exception_handlers
from app.core.rate_limit import RateLimiter, limiter, rate_limit
from app.services.user.model import CurrentUser


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_sliding_window_and_retry_after():
    clock = Clock()
    rl = RateLimiter({"chat": 3}, window_seconds=60, clock=clock)
    for _ in range(3):
        assert rl.hit("chat", "u1") is None
    assert rl.hit("chat", "u1") == 60          # penuh: tunggu sampai request pertama keluar jendela
    clock.now += 45
    assert rl.hit("chat", "u1") == 15
    clock.now += 15
    assert rl.hit("chat", "u1") is None        # request pertama sudah keluar jendela


def test_users_and_groups_are_independent():
    rl = RateLimiter({"chat": 1, "voice": 1}, clock=Clock())
    assert rl.hit("chat", "u1") is None
    assert rl.hit("chat", "u2") is None
    assert rl.hit("voice", "u1") is None
    assert rl.hit("chat", "u1") is not None


def test_check_raises_with_retry_after():
    rl = RateLimiter({"voice": 1}, clock=Clock())
    rl.check("voice", "u1")
    with pytest.raises(RateLimited) as exc:
        rl.check("voice", "u1")
    assert exc.value.http_status == 429 and exc.value.retryable
    assert exc.value.details == {"retry_after": 60}
    assert exc.value.headers == {"Retry-After": "60"}


def test_idle_keys_are_cleaned_up(monkeypatch):
    monkeypatch.setattr("app.core.rate_limit._CLEANUP_EVERY", 5)
    clock = Clock()
    rl = RateLimiter({"default": 100}, clock=clock)
    for i in range(4):
        rl.hit("default", f"u{i}")
    clock.now += 120
    rl.hit("default", "baru")                 # hit ke-5 memicu pembersihan
    assert rl.tracked_keys() == 1


def test_configured_limits_match_design():
    cfg = AppConfig()
    assert (cfg.RATE_LIMIT_CHAT, cfg.RATE_LIMIT_VOICE, cfg.RATE_LIMIT_UPLOAD,
            cfg.RATE_LIMIT_LOGIN, cfg.RATE_LIMIT_DEFAULT) == (20, 10, 10, 10, 120)


def test_http_429_with_retry_after_header():
    app = FastAPI()
    register_exception_handlers(app)
    user = CurrentUser(id="u1", email="a@corp.com", name="A", given_name="", picture="", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: user

    @app.post("/chat", dependencies=[Depends(rate_limit("chat"))])
    def chat():
        return {"ok": True}

    client = TestClient(app)
    for _ in range(20):
        assert client.post("/chat").status_code == 200
    r = client.post("/chat")
    assert r.status_code == 429
    assert r.headers["retry-after"].isdigit()
    body = r.json()["error"]
    assert body["code"] == "RATE_LIMITED" and body["retryable"] is True
    assert body["details"]["retry_after"] == int(r.headers["retry-after"])
    assert "Try again in" in body["message"]


def test_routes_carry_the_right_groups():
    """Endpoint mahal memakai grup yang tepat (bukan hanya batas default)."""
    from fastapi.routing import APIRoute

    from app.main import app

    def groups(route):
        found = set()

        def walk(dep):
            for d in dep.dependencies:
                name = getattr(d.call, "__name__", "")
                if name.startswith("rate_limit_"):
                    found.add(name.removeprefix("rate_limit_"))
                walk(d)

        walk(route.dependant)
        return found

    by_path = {(next(iter(r.methods)), r.path): groups(r) for r in app.routes if isinstance(r, APIRoute)}
    assert by_path[("POST", "/api/v1/notebooks/{notebook_id}/messages")] == {"chat"}
    assert by_path[("POST", "/api/v1/notebooks/{notebook_id}/conversations/{conversation_id}/messages/{message_id}/retry")] == {"chat"}
    assert by_path[("POST", "/api/v1/voice/stt")] == {"voice"}
    assert by_path[("POST", "/api/v1/voice/tts")] == {"voice"}
    for path in ("/api/v1/library/documents", "/api/v1/library/documents/{document_id}/versions",
                 "/api/v1/library/pending/{pending_id}/resolve",
                 "/api/v1/notebooks/{notebook_id}/sources/upload",
                 "/api/v1/notebooks/{notebook_id}/sources/pending/{pending_id}/resolve"):
        assert by_path[("POST", path)] == {"upload"}, path


def test_login_is_limited_per_ip(monkeypatch):
    from starlette.middleware.sessions import SessionMiddleware

    from app.api.routers import auth

    async def fake_redirect(request, redirect_uri, **kwargs):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("https://accounts.google.com/o/oauth2")

    monkeypatch.setattr(auth.oauth.google, "authorize_redirect", fake_redirect)
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="s")
    app.include_router(auth.router)
    client = TestClient(app, follow_redirects=False)
    for _ in range(10):
        assert client.get("/api/v1/auth/google/login").headers["location"].startswith("https://accounts")
    r = client.get("/api/v1/auth/google/login")
    assert r.status_code in (302, 307) and r.headers["location"] == "/login?error=RATE_LIMITED"
    assert limiter.hit("login", "ip-lain") is None   # IP lain tidak terpengaruh
