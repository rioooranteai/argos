"""HTTP: /api/v1/notebooks — sumber, chat terbatas sumber aktif, sitasi, isolasi antar user."""
from __future__ import annotations

import asyncio
import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.notebooks import router
from app.core.config import AppConfig
from app.core.database import Database
from app.core.dependencies import (
    get_chat_engine,
    get_conversation_service,
    get_current_user,
    get_notebook_service,
)
from app.core.errors import UpstreamTimeout, register_exception_handlers
from app.core.migrations import run_migrations
from app.engines.chat_engine.engine import ChatEngine
from app.infrastructure.providers.repositories.sqlite_conversation_repository import (
    SQLiteConversationRepository,
)
from app.infrastructure.providers.repositories.sqlite_feature_repository import (
    SQLiteFeatureRepository,
)
from app.infrastructure.providers.repositories.sqlite_job_repository import SQLiteJobRepository
from app.infrastructure.providers.repositories.sqlite_library_repository import (
    SQLiteLibraryRepository,
)
from app.infrastructure.providers.repositories.sqlite_notebook_repository import (
    SQLiteNotebookRepository,
)
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository
from app.services.conversation.service import ConversationService
from app.services.library.service import LibraryService
from app.services.nl2sql.service import NL2SQLResult
from app.services.notebook.service import NotebookService
from app.services.user.model import CurrentUser
from app.services.vector_store.model import SearchHit
from tests.library_helpers import make_pdf

ALICE = CurrentUser(id="u1", email="a@corp.com", name="Alice", given_name="", picture="", is_admin=False)
BOB = CurrentUser(id="u2", email="b@corp.com", name="Bob", given_name="", picture="", is_admin=False)


class FakeChatEngine:
    def __init__(self):
        self.calls = []

    async def chat(self, user_input, history=None, sources=None):
        self.calls.append({"q": user_input, "sources": sources, "history": history})
        return {
            "answer": "Avanza Rp 230 jt [1].",
            "route": "sql",
            "router_reasoning": "harga",
            "citations": [{"label": 1, "version_id": sources[0].version_id, "display_name": sources[0].display_name}],
            "error": None,
        }


@pytest.fixture
def env(tmp_path):
    db = Database(db_path=tmp_path / "t.db")
    with db.get_connection() as conn:
        run_migrations(conn)
    for u in (ALICE, BOB):
        SQLiteUserRepository(db).upsert_on_login(u.id, u.email, u.name, None)
    cfg = AppConfig()
    library_repo = SQLiteLibraryRepository(db)
    library = LibraryService(library_repo, tmp_path / "queue", cfg)
    nb_svc = NotebookService(SQLiteNotebookRepository(db), library_repo, library, SQLiteJobRepository(db), cfg)
    conv_svc = ConversationService(SQLiteConversationRepository(db), title_llm=None)
    engine = FakeChatEngine()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_notebook_service] = lambda: nb_svc
    app.dependency_overrides[get_conversation_service] = lambda: conv_svc
    app.dependency_overrides[get_chat_engine] = lambda: engine
    state = {"user": ALICE}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return TestClient(app), db, engine, state


def _publish(db, version_id):
    with db.get_connection() as conn:
        doc = conn.execute("SELECT document_id FROM document_versions WHERE id=?", (version_id,)).fetchone()[0]
    SQLiteFeatureRepository(db).publish_version(doc, version_id, [], [])


def _setup_notebook(c):
    nb = c.post("/api/v1/notebooks", json={"title": "Riset MPV"}).json()
    up = c.post(
        f"/api/v1/notebooks/{nb['id']}/sources/upload",
        files=[("files", ("Pricelist.pdf", make_pdf(1), "application/pdf"))],
    )
    assert up.status_code == 202
    return nb, up.json()


