"""Upload yang mirip dokumen Library: saran, keputusan user, kedaluwarsa (Tahap 3, A §6.3)."""
from __future__ import annotations

import dataclasses
import io
import random

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

from app.api.routers.library import router as library_router
from app.core.config import AppConfig
from app.core.database import Database
from app.core.dependencies import get_current_user, get_library_service
from app.core.errors import ConflictError, NotFoundError, register_exception_handlers
from app.core.migrations import run_migrations
from app.infrastructure.providers.repositories.sqlite_job_repository import SQLiteJobRepository
from app.infrastructure.providers.repositories.sqlite_library_repository import (
    SQLiteLibraryRepository,
)
from app.infrastructure.providers.repositories.sqlite_notebook_repository import (
    SQLiteNotebookRepository,
)
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository
from app.services.library.service import LibraryService, pending_file_path, queued_file_path
from app.services.notebook.service import NotebookService
from app.services.user.model import CurrentUser
from tests.library_helpers import make_pdf

ALICE = CurrentUser(id="u1", email="a@corp.com", name="Alice", given_name="", picture="", is_admin=False)
BOB = CurrentUser(id="u2", email="b@corp.com", name="Bob", given_name="", picture="", is_admin=False)

WORDS = (
    "harga mobil garansi mesin bensin diesel transmisi otomatis manual cicilan bunga tenor "
    "dealer servis berkala suku cadang warna interior kursi kabin bagasi roda velg lampu"
).split()


def pricelist(seed: int, price_shift: int = 0) -> bytes:
    rnd = random.Random(seed)
    lines = [
        " ".join(rnd.choice(WORDS) for _ in range(9)) + f" Rp {rnd.randint(100, 999) + price_shift}.000"
        for _ in range(60)
    ]
    return "\n".join(lines).encode()


