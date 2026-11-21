"""End-to-end pipeline (no real OpenAI/Docling): atomic publish, failure midway,
cancellation, cache on retry, latest version."""
from __future__ import annotations

import asyncio

import pytest

from app.core.concurrency import AILimits
from app.core.config import AppConfig
from app.core.database import Database
from app.core.migrations import run_migrations
from app.engines.document_engine.pipeline import DocumentPipeline
from app.engines.document_engine.worker import DocumentWorker
from app.tools.storage.sqlite.cache import SQLiteCacheRepository
from app.tools.storage.sqlite.feature import (
    SQLiteFeatureRepository,
)
from app.tools.storage.sqlite.job import SQLiteJobRepository
from app.tools.storage.sqlite.library import (
    SQLiteLibraryRepository,
)
from app.services.extraction.service import ExtractionService
from app.tools.document_parser.base import DocumentElement, ElementType
from app.services.ingestion.service import FigureDescriber
from app.services.library.model import NewVersion
from tests.fakes import FakeExtractor, FakeParser, FakeVectorStore, FakeVision


ELEMENTS = [
    DocumentElement(element_type=ElementType.TEXT, content="Toyota Avanza harga Rp 230 jt",
                    page_number=4, section_heading="Harga", metadata={"headings": ["Harga"]}),
    DocumentElement(element_type=ElementType.FIGURE, content="", page_number=4, image_bytes=b"png"),
]


@pytest.fixture
def env(tmp_path):
    db = Database(db_path=tmp_path / "t.db")
    with db.get_connection() as conn:
        run_migrations(conn)
        conn.execute("INSERT INTO users (id, email) VALUES ('u1', 'u1@corp.com')")
    library = SQLiteLibraryRepository(db)
    queue = tmp_path / "queue"
    queue.mkdir()
    return db, library, queue


def _version(library, queue, n=1, doc="d1"):
    new = NewVersion(id=f"v{n}", content_hash=f"h{n}", original_filename="p.pdf", file_ext=".pdf",
                     size_bytes=3, page_count=1, uploaded_by="u1", pipeline_version="p1")
    if n == 1:
        v = library.create_document_with_version(doc, "Pricelist", "u1", new)
    else:
        v = library.create_next_version(doc, new)
    (queue / f"{v.id}.pdf").write_bytes(b"pdf")
    return v


def _build(db, library, queue, extractor=None, vision=None, vectors=None, elements=ELEMENTS):
    cfg = AppConfig()
    limits = AILimits.from_config(cfg)
    cache = SQLiteCacheRepository(db)
    vision = vision or FakeVision()
    extractor = extractor or FakeExtractor()
    vectors = vectors or FakeVectorStore()
    pipeline = DocumentPipeline(
        parser=FakeParser(elements),
        describer=FigureDescriber(vision, cache, "vlm", limits.vision),
        vector_store=vectors,
        extraction=ExtractionService(extractor, cache, limits.extraction, "p1", 5),
        features=SQLiteFeatureRepository(db),
        library=library,
        queue_dir=queue,
        config=cfg,
        limits=limits,
        count_tokens=lambda t: len(t.split()),
    )
    worker = DocumentWorker(SQLiteJobRepository(db), pipeline.process, pipeline.cleanup,
                            pipeline.source_path, cfg)
    return worker, vision, extractor, vectors


def _q(db, sql, *args):
    with db.get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


async def test_success_publishes_everything_atomically(env):
    db, library, queue = env
    v = _version(library, queue)
    worker, vision, extractor, vectors = _build(db, library, queue)
    await worker.run_once()

    [ver] = _q(db, "SELECT * FROM document_versions WHERE id = ?", v.id)
    assert ver["stage"] == "ready" and ver["error"] is None
    assert library.get_document("d1").latest_version_id == v.id
    [feat] = _q(db, "SELECT * FROM features WHERE version_id = ?", v.id)
    assert (feat["product_name"], feat["price"], feat["page_number"]) == ("Avanza", 230.0, 4)
    [section] = _q(db, "SELECT * FROM sections WHERE version_id = ?", v.id)
    assert feat["section_hash"] == section["section_hash"]
    assert vectors.count_version(v.id) == 2  # text + image description
    assert not (queue / f"{v.id}.pdf").exists()


