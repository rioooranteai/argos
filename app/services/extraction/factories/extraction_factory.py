import logging
from typing import Any

from app.services.extraction.base.extraction_base import BaseExtractionProvider
from app.services.extraction.exceptions import UnsupportedProviderError
from app.services.extraction.providers.pydantic_ai_provider import PydanticAIExtractionProvider

logger = logging.getLogger(__name__)


class ExtractionFactory:
    _providers: dict[str, type[BaseExtractionProvider]] = {
        "pydantic_ai": PydanticAIExtractionProvider,
    }

    @classmethod
    def create(
            cls,
            provider: str = "pydantic_ai",
            **kwargs: Any,
    ) -> BaseExtractionProvider:
        if provider not in cls._providers:
            raise UnsupportedProviderError(
                f"Provider '{provider}' tidak tersedia. "
                f"Pilihan yang valid: {cls.available_providers()}"
            )

        logger.info(f"Membuat ExtractionProvider: '{provider}'")
        return cls._providers[provider](**kwargs)

    @classmethod
    def available_providers(cls) -> list[str]:
        return list(cls._providers.keys())

    @classmethod
    def register(cls, name: str, provider_class: type[BaseExtractionProvider]) -> None:
        cls._providers[name] = provider_class
        logger.info(f"Provider '{name}' berhasil didaftarkan.")
