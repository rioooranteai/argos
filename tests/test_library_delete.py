"""Stage 2: delete/archive documents, delete versions, automatic archive cleanup."""
from __future__ import annotations

import pytest

from app.core.config import AppConfig
from app.core.database import Database
from app.core.errors import ConflictError, NotFoundError, PermissionDenied
from app.core.migrations import run_migrations
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
from app.services.library.service import LibraryService, queued_file_path
from app.services.notebook.service import NotebookService
from app.services.user.model import CurrentUser
from tests.library_helpers import make_pdf, upload

ALICE = CurrentUser(id="u1", email="a@corp.com", name="Alice", given_name="", picture="", is_admin=False)
BOB = CurrentUser(id="u2", email="b@corp.com", name="Bob", given_name="", picture="", is_admin=False)
ADMIN = CurrentUser(id="u3", email="boss@corp.com", name="Boss", given_name="", picture="", is_admin=True)


class FakeVectors:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_version(self, version_id):
        self.deleted.append(version_id)


@pytest.fixture
def env(tmp_path):
    db = Database(db_path=tmp_path / "t.db")
    with db.get_connection() as conn:
        run_migrations(conn)
    users = SQLiteUserRepository(db)
    for u in (ALICE, BOB, ADMIN):
        users.upsert_on_login(u.id, u.email, u.name, None, new_user_id=u.id)
    repo = SQLiteLibraryRepository(db)
    vectors = FakeVectors()
    jobs = SQLiteJobRepository(db)
    queue = tmp_path / "queue"
    library = LibraryService(repo, queue, AppConfig(), vector_store=vectors, jobs=jobs, users=users)
    notebooks = NotebookService(SQLiteNotebookRepository(db), repo, library, jobs, AppConfig())
    return library, notebooks, repo, vectors, db, queue


def publish(db, version_id):
    with db.get_connection() as conn:
        doc = conn.execute("SELECT document_id FROM document_versions WHERE id=?", (version_id,)).fetchone()[0]
        conn.execute(
            "INSERT INTO features (document_id, version_id, section_hash, product_name) VALUES (?, ?, 's', 'X')",
            (doc, version_id),
        )
    SQLiteFeatureRepository(db).publish_version(doc, version_id, [], [])


async def new_doc(library, user, marker=0):
    [r] = await library.upload_documents(user, [upload(make_pdf(1, marker=marker), "doc.pdf")])
    return r


def count(db, table):
    with db.get_connection() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ── Delete documents ────────────────────────────────────────────────────


async def test_unused_document_is_purged(env):
    library, _, repo, vectors, db, queue = env
    r = await new_doc(library, ALICE)
    assert library.delete_document(ALICE, r.document_id) == "deleted"
    assert repo.get_document(r.document_id) is None
    assert count(db, "document_versions") == 0
    assert vectors.deleted == [r.version_id]
    assert not queued_file_path(queue, r.version_id, ".pdf").exists()


async def test_owner_notebooks_detached_then_purged(env):
    library, notebooks, repo, _, db, _ = env
    r = await new_doc(library, ALICE)
    publish(db, r.version_id)
    nb = notebooks.create(ALICE, "NB Alice")
    notebooks.add_from_library(ALICE, nb.id, [r.document_id])
    assert library.delete_document(ALICE, r.document_id) == "deleted"
    assert notebooks.sources(ALICE, nb.id) == []
    assert count(db, "features") == 0


async def test_document_used_by_others_is_archived(env):
    library, notebooks, repo, vectors, db, _ = env
    r = await new_doc(library, ALICE)
    publish(db, r.version_id)
    nb_bob = notebooks.create(BOB, "NB Bob")
    notebooks.add_from_library(BOB, nb_bob.id, [r.document_id])

    assert library.delete_document(ALICE, r.document_id) == "archived"
    assert repo.get_document(r.document_id).status == "archived"
    assert library.list_documents(None, None, 50, 0) == []          # gone from the Library
    [src] = notebooks.sources(BOB, nb_bob.id)                        # Bob's notebook still works
    assert src.document_status == "archived"
    assert [s.version_id for s in notebooks.active_sources(BOB, nb_bob.id)] == [r.version_id]
    assert vectors.deleted == []                                     # the data is not deleted yet

    # Bob removes the last source → the archived document is permanently deleted
    notebooks.remove_source(BOB, nb_bob.id, r.document_id)
    assert repo.get_document(r.document_id) is None
    assert vectors.deleted == [r.version_id]


async def test_archived_document_purged_when_notebook_deleted(env):
    library, notebooks, repo, _, db, _ = env
    r = await new_doc(library, ALICE)
    publish(db, r.version_id)
    nb_bob = notebooks.create(BOB, "NB Bob")
    notebooks.add_from_library(BOB, nb_bob.id, [r.document_id])
    library.delete_document(ALICE, r.document_id)
    notebooks.delete(BOB, nb_bob.id)
    assert repo.get_document(r.document_id) is None


