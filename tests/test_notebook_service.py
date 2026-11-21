"""NotebookService: source limit, version pins, checkboxes, active sources, cancellation."""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from app.core.config import AppConfig
from app.core.database import Database
from app.core.errors import NotFoundError, ValidationError
from app.core.migrations import run_migrations
from app.services.library.service import LibraryService
from app.services.notebook.service import NotebookService
from app.services.user.model import CurrentUser
from app.tools.storage.sqlite.feature import (
    SQLiteFeatureRepository,
)
from app.tools.storage.sqlite.job import SQLiteJobRepository
from app.tools.storage.sqlite.library import (
    SQLiteLibraryRepository,
)
from app.tools.storage.sqlite.notebook import (
    SQLiteNotebookRepository,
)
from app.tools.storage.sqlite.user import SQLiteUserRepository
from tests.library_helpers import make_pdf, upload

ALICE = CurrentUser(id="u1", email="a@corp.com", name="Alice", given_name="", picture="", is_admin=False)
BOB = CurrentUser(id="u2", email="b@corp.com", name="Bob", given_name="", picture="", is_admin=False)


@pytest.fixture
def env(tmp_path):
    db = Database(db_path=tmp_path / "t.db")
    with db.get_connection() as conn:
        run_migrations(conn)
    users = SQLiteUserRepository(db)
    for u in (ALICE, BOB):
        users.upsert_on_login(u.id, u.email, u.name, None, new_user_id=u.id)
    library_repo = SQLiteLibraryRepository(db)
    cfg = dataclasses.replace(AppConfig(), NOTEBOOK_MAX_SOURCES=3)
    library = LibraryService(library_repo, tmp_path / "queue", cfg)
    jobs = SQLiteJobRepository(db)
    svc = NotebookService(SQLiteNotebookRepository(db), library_repo, library, jobs, cfg)
    return svc, library, db


def publish(db, version_id: str):
    """Mark a version ready the way the pipeline does."""
    with db.get_connection() as conn:
        doc = conn.execute("SELECT document_id FROM document_versions WHERE id=?", (version_id,)).fetchone()[0]
    SQLiteFeatureRepository(db).publish_version(doc, version_id, [], [])


async def doc(library, user, marker: int, name: str = "d.pdf"):
    [r] = await library.upload_documents(user, [upload(make_pdf(1, marker=marker), name)])
    return r


async def test_upload_attaches_sources_and_respects_limit(env):
    svc, _, _ = env
    nb = svc.create(ALICE, "Riset MPV")
    files = [upload(make_pdf(1, marker=i), f"{i}.pdf") for i in range(2)]
    results, sources = await svc.upload(ALICE, nb.id, files)
    assert [r.status for r in results] == ["queued", "queued"]
    assert len(sources) == 2 and all(s.enabled for s in sources)
    assert sources[0].stage == "queued"

    # 1 slot left → uploading 2 files is rejected up front
    with pytest.raises(ValidationError):
        await svc.upload(ALICE, nb.id, [upload(make_pdf(1, marker=7), "a.pdf"), upload(make_pdf(1, marker=8), "b.pdf")])


async def test_full_notebook_rejects_more(env):
    svc, library, _ = env
    nb = svc.create(ALICE, "NB")
    ids = [(await doc(library, ALICE, i)).document_id for i in range(4)]
    svc.add_from_library(ALICE, nb.id, ids[:3])
    with pytest.raises(ValidationError) as e:
        svc.add_from_library(ALICE, nb.id, [ids[3]])
    assert e.value.code == "NOTEBOOK_FULL"


async def test_concurrent_adds_cannot_exceed_limit(env):
    svc, library, _ = env
    nb = svc.create(ALICE, "NB")
    ids = [(await doc(library, ALICE, i)).document_id for i in range(6)]

    def add(d):
        try:
            svc.add_from_library(ALICE, nb.id, [d])
        except ValidationError:
            pass

    await asyncio.gather(*(asyncio.to_thread(add, d) for d in ids))
    assert len(svc.sources(ALICE, nb.id)) == 3


