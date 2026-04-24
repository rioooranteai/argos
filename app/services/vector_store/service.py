import logging
from typing import Any

from app.core.interface.embedder import BaseEmbedder
from app.services.vector_store.base.vector_store_base import BaseVectorStoreProvider
from app.services.vector_store.factories.vector_store_factory import VectorStoreFactory

logger = logging.getLogger(__name__)


class VectorStoreService:

    def __init__(
            self,
            embedder: BaseEmbedder,
            provider: str = "chroma",
            **kwargs: Any,
    ):
        self._store: BaseVectorStoreProvider = VectorStoreFactory.create(
            embedder=embedder,
            provider=provider,
            **kwargs,
        )
        logger.info(f"VectorStoreService siap dengan provider: '{provider}'")

    def add_chunks(self, chunks: list) -> list[str]:
        logger.debug(f"Menyimpan {len(chunks)} chunk ke vector store.")
        return self._store.add_chunks(chunks)

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        logger.debug(f"Mencari: '{query}' (limit={limit})")
        return self._store.search(query, limit)

    def delete_by_ids(self, chunk_ids: list[str]) -> None:
        logger.debug(f"Menghapus {len(chunk_ids)} chunk by ID.")
        self._store.delete_by_ids(chunk_ids)

    def delete_by_metadata(self, filter_dict: dict[str, Any]) -> None:
        logger.debug(f"Menghapus chunk by metadata: {filter_dict}")
        self._store.delete_by_metadata(filter_dict)

    def delete_all(self) -> None:
        logger.warning("Menghapus SELURUH data di vector store.")
        self._store.delete_all()

    @property
    def available_providers(self) -> list[str]:
        return VectorStoreFactory.available_providers()

    def get_by_document_id(self, document_id: str) -> list[str]:
        """Ambil semua teks chunk berdasarkan document_id."""
        results = self._store.get_by_document_id(document_id)
        return results
