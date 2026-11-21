"""/health/live and /health/ready (DESIGN_GROUP_C.md §6)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.health import router
from app.core.database import Database
from app.api.dependencies import get_current_user
from app.core.errors import AuthenticationError, register_exception_handlers
from app.services.observability.health import HealthChecker
from app.core.observability.recorder import LLMCallRecorder
from app.core.observability.model import LLMCall
from app.services.user.model import CurrentUser

ADMIN = CurrentUser(id="a", email="admin@corp.com", name="A", given_name="", picture="", is_admin=True)
USER = CurrentUser(id="u", email="u@corp.com", name="U", given_name="", picture="", is_admin=False)


class Worker:
    def __init__(self, running=True, since=1.0, active=0):
        self.is_running, self._since, self.active_jobs = running, since, active

    def seconds_since_tick(self):
        return self._since


class Docling:
    def __init__(self, alive=True):
        self.is_alive = alive


class Vectors:
    def __init__(self, error=None):
        self.error = error

    def heartbeat(self):
        if self.error:
            raise self.error


class BrokenDB:
    def get_connection(self):
        raise RuntimeError("disk /data/argos.db rusak")


@pytest.fixture
def make(tmp_path):
    def _make(user=ADMIN, **overrides):
        parts = {
            "database": Database(db_path=tmp_path / "t.db"),
            "vector_store": Vectors(),
            "worker": Worker(),
            "docling": Docling(),
            "recorder": LLMCallRecorder(),
            "missing_config": lambda: [],
            "worker_poll_seconds": 2.0,
        }
        parts.update(overrides)
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router)
        app.state.health_checker = HealthChecker(**parts)

        def current_user():
            if user is None:
                raise AuthenticationError()
            return user

        app.dependency_overrides[get_current_user] = current_user
        return TestClient(app), parts

    return _make


def test_live_needs_no_login(make):
    client, _ = make(user=None)
    r = client.get("/health/live")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ready_is_admin_only(make):
    assert make(user=None)[0].get("/health/ready").status_code == 401
    r = make(user=USER)[0].get("/health/ready")
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"


def test_ready_all_ok(make):
    client, parts = make()
    with parts["recorder"].track("router", "m"):
        pass
    r = client.get("/health/ready")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert {k: v["status"] for k, v in body["checks"].items()} == {
        "database": "ok", "vector_store": "ok", "worker": "ok",
        "docling": "ok", "config": "ok", "openai": "ok",
    }


def test_openai_unknown_before_any_call_is_not_a_failure(make):
    body = make()[0].get("/health/ready").json()
    assert body["checks"]["openai"]["status"] == "unknown" and body["status"] == "ok"


def test_database_failure_is_503_without_exception_text(make):
    client, _ = make(database=BrokenDB())
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == {"status": "fail"}
    assert "rusak" not in r.text and "/data" not in r.text


def test_vector_store_failure_is_503(make):
    r = make(vector_store=Vectors(RuntimeError("chroma")))[0].get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["vector_store"]["status"] == "fail"


def test_docling_down_is_degraded_not_failed(make):
    r = make(docling=Docling(alive=False))[0].get("/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded" and r.json()["checks"]["docling"]["status"] == "degraded"


@pytest.mark.parametrize("worker, expected", [
    (Worker(running=False), "fail"),
    (Worker(since=60.0), "fail"),          # loop macet
    (Worker(since=None), "fail"),          # has never looped
    (Worker(since=600.0, active=2), "ok"),  # every slot is busy with a job
])
def test_worker_check(make, worker, expected):
    body = make(worker=worker)[0].get("/health/ready").json()
    assert body["checks"]["worker"]["status"] == expected


def test_missing_config_names_only(make):
    body = make(missing_config=lambda: ["OPENAI_API_KEY"])[0].get("/health/ready").json()
    assert body["checks"]["config"] == {"status": "fail", "missing": ["OPENAI_API_KEY"]}


def test_recent_openai_failure_is_degraded_old_one_is_not(make):
    client, parts = make()
    rec = parts["recorder"]
    rec.record(LLMCall(purpose="synthesizer", model="m", latency_ms=1, status="error",
                       error_code="LLM_TIMEOUT"))
    rec.record(LLMCall(purpose="title", model="m", latency_ms=1, status="error", error_code="LLM_ERROR",
                       ts=datetime.now(UTC) - timedelta(hours=1)))
    openai = client.get("/health/ready").json()["checks"]["openai"]
    assert openai["status"] == "degraded"
    assert openai["purposes"]["synthesizer"]["error_code"] == "LLM_TIMEOUT"

    rec.record(LLMCall(purpose="synthesizer", model="m", latency_ms=1, status="ok"))
    assert client.get("/health/ready").json()["checks"]["openai"]["status"] == "ok"