async def test_removing_source_of_active_document_never_purges(env):
    library, notebooks, repo, _, db, _ = env
    r = await new_doc(library, ALICE)
    publish(db, r.version_id)
    nb = notebooks.create(BOB, "NB")
    notebooks.add_from_library(BOB, nb.id, [r.document_id])
    notebooks.remove_source(BOB, nb.id, r.document_id)
    assert repo.get_document(r.document_id).status == "active"


async def test_only_owner_can_delete(env):
    library, *_ = env
    r = await new_doc(library, ALICE)
    with pytest.raises(PermissionDenied):
        library.delete_document(BOB, r.document_id)
    with pytest.raises(PermissionDenied):
        library.delete_document(ADMIN, r.document_id)  # the owner is still active


async def test_admin_can_delete_when_owner_inactive(env):
    library, _, repo, _, db, _ = env
    r = await new_doc(library, ALICE)
    with db.get_connection() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = 'u1'")
    assert library.delete_document(ADMIN, r.document_id) == "deleted"


async def test_deleting_processing_document_cancels_job(env):
    library, _, repo, _, db, _ = env
    r = await new_doc(library, ALICE)
    SQLiteJobRepository(db).claim_next(10)  # being processed by the worker
    library.delete_document(ALICE, r.document_id)
    assert repo.get_version(r.version_id) is None
    # The running worker sees the version gone → treated as cancelled
    assert SQLiteJobRepository(db).is_cancel_requested(r.version_id) is True


async def test_archived_document_cannot_be_deleted_again_or_added(env):
    library, notebooks, _, _, db, _ = env
    r = await new_doc(library, ALICE)
    publish(db, r.version_id)
    nb = notebooks.create(BOB, "NB")
    notebooks.add_from_library(BOB, nb.id, [r.document_id])
    library.delete_document(ALICE, r.document_id)
    with pytest.raises(NotFoundError):
        library.delete_document(ALICE, r.document_id)
    other = notebooks.create(ALICE, "Lain")
    with pytest.raises(NotFoundError):
        notebooks.add_from_library(ALICE, other.id, [r.document_id])


# ── Delete versions ─────────────────────────────────────────────────────


async def test_delete_version_rules(env):
    library, notebooks, repo, vectors, db, _ = env
    v1 = await new_doc(library, ALICE, marker=1)
    publish(db, v1.version_id)
    with pytest.raises(ConflictError) as e:
        library.delete_version(ALICE, v1.document_id, v1.version_id)
    assert e.value.code == "ONLY_VERSION"

    v2 = await library.upload_new_version(ALICE, v1.document_id, upload(make_pdf(1, marker=2), "b.pdf"))
    publish(db, v2.version_id)
    v3 = await library.upload_new_version(ALICE, v1.document_id, upload(make_pdf(1, marker=3), "c.pdf"))
    publish(db, v3.version_id)
    assert repo.get_document(v1.document_id).latest_version_id == v3.version_id

    nb = notebooks.create(BOB, "NB")
    notebooks.add_from_library(BOB, nb.id, [v1.document_id])  # pinned to v3
    with pytest.raises(ConflictError) as e:
        library.delete_version(ALICE, v1.document_id, v3.version_id)
    assert e.value.code == "VERSION_IN_USE" and e.value.details == {"notebooks": 1}

    library.delete_version(ALICE, v1.document_id, v2.version_id)
    assert [v.version_no for v in repo.list_versions(v1.document_id)] == [3, 1]  # not renumbered
    assert vectors.deleted == [v2.version_id]
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM features WHERE version_id=?", (v2.version_id,)).fetchone()[0] == 0


async def test_deleting_latest_version_moves_latest_back(env):
    library, _, repo, _, db, _ = env
    v1 = await new_doc(library, ALICE, marker=1)
    publish(db, v1.version_id)
    v2 = await library.upload_new_version(ALICE, v1.document_id, upload(make_pdf(1, marker=2), "b.pdf"))
    publish(db, v2.version_id)
    library.delete_version(ALICE, v1.document_id, v2.version_id)
    assert repo.get_document(v1.document_id).latest_version_id == v1.version_id


async def test_deleted_version_hash_can_be_uploaded_again(env):
    library, _, repo, _, db, _ = env
    v1 = await new_doc(library, ALICE, marker=1)
    publish(db, v1.version_id)
    v2 = await library.upload_new_version(ALICE, v1.document_id, upload(make_pdf(1, marker=2), "b.pdf"))
    library.delete_version(ALICE, v1.document_id, v2.version_id)
    again = await library.upload_new_version(ALICE, v1.document_id, upload(make_pdf(1, marker=2), "b.pdf"))
    assert again.status == "queued" and repo.get_version(again.version_id).version_no == 3


async def test_delete_version_permissions_and_not_found(env):
    library, *_ = env
    v1 = await new_doc(library, ALICE, marker=1)
    v2 = await library.upload_new_version(BOB, v1.document_id, upload(make_pdf(1, marker=2), "b.pdf"))
    with pytest.raises(PermissionDenied):
        library.delete_version(BOB, v1.document_id, v2.version_id)  # Bob uploaded the version but does not own the document
    with pytest.raises(NotFoundError):
        library.delete_version(ALICE, v1.document_id, "tidak-ada")
