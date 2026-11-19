import logging
from typing import Any

from app.infrastructure.interface.embedder import BaseEmbedder
from app.services.ingestion.model import IndexChunk
from app.services.vector_store.base.vector_store_base import BaseVectorStoreProvider
from app.services.vector_store.factories.vector_store_factory import VectorStoreFactory
from app.services.vector_store.model import SearchHit

logger = logging.getLogger(__name__)


class VectorStoreService:
    def __init__(self, embedder: BaseEmbedder, provider: str = "chroma", **kwargs: Any):
        self._store: BaseVectorStoreProvider = VectorStoreFactory.create(
            embedder=embedder, provider=provider, **kwargs
        )
        logger.info(f"VectorStoreService siap dengan provider: '{provider}'")

    def add_chunks(self, chunks: list[IndexChunk]) -> list[str]:
        return self._store.add_chunks(chunks)

    def search(self, query: str, version_ids: list[str] | None, limit: int = 5) -> list[SearchHit]:
        return self._store.search(query, version_ids, limit)

    def delete_version(self, version_id: str) -> None:
        self._store.delete_version(version_id)

    def count_version(self, version_id: str) -> int:
        return self._store.count_version(version_id)
