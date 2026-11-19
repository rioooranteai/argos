"""Antrean & worker: klaim eksklusif, lease, retry, gagal permanen, batal, shutdown."""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from app.core.config import AppConfig
from app.core.database import Database
from app.core.migrations import run_migrations
from app.engines.document_engine.jobs import JobCancelled, PermanentJobError, classify
from app.engines.document_engine.worker import DocumentWorker
from app.infrastructure.providers.repositories.sqlite_job_repository import SQLiteJobRepository
from app.infrastructure.providers.repositories.sqlite_library_repository import (
    SQLiteLibraryRepository,
)
from app.services.ingestion.exceptions import DocumentLoadError
from app.services.ingestion.providers.loaders.docling_process import ParserTimeout
from app.services.library.model import NewVersion


@pytest.fixture
def env(tmp_path):
    db = Database(db_path=tmp_path / "t.db")
    with db.get_connection() as conn:
        run_migrations(conn)
        conn.execute("INSERT INTO users (id, email) VALUES ('u1', 'u1@corp.com')")
    return db, SQLiteJobRepository(db), SQLiteLibraryRepository(db), tmp_path


def _add_version(library, n: int = 1) -> str:
    v = library.create_document_with_version(
        f"d{n}", f"Doc {n}", "u1",
        NewVersion(id=f"v{n}", content_hash=f"h{n}", original_filename="a.pdf", file_ext=".pdf",
                   size_bytes=1, page_count=1, uploaded_by="u1", pipeline_version="p1"),
    )
    return v.id


def _cfg(**kw) -> AppConfig:
    return dataclasses.replace(AppConfig(), **kw)


def _worker(jobs, tmp_path, process, cleaned=None, **cfg):
    async def cleanup(version_id):
        if cleaned is not None:
            cleaned.append(version_id)

    def source(v):
        return tmp_path / f"{v.id}.pdf"

    return DocumentWorker(jobs, process, cleanup, source, _cfg(**cfg))


def _stage(db, vid):
    with db.get_connection() as conn:
        return dict(conn.execute("SELECT * FROM document_versions WHERE id = ?", (vid,)).fetchone())


# ── Repository ─────────────────────────────────────────────────────────


def test_claim_is_exclusive(env):
    _, jobs, library, _ = env
    _add_version(library)
    first = jobs.claim_next(10)
    assert first is not None and first.stage == "parsing" and first.attempts == 1
    assert jobs.claim_next(10) is None  # sudah diklaim, lease masih berlaku


def test_expired_lease_is_reclaimed(env):
    db, jobs, library, _ = env
    vid = _add_version(library)
    jobs.claim_next(10)
    with db.get_connection() as conn:
        conn.execute("UPDATE document_versions SET locked_until = datetime('now', '-1 minutes')")
    again = jobs.claim_next(10)
    assert again.id == vid and again.attempts == 2


def test_retry_waits_for_next_retry_at(env):
    db, jobs, library, _ = env
    vid = _add_version(library)
    jobs.claim_next(10)
    jobs.schedule_retry(vid, 5, "sementara")
    assert jobs.claim_next(10) is None
    with db.get_connection() as conn:
        conn.execute("UPDATE document_versions SET next_retry_at = datetime('now', '-1 seconds')")
    assert jobs.claim_next(10).id == vid


def test_recover_orphans(env):
    db, jobs, library, _ = env
    vid = _add_version(library)
    jobs.claim_next(10)
    assert jobs.recover_orphans() == 1
    row = _stage(db, vid)
    assert row["stage"] == "queued" and row["attempts"] == 0


def test_cancel_queued_immediately(env):
    db, jobs, library, _ = env
    vid = _add_version(library)
    jobs.request_cancel(vid)
    assert _stage(db, vid)["stage"] == "cancelled"
    assert jobs.claim_next(10) is None


# ── Klasifikasi ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc, retryable",
    [
        (TimeoutError(), True),
        (ParserTimeout("x"), True),
        (DocumentLoadError("a.pdf", "rusak"), False),
        (PermanentJobError("x"), False),
        (RuntimeError("??"), True),
    ],
)
def test_classify(exc, retryable):
    assert classify(exc)[0] is retryable


def test_classify_follows_cause_chain():
    try:
        try:
            raise TimeoutError()
        except TimeoutError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert classify(outer)[0] is True


def _openai_error(cls, status):
    import httpx
    import openai  # noqa: F401

    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/x"))
    return cls("err", response=response, body=None)