def md(data: bytes, name: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


@pytest.fixture
def env(tmp_path):
    db = Database(db_path=tmp_path / "t.db")
    with db.get_connection() as conn:
        run_migrations(conn)
    users = SQLiteUserRepository(db)
    for u in (ALICE, BOB):
        users.upsert_on_login(u.id, u.email, u.name, None)
    repo = SQLiteLibraryRepository(db)
    queue = tmp_path / "queue"
    cfg = dataclasses.replace(AppConfig(), NOTEBOOK_MAX_SOURCES=3)
    library = LibraryService(repo, queue, cfg)
    notebooks = NotebookService(SQLiteNotebookRepository(db), repo, library, SQLiteJobRepository(db), cfg)
    return library, notebooks, repo, queue, db


async def _original(library):
    [r] = await library.upload_documents(ALICE, [md(pricelist(1), "Pricelist Toyota.md")])
    assert r.status == "queued"
    return r


async def test_similar_upload_is_held_pending(env):
    library, _, repo, queue, _ = env
    original = await _original(library)

    [r] = await library.upload_documents(ALICE, [md(pricelist(1, price_shift=7), "toyota_des.md")])

    assert r.status == "similar"
    assert r.similar_document_id == original.document_id
    assert r.similar_document_name == "Pricelist Toyota"
    assert r.similarity >= 0.9
    assert r.document_id is None and r.version_id is None  # belum didaftarkan
    assert pending_file_path(queue, r.pending_id, ".md").exists()
    assert len(repo.list_documents(None, None, 10, 0)) == 1


async def test_unrelated_upload_is_not_held(env):
    library, *_ = env
    await _original(library)
    [r] = await library.upload_documents(ALICE, [md(pricelist(2), "honda.md")])
    assert r.status == "queued"


async def test_resolve_as_new_version(env):
    library, _, repo, queue, _ = env
    original = await _original(library)
    [p] = await library.upload_documents(ALICE, [md(pricelist(1, 7), "toyota_des.md")])

    r = await library.resolve_pending(ALICE, p.pending_id, "new_version")

    assert r.status == "queued" and r.document_id == original.document_id
    v = repo.get_version(r.version_id)
    assert v.version_no == 2 and v.original_filename == "toyota_des.md"
    assert queued_file_path(queue, v.id, ".md").exists()
    assert not pending_file_path(queue, p.pending_id, ".md").exists()
    assert repo.get_pending(p.pending_id) is None


async def test_resolve_as_separate_document(env):
    library, _, repo, queue, _ = env
    original = await _original(library)
    [p] = await library.upload_documents(ALICE, [md(pricelist(1, 7), "toyota_des.md")])

    r = await library.resolve_pending(ALICE, p.pending_id, "separate")

    assert r.status == "queued" and r.document_id != original.document_id
    assert repo.get_document(r.document_id).display_name == "toyota_des"
    assert repo.get_version(r.version_id).version_no == 1


async def test_new_versions_keep_fingerprint_for_later_comparison(env):
    library, _, repo, _, _ = env
    original = await _original(library)
    [p] = await library.upload_documents(ALICE, [md(pricelist(1, 7), "v2.md")])
    await library.resolve_pending(ALICE, p.pending_id, "separate")
    # Kedua dokumen kini pembanding; upload ketiga cocok dengan salah satunya.
    assert len(repo.list_fingerprints()) == 2
    [r] = await library.upload_documents(ALICE, [md(pricelist(1, 9), "v3.md")])
    assert r.status == "similar" and r.similar_document_id is not None
    assert original.document_id  # dokumen asli tetap ada


async def test_resolve_only_by_uploader_and_only_once(env):
    library, *_ = env
    await _original(library)
    [p] = await library.upload_documents(ALICE, [md(pricelist(1, 7), "x.md")])

    with pytest.raises(NotFoundError):
        await library.resolve_pending(BOB, p.pending_id, "separate")
    await library.resolve_pending(ALICE, p.pending_id, "separate")
    with pytest.raises(NotFoundError):
        await library.resolve_pending(ALICE, p.pending_id, "separate")


async def test_candidate_deleted_before_decision(env):
    library, _, repo, _, _ = env
    original = await _original(library)
    [p] = await library.upload_documents(ALICE, [md(pricelist(1, 7), "x.md")])
    library.delete_document(ALICE, original.document_id)

    with pytest.raises(ConflictError) as exc:
        await library.resolve_pending(ALICE, p.pending_id, "new_version")
    assert exc.value.code == "SIMILAR_DOCUMENT_GONE"
    # Pending tetap ada sehingga user masih bisa memilih "dokumen terpisah".
    r = await library.resolve_pending(ALICE, p.pending_id, "separate")
    assert r.status == "queued"


async def test_expired_pending_is_deleted(env):
    library, _, repo, queue, db = env
    await _original(library)
    [p] = await library.upload_documents(ALICE, [md(pricelist(1, 7), "x.md")])
    with db.get_connection() as conn:
        conn.execute("UPDATE pending_uploads SET created_at = datetime('now', '-61 minutes')")

    assert library.purge_expired_pending() == 1
    assert repo.get_pending(p.pending_id) is None
    assert not pending_file_path(queue, p.pending_id, ".md").exists()
    with pytest.raises(NotFoundError):
        await library.resolve_pending(ALICE, p.pending_id, "separate")


async def test_explicit_version_upload_skips_similarity_check(env):
    library, _, repo, _, _ = env
    original = await _original(library)
    r = await library.upload_new_version(ALICE, original.document_id, md(pricelist(1, 7), "v2.md"))
    assert r.status == "queued" and repo.get_version(r.version_id).version_no == 2


async def test_scanned_pdf_gets_no_suggestion(env):
    library, *_ = env
    [a] = await library.upload_documents(ALICE, [md(make_pdf(1, marker=1), "scan1.pdf")])
    [b] = await library.upload_documents(ALICE, [md(make_pdf(1, marker=2), "scan2.pdf")])
    assert (a.status, b.status) == ("queued", "queued")


# ── Notebook ────────────────────────────────────────────────────────────


async def test_notebook_resolve_new_version_keeps_existing_pin(env):
    library, notebooks, _, _, _ = env
    nb = notebooks.create(ALICE, "Riset")
    [orig], _ = await notebooks.upload(ALICE, nb.id, [md(pricelist(1), "toyota.md")])
    [p], sources = await notebooks.upload(ALICE, nb.id, [md(pricelist(1, 7), "toyota2.md")])
    assert p.status == "similar" and len(sources) == 1  # pending tidak dipasang

    result, sources = await notebooks.resolve_pending(ALICE, nb.id, p.pending_id, "new_version")

    assert result.document_id == orig.document_id
    [src] = sources
    assert src.version_id == orig.version_id  # pin lama dipertahankan


async def test_notebook_resolve_separate_attaches_new_document(env):
    library, notebooks, _, _, _ = env
    nb = notebooks.create(ALICE, "Riset")
    await notebooks.upload(ALICE, nb.id, [md(pricelist(1), "toyota.md")])
    [p], _ = await notebooks.upload(ALICE, nb.id, [md(pricelist(1, 7), "toyota2.md")])

    result, sources = await notebooks.resolve_pending(ALICE, nb.id, p.pending_id, "separate")
    assert {s.document_id for s in sources} >= {result.document_id}
    assert len(sources) == 2


async def test_notebook_resolve_new_version_attaches_when_not_in_notebook(env):
    library, notebooks, _, _, _ = env
    original = await _original(library)  # ada di Library, belum di notebook
    nb = notebooks.create(ALICE, "Riset")
    [p], _ = await notebooks.upload(ALICE, nb.id, [md(pricelist(1, 7), "toyota2.md")])

    result, [src] = await notebooks.resolve_pending(ALICE, nb.id, p.pending_id, "new_version")
    assert src.document_id == original.document_id and src.version_id == result.version_id


# ── API ─────────────────────────────────────────────────────────────────


def test_api_upload_similar_then_resolve(env):
    library, *_ = env
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(library_router)
    app.dependency_overrides[get_library_service] = lambda: library
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)

    def post(data, name):
        return c.post("/api/v1/library/documents", files=[("files", (name, data, "text/markdown"))])

    assert post(pricelist(1), "a.md").json()["results"][0]["status"] == "queued"
    [res] = post(pricelist(1, 7), "b.md").json()["results"]
    assert res["status"] == "similar" and res["pending_id"]

    bad = c.post(f"/api/v1/library/pending/{res['pending_id']}/resolve", json={"action": "merge"})
    assert bad.status_code == 422

    ok = c.post(f"/api/v1/library/pending/{res['pending_id']}/resolve", json={"action": "new_version"})
    assert ok.status_code == 202 and ok.json()["status"] == "queued"

    gone = c.post(f"/api/v1/library/pending/{res['pending_id']}/resolve", json={"action": "separate"})
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "PENDING_UPLOAD_NOT_FOUND"
