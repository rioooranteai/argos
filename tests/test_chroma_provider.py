"""ChromaProvider: filter per versi, hasil bertipe, hapus per versi (Chroma asli, embedder palsu)."""
from __future__ import annotations

import pytest

from app.infrastructure.interface.embedder import BaseEmbedder
from app.services.ingestion.model import IndexChunk
from app.services.vector_store.providers.chroma_provider import ChromaProvider


class FakeEmbedder(BaseEmbedder):
    def _vec(self, text: str) -> list[float]:
        return [float("avanza" in text.lower()), float("honda" in text.lower()), 1.0]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    @property
    def dimension(self):
        return 3


def chunk(cid: str, text: str, version: str) -> IndexChunk:
    return IndexChunk(cid, text, {"version_id": version, "document_id": "d", "page_number": 1, "none": None})


@pytest.fixture
def store(tmp_path):
    s = ChromaProvider(FakeEmbedder(), collection_name="test_chunks", db_path=str(tmp_path / "chroma"))
    s.add_chunks([
        chunk("a1", "Avanza 230 jt", "v1"),
        chunk("a2", "Avanza 235 jt", "v2"),
        chunk("h1", "Honda Brio", "v3"),
        chunk("a1", "duplikat diabaikan", "v1"),
    ])
    return s


def test_filter_by_versions(store):
    hits = store.search("avanza", ["v2"], limit=5)
    assert [h.id for h in hits] == ["a2"]
    assert hits[0].metadata["version_id"] == "v2"
    assert "none" not in hits[0].metadata  # nilai None tidak disimpan


def test_multiple_versions(store):
    assert {h.id for h in store.search("avanza", ["v1", "v3"], limit=5)} == {"a1", "h1"}


def test_empty_version_list_returns_nothing(store):
    assert store.search("avanza", [], limit=5) == []


def test_delete_version(store):
    assert store.count_version("v1") == 1
    store.delete_version("v1")
    assert store.count_version("v1") == 0
    assert store.count_version("v2") == 1


def test_heartbeat(store):
    store.heartbeat()  # tidak melempar exception
