"""LibraryService: idempotensi hash, batas batch, versi baru, hak ganti nama."""
from __future__ import annotations

import dataclasses

import pytest

from app.core.config import AppConfig
from app.core.database import Database
from app.core.errors import ConflictError, PermissionDenied, ValidationError
from app.core.migrations import run_migrations
from app.infrastructure.providers.repositories.sqlite_library_repository import (
    SQLiteLibraryRepository,
)
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository
from app.services.library.service import LibraryService, queued_file_path
from app.services.user.model import CurrentUser
from tests.library_helpers import make_pdf, upload

ALICE = CurrentUser(id="u1", email="alice@corp.com", name="Alice", given_name="", picture="", is_admin=False)
BOB = CurrentUser(id="u2", email="bob@corp.com", name="Bob", given_name="", picture="", is_admin=False)
ADMIN = CurrentUser(id="u3", email="boss@corp.com", name="Boss", given_name="", picture="", is_admin=True)


@pytest.fixture
def env(tmp_path):
    database = Database(db_path=tmp_path / "t.db")
    with database.get_connection() as conn:
        run_migrations(conn)
    users = SQLiteUserRepository(database)
    for u in (ALICE, BOB, ADMIN):
        users.upsert_on_login(u.id, u.email, u.name, None)
    repo = SQLiteLibraryRepository(database)
    queue = tmp_path / "queue"
    svc = LibraryService(repo, queue, AppConfig())
    return svc, repo, queue, database


def _cfg(**overrides) -> AppConfig:
    return dataclasses.replace(AppConfig(), **overrides)


async def test_new_upload_is_queued_with_file_in_queue(env):
    svc, repo, queue, _ = env
    [r] = await svc.upload_documents(ALICE, [upload(make_pdf(2), "Pricelist Toyota.pdf")])
    assert r.status == "queued"
    v = repo.get_version(r.version_id)
    assert v.stage == "queued" and v.page_count == 2 and v.version_no == 1
    assert queued_file_path(queue, v.id, ".pdf").exists()
    doc = repo.get_document(r.document_id)
    assert doc.display_name == "Pricelist Toyota"
    assert doc.owner_id == ALICE.id
    # tidak ada file sementara yang tertinggal
    assert [p.name for p in queue.iterdir()] == [f"{v.id}.pdf"]


async def test_identical_file_is_reused_not_reprocessed(env):
    svc, _, queue, _ = env
    data = make_pdf(1)
    [first] = await svc.upload_documents(ALICE, [upload(data, "a.pdf")])
    [second] = await svc.upload_documents(BOB, [upload(data, "nama-lain.pdf")])
    assert second.status == "existing"
    assert second.version_id == first.version_id
    assert second.document_id == first.document_id
    assert len(list(queue.iterdir())) == 1


async def test_same_file_twice_in_one_batch(env):
    svc, _, _, _ = env
    data = make_pdf(1)
    r1, r2 = await svc.upload_documents(ALICE, [upload(data, "a.pdf"), upload(data, "b.pdf")])
    assert (r1.status, r2.status) == ("queued", "existing")
    assert r1.version_id == r2.version_id


async def test_failed_version_is_requeued_on_reupload(env):
    svc, repo, queue, database = env
    data = make_pdf(1)
    [r] = await svc.upload_documents(ALICE, [upload(data, "a.pdf")])
    with database.get_connection() as conn:
        conn.execute(
            "UPDATE document_versions SET stage='failed', attempts=3, error='x' WHERE id=?",
            (r.version_id,),
        )
    queued_file_path(queue, r.version_id, ".pdf").unlink()  # worker sudah menghapus file

    [again] = await svc.upload_documents(BOB, [upload(data, "a.pdf")])
    assert again.status == "queued" and again.version_id == r.version_id
    v = repo.get_version(r.version_id)
    assert (v.stage, v.attempts, v.error) == ("queued", 0, None)
    assert queued_file_path(queue, r.version_id, ".pdf").exists()


async def test_lost_race_returns_existing(env, monkeypatch):
    """Dua upload identik bersamaan: yang kalah mendapat versi pemenang."""
    svc, repo, _, _ = env
    data = make_pdf(1)
    [winner] = await svc.upload_documents(ALICE, [upload(data, "a.pdf")])
    # Simulasikan: pengecekan hash belum melihat pemenang, INSERT lalu kena UNIQUE.
    original = repo.find_version_by_hash
    calls = {"n": 0}

    def flaky(h):
        calls["n"] += 1
        return None if calls["n"] == 1 else original(h)

    monkeypatch.setattr(repo, "find_version_by_hash", flaky)
    [loser] = await svc.upload_documents(BOB, [upload(data, "a.pdf")])
    assert loser.status == "existing" and loser.version_id == winner.version_id
    # dokumen kedua tidak tercipta (transaksi di-rollback)
    assert len(repo.list_documents(None, None, 50, 0)) == 1


