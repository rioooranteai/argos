import logging
from typing import Any

from app.services.shared.base.embedder import BaseEmbedder
from app.services.vector_store.base.vector_store_base import BaseVectorStoreProvider
from app.services.vector_store.exceptions import UnsupportedProviderError
from app.services.vector_store.providers.chroma_provider import ChromaProvider

logger = logging.getLogger(__name__)


class VectorStoreFactory:
    _providers: dict[str, type[BaseVectorStoreProvider]] = {
        "chroma": ChromaProvider,
    }

    @classmethod
    def create(
            cls,
            embedder: BaseEmbedder,
            provider: str = "chroma",
            **kwargs: Any,
    ) -> BaseVectorStoreProvider:
        if provider not in cls._providers:
            raise UnsupportedProviderError(
                f"Provider '{provider}' tidak tersedia. "
                f"Pilihan yang valid: {cls.available_providers()}"
            )

        logger.info(f"Membuat VectorStore provider: '{provider}'")
        return cls._providers[provider](embedder=embedder, **kwargs)

    @classmethod
    def available_providers(cls) -> list[str]:
        return list(cls._providers.keys())

    @classmethod
    def register(cls, name: str, provider_class: type[BaseVectorStoreProvider]) -> None:
        """Daftarkan provider baru secara dinamis."""
        cls._providers[name] = provider_class
        logger.info(f"Provider '{name}' berhasil didaftarkan.")
