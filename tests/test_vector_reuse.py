"""Stage 3: vectors of unchanged chunks are reused from the previous version,
and reuse statistics are stored per version."""
from __future__ import annotations

import pytest

from app.tools.embedding.base import BaseEmbedder
from app.services.ingestion.model import DocumentElement, ElementType, IndexChunk
from app.services.vector_store.providers.chroma_provider import ChromaProvider
from tests.test_pipeline import (  # noqa: F401 — the `env` fixture is reused
    FakeVectors,
    _build,
    _q,
    _version,
    env,
)


def _el(text: str, heading: str, page: int = 1) -> DocumentElement:
    return DocumentElement(element_type=ElementType.TEXT, content=text, page_number=page,
                           section_heading=heading, metadata={"headings": [heading]})


V1 = [_el("Avanza Rp 230 jt", "Harga"), _el("Garansi 3 tahun", "Garansi"),
      _el("Bengkel di 30 kota", "Layanan")]
# v2: one section changed (price), two sections identical.
V2 = [_el("Avanza Rp 245 jt", "Harga"), _el("Garansi 3 tahun", "Garansi"),
      _el("Bengkel di 30 kota", "Layanan")]


async def _process(db, library, queue, n, elements, vectors):
    _version(library, queue, n)
    worker, _, extractor, _ = _build(db, library, queue, vectors=vectors, elements=elements)
    await worker.run_once()
    return extractor


async def test_unchanged_chunks_reuse_vectors(env):
    db, library, queue = env
    vectors = FakeVectors()
    await _process(db, library, queue, 1, V1, vectors)
    vectors.embedded.clear()

    await _process(db, library, queue, 2, V2, vectors)

    # Only the changed chunk is sent to the embedder.
    assert vectors.embedded == ["[Document: Pricelist]\nAvanza Rp 245 jt"]
    assert vectors.count_version("v2") == 3
    assert vectors.count_version("v1") == 3  # the old version is intact (can still be pinned)
    [v2] = _q(db, "SELECT stage FROM document_versions WHERE id = 'v2'")
    assert v2["stage"] == "ready"
    stats = library.get_version("v2").reuse_stats
    assert stats["chunks"] == 3 and stats["chunks_reused"] == 2


async def test_first_version_has_zero_reuse(env):
    db, library, queue = env
    await _process(db, library, queue, 1, V1, FakeVectors())
    stats = library.get_version("v1").reuse_stats
    assert stats["chunks"] == 3 and stats["chunks_reused"] == 0
    assert stats["units_cached"] == 0 and stats["units"] >= 1


def _chapter(text: str, chapter: str, heading: str) -> DocumentElement:
    # Different parent headings → the sections are not merged into one extraction unit.
    return DocumentElement(element_type=ElementType.TEXT, content=text, page_number=1,
                           section_heading=heading, metadata={"headings": [chapter, heading]})


async def test_extraction_cache_counted_for_unchanged_units(env):
    db, library, queue = env
    vectors = FakeVectors()
    base = [_chapter("Avanza Rp 230 jt", "Mobil", "Harga"), _chapter("Garansi 3 tahun", "Servis", "Garansi")]
    await _process(db, library, queue, 1, base, vectors)
    extractor = await _process(
        db, library, queue, 2, base + [_chapter("Promo DP 10%", "Promo", "Cicilan")], vectors
    )
    stats = library.get_version("v2").reuse_stats
    assert (stats["units"], stats["units_cached"]) == (3, 2)
    assert extractor.calls == 1  # only the new unit is sent to the LLM


async def test_different_pipeline_version_is_not_reused(env):
    db, library, queue = env
    vectors = FakeVectors()
    await _process(db, library, queue, 1, V1, vectors)
    with db.get_connection() as conn:  # e.g. the embedding model changed → PIPELINE_VERSION bumped
        conn.execute("UPDATE document_versions SET pipeline_version = 'p0' WHERE id = 'v1'")
    vectors.embedded.clear()

    await _process(db, library, queue, 2, V2, vectors)
    assert len(vectors.embedded) == 3
    assert library.get_version("v2").reuse_stats["chunks_reused"] == 0


async def test_requeue_clears_reuse_stats(env):
    db, library, queue = env
    await _process(db, library, queue, 1, V1, FakeVectors())
    assert library.requeue_version("v1", "u1").reuse_stats is None


# ── ChromaProvider asli ─────────────────────────────────────────────────


class CountingEmbedder(BaseEmbedder):
    def __init__(self):
        self.seen: list[str] = []

    def embed_documents(self, texts):
        self.seen.extend(texts)
        return [[float(len(t)), 1.0, 0.5] for t in texts]

    def embed_query(self, text):
        return [float(len(text)), 1.0, 0.5]

    @property
    def dimension(self):
        return 3


@pytest.fixture
def chroma(tmp_path):
    emb = CountingEmbedder()
    return ChromaProvider(emb, collection_name="reuse", db_path=str(tmp_path / "c")), emb


def _chunk(cid, text, version):
    return IndexChunk(cid, text, {"version_id": version, "document_id": "d", "page_number": 1})


def test_chroma_copies_vectors_without_embedding(chroma):
    store, emb = chroma
    store.add_chunks([_chunk("a1", "sama", "v1"), _chunk("a2", "lama", "v1")])
    emb.seen.clear()

    reuse = store.version_texts("v1")
    assert reuse == {"sama": "a1", "lama": "a2"}
    result = store.add_chunks([_chunk("b1", "sama", "v2"), _chunk("b2", "baru", "v2")], reuse)

    assert result.reused == 1 and result.ids == ["b1", "b2"]
    assert emb.seen == ["baru"]
    got = store.collection.get(ids=["a1", "b1"], include=["embeddings", "metadatas"])
    vecs = {i: list(e) for i, e in zip(got["ids"], got["embeddings"])}
    assert vecs["a1"] == vecs["b1"]
    metas = {i: m for i, m in zip(got["ids"], got["metadatas"])}
    assert metas["b1"]["version_id"] == "v2" and metas["a1"]["version_id"] == "v1"


def test_chroma_falls_back_when_old_chunk_is_gone(chroma):
    store, emb = chroma
    store.add_chunks([_chunk("a1", "sama", "v1")])
    reuse = store.version_texts("v1")
    store.delete_version("v1")
    emb.seen.clear()

    result = store.add_chunks([_chunk("b1", "sama", "v2")], reuse)
    assert result.reused == 0 and emb.seen == ["sama"]