async def test_rejections_reported_per_file(env):
    svc, _, _, _ = env
    results = await svc.upload_documents(
        ALICE,
        [
            upload(b"MZ...", "virus.exe"),
            upload(b"%PDF-1.4 broken", "rusak.pdf"),
            upload(make_pdf(1), "ok.pdf"),
        ],
    )
    assert [r.status for r in results] == ["rejected", "rejected", "queued"]
    assert results[0].error_code == "UNSUPPORTED_FILE_TYPE"
    assert results[1].error_code == "FILE_CORRUPT"


async def test_too_many_files(env):
    svc, _, _, _ = env
    files = [upload(make_pdf(1, marker=i), f"{i}.pdf") for i in range(6)]
    with pytest.raises(ValidationError) as e:
        await svc.upload_documents(ALICE, files)
    assert e.value.code == "TOO_MANY_FILES"


async def test_max_files_limited_by_caller(env):
    svc, _, _, _ = env
    files = [upload(make_pdf(1, marker=i), f"{i}.pdf") for i in range(3)]
    with pytest.raises(ValidationError):
        await svc.upload_documents(ALICE, files, max_files=2)


async def test_page_limit(env, tmp_path):
    _, repo, queue, _ = env
    svc = LibraryService(repo, queue, _cfg(UPLOAD_MAX_PAGES=2))
    [r] = await svc.upload_documents(ALICE, [upload(make_pdf(3), "tebal.pdf")])
    assert r.status == "rejected" and r.error_code == "TOO_MANY_PAGES"


async def test_file_and_batch_size_limits(env):
    _, repo, queue, _ = env
    one_mb = b"a" * (1024 * 1024)
    svc = LibraryService(repo, queue, _cfg(UPLOAD_MAX_FILE_MB=2, UPLOAD_MAX_BATCH_MB=3))
    results = await svc.upload_documents(
        ALICE,
        [
            upload(one_mb * 3, "terlalu-besar.md"),  # > 2 MB per file
            upload(one_mb * 2, "a.md"),              # ok, kuota batch tersisa 1 MB
            upload(b"b" + one_mb, "b.md"),           # > sisa kuota batch
        ],
    )
    assert [r.status for r in results] == ["rejected", "queued", "rejected"]
    assert results[0].error_code == "FILE_TOO_LARGE"
    assert results[2].error_code == "BATCH_TOO_LARGE"


async def test_new_version_increments_number(env):
    svc, repo, _, _ = env
    [r] = await svc.upload_documents(ALICE, [upload(make_pdf(1), "p.pdf")])
    v2 = await svc.upload_new_version(BOB, r.document_id, upload(make_pdf(1, marker=1), "p-feb.pdf"))
    assert v2.status == "queued"
    assert repo.get_version(v2.version_id).version_no == 2
    # file identik dengan v2 → dipakai ulang
    again = await svc.upload_new_version(BOB, r.document_id, upload(make_pdf(1, marker=1), "x.pdf"))
    assert again.status == "existing" and again.version_id == v2.version_id


async def test_new_version_with_file_of_other_document(env):
    svc, _, _, _ = env
    [a] = await svc.upload_documents(ALICE, [upload(make_pdf(1, marker=0), "a.pdf")])
    [b] = await svc.upload_documents(ALICE, [upload(make_pdf(1, marker=5), "b.pdf")])
    with pytest.raises(ConflictError) as e:
        await svc.upload_new_version(ALICE, a.document_id, upload(make_pdf(1, marker=5), "b.pdf"))
    assert e.value.details["document_id"] == b.document_id


async def test_rename_only_owner_or_admin(env):
    svc, _, _, _ = env
    [r] = await svc.upload_documents(ALICE, [upload(make_pdf(1), "p.pdf")])
    with pytest.raises(PermissionDenied):
        svc.rename_document(BOB, r.document_id, "X")
    assert svc.rename_document(ALICE, r.document_id, "  Pricelist   Jan ").document.display_name == "Pricelist Jan"
    assert svc.rename_document(ADMIN, r.document_id, "Y").document.display_name == "Y"


async def test_list_and_search(env):
    svc, _, _, _ = env
    await svc.upload_documents(ALICE, [upload(make_pdf(1, marker=0), "Pricelist Toyota.pdf")])
    await svc.upload_documents(BOB, [upload(make_pdf(1, marker=1), "Brosur Honda.pdf")])
    assert len(svc.list_documents(None, None, 50, 0)) == 2
    [hit] = svc.list_documents("toyota", None, 50, 0)
    assert hit.document.display_name == "Pricelist Toyota"
    assert hit.latest_version.stage == "queued"
    assert hit.owner_name == "Alice"
    [by_bob] = svc.list_documents(None, BOB.id, 50, 0)
    assert by_bob.document.display_name == "Brosur Honda"
    # wildcard LIKE di-escape
    assert svc.list_documents("%", None, 50, 0) == []
