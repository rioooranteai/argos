import logging
from pathlib import Path
from typing import Any

import chromadb
from app.core.interface.embedder import BaseEmbedder
from app.services.vector_store.base.vector_store_base import BaseVectorStoreProvider
from app.services.vector_store.exceptions import VectorStoreInsertError, VectorStoreSearchError

logger = logging.getLogger(__name__)


class ChromaProvider(BaseVectorStoreProvider):

    def __init__(
            self,
            embedder: BaseEmbedder,
            collection_name: str = "competitor_knowledge",
            db_path: str | None = None,
    ):
        self.embedder = embedder
        self.collection_name = collection_name

        resolved_path = Path(db_path) if db_path else Path(__file__).resolve().parents[4] / "chroma_db"
        resolved_path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(resolved_path))
        self.collection = self.client.get_or_create_collection(name=self.collection_name)

        logger.info(f"ChromaProvider siap. Collection: '{self.collection_name}' | Path: '{resolved_path}'")

    def add_chunks(self, chunks: list) -> list[str]:
        if not chunks:
            return []

        ids, documents, metadatas = [], [], []
        seen_ids = set()

        for chunk in chunks:
            if chunk.chunk_id in seen_ids:
                logger.debug(f"Mengabaikan chunk duplikat: {chunk.chunk_id}")
                continue

            seen_ids.add(chunk.chunk_id)

            clean_meta = {}
            if chunk.metadata:
                for k, v in chunk.metadata.items():
                    if v is None:
                        continue
                    if isinstance(v, (str, int, float, bool)):
                        clean_meta[k] = v
                    elif isinstance(v, list) and all(isinstance(i, (str, int, float, bool)) for i in v):
                        clean_meta[k] = v
                    else:
                        clean_meta[k] = str(v)

            ids.append(chunk.chunk_id)
            documents.append(chunk.text)
            metadatas.append(clean_meta)

        if not ids:
            return []

        try:
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            logger.debug(f"Berhasil menyimpan {len(ids)} chunk.")
            return ids
        except Exception as e:
            raise VectorStoreInsertError(f"Gagal menyimpan data ke ChromaDB: {e}") from e

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        try:
            query_embedding = self.embedder.embed_query(query)
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
            )
            return results
        except Exception as e:
            raise VectorStoreSearchError(f"Gagal melakukan pencarian di ChromaDB: {e}") from e

    def delete_by_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self.collection.delete(ids=chunk_ids)
        logger.debug(f"Berhasil menghapus {len(chunk_ids)} chunk by ID.")

    def delete_by_metadata(self, filter_dict: dict[str, Any]) -> None:
        self.collection.delete(where=filter_dict)
        logger.debug(f"Berhasil menghapus chunk by metadata: {filter_dict}")

    def delete_all(self) -> None:
        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        logger.warning(f"Seluruh data di collection '{self.collection_name}' telah dihapus.")

    def get_by_document_id(self, document_id: str) -> list[str]:
        result = self.collection.get(
            where={"document_id": document_id},
            include=["documents"],
        )
        return result.get("documents", [])