def test_chat_blocked_until_source_ready_then_scoped(env):
    c, db, engine, _ = env
    nb, up = _setup_notebook(c)
    assert up["sources"][0]["stage"] == "queued" and nb["max_sources"] == 10

    r = c.post(f"/api/v1/notebooks/{nb['id']}/messages", json={"question": "harga avanza?"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "SOURCES_PROCESSING"

    vid = up["results"][0]["version_id"]
    _publish(db, vid)
    r = c.post(f"/api/v1/notebooks/{nb['id']}/messages", json={"question": "harga avanza?"})
    assert r.status_code == 200
    body = r.json()
    assert body["citations"][0]["label"] == 1
    assert [s.version_id for s in engine.calls[0]["sources"]] == [vid]
    assert body["metadata"]["sources_used"] == 1

    conv = c.get(f"/api/v1/notebooks/{nb['id']}/conversations/{body['conversation_id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["citations"][0]["version_id"] == vid
    with db.get_connection() as conn:
        snap = conn.execute("SELECT source_snapshot FROM messages WHERE role='user'").fetchone()[0]
    assert vid in snap


def test_unchecked_sources_excluded(env):
    c, db, engine, _ = env
    nb, up = _setup_notebook(c)
    _publish(db, up["results"][0]["version_id"])
    doc_id = up["results"][0]["document_id"]
    sources = c.patch(f"/api/v1/notebooks/{nb['id']}/sources/{doc_id}", json={"enabled": False}).json()
    assert sources[0]["enabled"] is False
    r = c.post(f"/api/v1/notebooks/{nb['id']}/messages", json={"question": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "NO_ACTIVE_SOURCES"
    assert engine.calls == []


def test_notebooks_and_conversations_are_private(env):
    c, db, _, state = env
    nb, up = _setup_notebook(c)
    _publish(db, up["results"][0]["version_id"])
    conv_id = c.post(f"/api/v1/notebooks/{nb['id']}/messages", json={"question": "x"}).json()["conversation_id"]

    state["user"] = BOB
    assert c.get(f"/api/v1/notebooks/{nb['id']}").status_code == 404
    assert c.get(f"/api/v1/notebooks/{nb['id']}/conversations/{conv_id}").status_code == 404
    assert c.get("/api/v1/notebooks").json() == []

    # Percakapan tidak bisa dipakai lewat notebook lain milik pemiliknya sendiri
    state["user"] = ALICE
    other = c.post("/api/v1/notebooks", json={"title": "Lain"}).json()
    r = c.get(f"/api/v1/notebooks/{other['id']}/conversations/{conv_id}")
    assert r.status_code == 404


def test_add_from_library_and_remove(env):
    c, db, _, _ = env
    nb, up = _setup_notebook(c)
    other = c.post("/api/v1/notebooks", json={"title": "NB 2"}).json()
    doc_id = up["results"][0]["document_id"]
    added = c.post(f"/api/v1/notebooks/{other['id']}/sources", json={"document_ids": [doc_id]}).json()
    assert added[0]["document_id"] == doc_id
    assert c.delete(f"/api/v1/notebooks/{other['id']}/sources/{doc_id}").json() == []
    assert c.delete(f"/api/v1/notebooks/{other['id']}").status_code == 204


# ── ChatEngine: sumber aktif diteruskan ke SQL & vector, timeout total ──────


class _LLM:
    def __init__(self, text, delay=0.0):
        self.text, self.delay = text, delay

    async def ainvoke(self, prompt, system=None):
        await asyncio.sleep(self.delay)
        return self.text

    def invoke(self, prompt, system=None):
        return self.text

    def with_structured_output(self, schema):
        return self


class _NL2SQL:
    def __init__(self):
        self.version_ids = None

    async def process_query(self, q, version_ids):
        self.version_ids = version_ids
        return NL2SQLResult(
            status="ok",
            raw_data=[{"product_name": "Avanza", "price": 230.0, "version_id": "v1", "page_number": 4}],
            row_count=1,
        )


class _Vectors:
    def __init__(self):
        self.version_ids = None

    def search(self, query, version_ids, limit=5):
        self.version_ids = version_ids
        return [SearchHit("c1", "Veloz 7 kursi", 0.1, {"version_id": "v1", "page_number": 2})]


async def test_engine_passes_active_versions_and_returns_citations():
    from datetime import datetime

    from app.services.notebook.model import ActiveSource

    nl2sql, vectors = _NL2SQL(), _Vectors()
    engine = ChatEngine(
        llm=_LLM("Avanza Rp 230 jt [1]."),
        router_llm=_LLM('{"route": "both", "reasoning": "x"}'),
        nl2sql_svc=nl2sql,
        vector_svc=vectors,
    )
    sources = [ActiveSource("v1", "d1", "Pricelist", 1, datetime(2026, 1, 1))]
    out = await engine.chat("harga?", sources=sources)
    assert nl2sql.version_ids == ["v1"] and vectors.version_ids == ["v1"]
    assert [c["label"] for c in out["citations"]] == [1]


async def test_engine_total_timeout():
    engine = ChatEngine(
        llm=_LLM("x", delay=5),
        router_llm=_LLM('{"route": "none", "reasoning": ""}'),
        nl2sql_svc=_NL2SQL(),
        vector_svc=_Vectors(),
        total_timeout=0.1,
    )
    with pytest.raises(UpstreamTimeout):
        await engine.chat("halo", sources=[])


def test_llm_factory_sets_timeouts():
    from app.infrastructure.factories.llm_factory import get_llm

    cfg = AppConfig()
    router_llm = get_llm("router")
    assert router_llm._client.request_timeout == cfg.LLM_TIMEOUT_ROUTER
    assert get_llm("title")._client.max_retries == 0
    assert get_llm("nl2sql")._client.request_timeout == cfg.LLM_TIMEOUT_NL2SQL
    assert dataclasses.is_dataclass(cfg)