async def test_add_same_document_twice_is_noop(env):
    svc, library, _ = env
    nb = svc.create(ALICE, "NB")
    d = await doc(library, ALICE, 1)
    svc.add_from_library(ALICE, nb.id, [d.document_id, d.document_id])
    svc.add_from_library(ALICE, nb.id, [d.document_id])
    assert len(svc.sources(ALICE, nb.id)) == 1


async def test_notebook_is_private(env):
    svc, _, _ = env
    nb = svc.create(ALICE, "Milik Alice")
    with pytest.raises(NotFoundError):
        svc.sources(BOB, nb.id)
    assert svc.list(BOB) == []


async def test_active_sources_only_enabled_and_ready(env):
    svc, library, db = env
    nb = svc.create(ALICE, "NB")
    a = await doc(library, ALICE, 1, "a.pdf")
    b = await doc(library, ALICE, 2, "b.pdf")
    c = await doc(library, ALICE, 3, "c.pdf")
    svc.add_from_library(ALICE, nb.id, [a.document_id, b.document_id, c.document_id])
    publish(db, a.version_id)
    publish(db, b.version_id)  # c is still queued
    svc.update_source(ALICE, nb.id, b.document_id, enabled=False, use_latest_version=False)

    assert [s.version_id for s in svc.active_sources(ALICE, nb.id)] == [a.version_id]


async def test_pinned_version_and_update(env):
    svc, library, db = env
    nb = svc.create(ALICE, "NB")
    v1 = await doc(library, ALICE, 1, "p.pdf")
    publish(db, v1.version_id)
    svc.add_from_library(ALICE, nb.id, [v1.document_id])

    v2 = await library.upload_new_version(BOB, v1.document_id, upload(make_pdf(1, marker=9), "p2.pdf"))
    [s] = svc.sources(ALICE, nb.id)
    assert s.version_id == v1.version_id and not s.update_available  # v2 is not ready yet

    publish(db, v2.version_id)
    [s] = svc.sources(ALICE, nb.id)
    assert s.version_id == v1.version_id and s.update_available  # still pinned, with a badge

    [s] = svc.update_source(ALICE, nb.id, v1.document_id, enabled=None, use_latest_version=True)
    assert s.version_id == v2.version_id and not s.update_available


async def test_remove_processing_source_cancels_own_upload(env):
    svc, library, db = env
    nb = svc.create(ALICE, "NB")
    results, _ = await svc.upload(ALICE, nb.id, [upload(make_pdf(1), "a.pdf")])
    vid = results[0].version_id
    svc.remove_source(ALICE, nb.id, results[0].document_id)
    with db.get_connection() as conn:
        assert conn.execute("SELECT stage FROM document_versions WHERE id=?", (vid,)).fetchone()[0] == "cancelled"


async def test_remove_does_not_cancel_when_used_elsewhere_or_not_uploader(env):
    svc, library, db = env
    nb_a = svc.create(ALICE, "A")
    nb_b = svc.create(BOB, "B")
    results, _ = await svc.upload(ALICE, nb_a.id, [upload(make_pdf(1), "a.pdf")])
    d = results[0].document_id
    svc.add_from_library(BOB, nb_b.id, [d])

    svc.remove_source(ALICE, nb_a.id, d)  # still used by Bob's notebook → not cancelled
    with db.get_connection() as conn:
        assert conn.execute("SELECT stage FROM document_versions").fetchone()[0] == "queued"
    svc.add_from_library(ALICE, nb_a.id, [d])
    svc.remove_source(BOB, nb_b.id, d)    # Bob is not the uploader → not cancelled
    with db.get_connection() as conn:
        assert conn.execute("SELECT stage FROM document_versions").fetchone()[0] == "queued"
    svc.remove_source(ALICE, nb_a.id, d)  # the uploader, used by nobody → cancelled
    with db.get_connection() as conn:
        assert conn.execute("SELECT stage FROM document_versions").fetchone()[0] == "cancelled"


async def test_ready_source_removal_never_cancels(env):
    svc, library, db = env
    nb = svc.create(ALICE, "NB")
    d = await doc(library, ALICE, 1)
    publish(db, d.version_id)
    svc.add_from_library(ALICE, nb.id, [d.document_id])
    svc.remove_source(ALICE, nb.id, d.document_id)
    with db.get_connection() as conn:
        assert conn.execute("SELECT stage FROM document_versions").fetchone()[0] == "ready"
