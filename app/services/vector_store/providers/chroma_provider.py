import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import chromadb

from app.infrastructure.interface.embedder import BaseEmbedder
from app.services.ingestion.model import IndexChunk
from app.services.vector_store.base.vector_store_base import BaseVectorStoreProvider
from app.services.vector_store.exceptions import VectorStoreInsertError, VectorStoreSearchError
from app.services.vector_store.model import AddChunksResult, SearchHit

logger = logging.getLogger(__name__)


def _clean_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma hanya menerima nilai skalar."""
    clean: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        clean[k] = v if isinstance(v, (str, int, float, bool)) else str(v)
    return clean


class ChromaProvider(BaseVectorStoreProvider):
    def __init__(
        self,
        embedder: BaseEmbedder,
        collection_name: str = "argos_chunks",
        db_path: str | None = None,
    ):
        self.embedder = embedder
        self.collection_name = collection_name

        from app.core.config import infra

        resolved_path = Path(db_path) if db_path else infra.chroma_path
        resolved_path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(resolved_path))
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        logger.info(f"ChromaProvider siap. Collection: '{self.collection_name}' | Path: '{resolved_path}'")

    def add_chunks(
        self, chunks: list[IndexChunk], reuse: Mapping[str, str] | None = None
    ) -> AddChunksResult:
        unique: dict[str, IndexChunk] = {}
        for chunk in chunks:
            unique.setdefault(chunk.chunk_id, chunk)
        if not unique:
            return AddChunksResult(ids=[])

        ids = list(unique)
        documents = [c.text for c in unique.values()]
        metadatas = [_clean_metadata(c.metadata) for c in unique.values()]
        try:
            known = self._reused_embeddings(documents, reuse or {})
            missing = [i for i, text in enumerate(documents) if text not in known]
            fresh = self.embedder.embed_documents([documents[i] for i in missing]) if missing else []
            fresh_by_index = dict(zip(missing, fresh))
            embeddings = [
                known[text] if text in known else fresh_by_index[i]
                for i, text in enumerate(documents)
            ]
            self.collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        except Exception as e:
            raise VectorStoreInsertError(f"Gagal menyimpan data ke ChromaDB: {e}") from e
        return AddChunksResult(ids=ids, reused=len(documents) - len(missing))

    def _reused_embeddings(
        self, documents: list[str], reuse: Mapping[str, str]
    ) -> dict[str, list[float]]:
        """Vektor chunk lama untuk teks yang identik (hanya batch ini, hemat memori)."""
        wanted = {reuse[t]: t for t in documents if t in reuse}
        if not wanted:
            return {}
        raw = self.collection.get(ids=list(wanted), include=["embeddings"])
        embeddings = raw.get("embeddings")
        if embeddings is None:
            return {}
        return {
            wanted[old_id]: [float(x) for x in emb]
            for old_id, emb in zip(raw.get("ids") or [], embeddings)
            if old_id in wanted
        }

    def version_texts(self, version_id: str) -> dict[str, str]:
        raw = self.collection.get(where={"version_id": version_id}, include=["documents"])
        return {
            text: chunk_id
            for chunk_id, text in zip(raw.get("ids") or [], raw.get("documents") or [])
            if text
        }

    def search(self, query: str, version_ids: list[str] | None, limit: int = 5) -> list[SearchHit]:
        if version_ids is not None and not version_ids:
            return []  # tidak ada sumber aktif → tidak ada hasil, bukan "semua"
        where = None
        if version_ids is not None:
            where = (
                {"version_id": version_ids[0]}
                if len(version_ids) == 1
                else {"version_id": {"$in": list(version_ids)}}
            )
        try:
            query_embedding = self.embedder.embed_query(query)
            raw = self.collection.query(
                query_embeddings=[query_embedding], n_results=limit, where=where
            )
        except Exception as e:
            raise VectorStoreSearchError(f"Gagal melakukan pencarian di ChromaDB: {e}") from e

        ids = (raw.get("ids") or [[]])[0]
        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        dists = (raw.get("distances") or [[None] * len(ids)])[0]
        return [
            SearchHit(id=ids[i], text=docs[i], distance=dists[i], metadata=dict(metas[i] or {}))
            for i in range(len(ids))
        ]

    def delete_version(self, version_id: str) -> None:
        self.collection.delete(where={"version_id": version_id})

    def count_version(self, version_id: str) -> int:
        return len(self.collection.get(where={"version_id": version_id}, include=[])["ids"])

    def heartbeat(self) -> None:
        self.client.heartbeat()
        self.collection.count()