async def test_failure_midway_leaves_no_visible_data(env):
    db, library, queue = env
    v = _version(library, queue)
    worker, _, _, vectors = _build(db, library, queue, extractor=FakeExtractor(fail=True))
    await worker.run_once()

    [ver] = _q(db, "SELECT * FROM document_versions WHERE id = ?", v.id)
    assert ver["stage"] == "queued"  # retried later
    assert _q(db, "SELECT * FROM features WHERE version_id = ?", v.id) == []
    assert _q(db, "SELECT * FROM sections WHERE version_id = ?", v.id) == []
    assert vectors.count_version(v.id) == 0  # vectors already written are cleaned up
    assert library.get_document("d1").latest_version_id is None


async def test_retry_uses_cache(env):
    db, library, queue = env
    v = _version(library, queue)
    vision = FakeVision()
    worker, _, _, _ = _build(db, library, queue, extractor=FakeExtractor(fail=True), vision=vision)
    await worker.run_once()
    assert vision.calls == 1

    with db.get_connection() as conn:
        conn.execute("UPDATE document_versions SET next_retry_at = datetime('now', '-1 seconds')")
    extractor = FakeExtractor()
    worker2, _, _, _ = _build(db, library, queue, extractor=extractor, vision=vision)
    await worker2.run_once()
    assert vision.calls == 1  # the image description comes from the cache
    assert _q(db, "SELECT stage FROM document_versions WHERE id = ?", v.id)[0]["stage"] == "ready"


async def test_cancel_before_publish(env):
    db, library, queue = env
    v = _version(library, queue)

    class CancellingExtractor(FakeExtractor):
        async def extract(self, text):
            SQLiteJobRepository(db).request_cancel(v.id)
            return await super().extract(text)

    worker, _, _, vectors = _build(db, library, queue, extractor=CancellingExtractor())
    await worker.run_once()
    assert _q(db, "SELECT stage FROM document_versions WHERE id = ?", v.id)[0]["stage"] == "cancelled"
    assert _q(db, "SELECT * FROM features") == []
    assert vectors.count_version(v.id) == 0


async def test_missing_source_file_fails_permanently(env):
    db, library, queue = env
    v = _version(library, queue)
    (queue / f"{v.id}.pdf").unlink()
    worker, _, _, _ = _build(db, library, queue)
    await worker.run_once()
    [ver] = _q(db, "SELECT * FROM document_versions WHERE id = ?", v.id)
    assert ver["stage"] == "failed" and "Upload this document again" in ver["error"]


async def test_empty_document_fails_permanently(env):
    db, library, queue = env
    v = _version(library, queue)
    worker, _, _, _ = _build(db, library, queue, elements=[])
    await worker.run_once()
    assert _q(db, "SELECT stage FROM document_versions WHERE id = ?", v.id)[0]["stage"] == "failed"


async def test_latest_version_is_highest_ready(env):
    db, library, queue = env
    _version(library, queue, 1)
    v2 = _version(library, queue, 2)
    worker, _, _, _ = _build(db, library, queue)
    # v1 and v2 are processed; the finish order does not affect the latest version.
    await worker.run_once()
    await worker.run_once()
    assert library.get_document("d1").latest_version_id == v2.id


async def test_vision_failure_counted_not_fatal(env):
    db, library, queue = env
    v = _version(library, queue)

    class BrokenVision(FakeVision):
        async def describe_image(self, el):
            raise TimeoutError()

    worker, _, _, _ = _build(db, library, queue, vision=BrokenVision())
    await worker.run_once()
    [ver] = _q(db, "SELECT * FROM document_versions WHERE id = ?", v.id)
    assert ver["stage"] == "ready" and ver["vision_failed"] == 1


async def test_two_workers_process_distinct_jobs(env):
    db, library, queue = env
    _version(library, queue, 1, doc="d1")
    library.create_document_with_version(
        "d2", "Brosur", "u1",
        NewVersion(id="w1", content_hash="hx", original_filename="b.pdf", file_ext=".pdf",
                   size_bytes=3, page_count=1, uploaded_by="u1", pipeline_version="p1"),
    )
    (queue / "w1.pdf").write_bytes(b"pdf")
    worker, _, _, _ = _build(db, library, queue)
    await asyncio.gather(worker.run_once(), worker.run_once())
    stages = {r["id"]: r["stage"] for r in _q(db, "SELECT id, stage FROM document_versions")}
    assert stages == {"v1": "ready", "w1": "ready"}