def test_classify_openai_client_errors_permanent():
    import openai

    assert classify(_openai_error(openai.AuthenticationError, 401))[0] is False
    assert classify(_openai_error(openai.BadRequestError, 400))[0] is False
    assert classify(_openai_error(openai.RateLimitError, 429))[0] is True
    assert classify(_openai_error(openai.InternalServerError, 500))[0] is True


def test_classify_message_hides_details():
    retry, msg = classify(RuntimeError("password=secret at /srv/x.py"))
    assert "secret" not in msg


# ── Worker ─────────────────────────────────────────────────────────────


async def test_success_removes_source_file(env):
    db, jobs, library, tmp = env
    vid = _add_version(library)
    (tmp / f"{vid}.pdf").write_bytes(b"x")

    async def process(version, ctx):
        await ctx.stage("extracting", total=2)
        await ctx.progress(2)
        with db.get_connection() as conn:  # yang biasanya dilakukan publish_version
            conn.execute("UPDATE document_versions SET stage='ready' WHERE id=?", (version.id,))

    assert await _worker(jobs, tmp, process).run_once()
    assert _stage(db, vid)["stage"] == "ready"
    assert not (tmp / f"{vid}.pdf").exists()


async def test_transient_error_schedules_retry_then_fails(env):
    db, jobs, library, tmp = env
    vid = _add_version(library)
    (tmp / f"{vid}.pdf").write_bytes(b"x")
    cleaned: list[str] = []

    async def process(version, ctx):
        raise TimeoutError()

    worker = _worker(jobs, tmp, process, cleaned, DOC_MAX_ATTEMPTS=2)
    await worker.run_once()
    row = _stage(db, vid)
    assert row["stage"] == "queued" and row["next_retry_at"] is not None
    assert row["error"] and "dicoba lagi" in row["error"]
    assert (tmp / f"{vid}.pdf").exists()  # file dipertahankan untuk percobaan ulang

    with db.get_connection() as conn:
        conn.execute("UPDATE document_versions SET next_retry_at = datetime('now', '-1 seconds')")
    await worker.run_once()
    row = _stage(db, vid)
    assert row["stage"] == "failed" and row["attempts"] == 2
    assert not (tmp / f"{vid}.pdf").exists()
    assert cleaned == [vid, vid]  # data setengah jadi dibersihkan setiap kali gagal


async def test_permanent_error_fails_immediately(env):
    db, jobs, library, tmp = env
    vid = _add_version(library)

    async def process(version, ctx):
        raise DocumentLoadError("a.pdf", "rusak")

    await _worker(jobs, tmp, process).run_once()
    row = _stage(db, vid)
    assert row["stage"] == "failed" and row["attempts"] == 1
    assert row["error"] == "Dokumen tidak bisa dibaca. Pastikan file tidak rusak."


async def test_cancel_during_processing(env):
    db, jobs, library, tmp = env
    vid = _add_version(library)
    cleaned: list[str] = []

    async def process(version, ctx):
        jobs.request_cancel(version.id)  # mis. user menghapus sumber saat diproses
        await ctx.check_cancelled()

    await _worker(jobs, tmp, process, cleaned).run_once()
    assert _stage(db, vid)["stage"] == "cancelled"
    assert cleaned == [vid]


async def test_total_timeout(env):
    db, jobs, library, tmp = env
    vid = _add_version(library)

    async def process(version, ctx):
        await asyncio.sleep(5)

    await _worker(jobs, tmp, process, DOC_TOTAL_TIMEOUT=0.05).run_once()
    assert _stage(db, vid)["stage"] == "queued"  # timeout = error sementara


async def test_shutdown_releases_job_without_counting_attempt(env):
    db, jobs, library, tmp = env
    vid = _add_version(library)
    started = asyncio.Event()

    async def process(version, ctx):
        started.set()
        await asyncio.sleep(30)

    worker = _worker(jobs, tmp, process, WORKER_SHUTDOWN_GRACE=0.05, DOC_WORKERS=1)
    await worker.start()
    await asyncio.wait_for(started.wait(), 5)
    await worker.stop()
    row = _stage(db, vid)
    assert row["stage"] == "queued" and row["attempts"] == 0 and row["locked_until"] is None


async def test_heartbeat_updates_progress(env):
    db, jobs, library, tmp = env
    vid = _add_version(library)
    seen = {}

    async def process(version, ctx):
        await ctx.stage("vision", total=4)
        await ctx.progress(4)
        seen.update(_stage(db, version.id))
        raise JobCancelled()

    await _worker(jobs, tmp, process).run_once()
    assert (seen["stage"], seen["progress_done"], seen["progress_total"]) == ("vision", 4, 4)
