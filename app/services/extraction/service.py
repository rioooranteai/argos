import logging
from typing import Any

from app.services.extraction.base.extraction_base import BaseExtractionProvider
from app.infrastructure.interface.feature_repository import BaseFeatureRepository
from app.services.extraction.factories.extraction_factory import ExtractionFactory
from app.services.extraction.model import ExtractionResult

logger = logging.getLogger(__name__)

_MAX_CHUNK_CHARS = 100_000
_MIN_CHUNK_CHARS = 80


class ExtractionService:
    """Orchestrates LLM-based feature extraction and persistence.

    The service does not know how features are stored — it depends only on
    the FeatureRepository port. Swap the adapter (SQLite, Postgres, in-memory
    for tests) without touching this class.
    """

    def __init__(
        self,
        repository: BaseFeatureRepository,
        provider: str = "pydantic_ai",
        **kwargs: Any,
    ):
        self._repo = repository
        self._provider: BaseExtractionProvider = ExtractionFactory.create(
            provider=provider,
            **kwargs,
        )
        logger.info(f"ExtractionService ready with provider: '{provider}'")

    async def process_document_texts(
        self,
        document_id: str,
        chunks_text: list[str],
    ) -> dict:

        valid_texts = [t for t in chunks_text if len(t.strip()) >= _MIN_CHUNK_CHARS]

        if not valid_texts:
            logger.warning(f"No valid text for document_id: {document_id}")
            return ExtractionResult(
                status="failed",
                document_id=document_id,
                total_features_extracted=0,
            ).model_dump()

        combined_text = "\n\n--- Bagian Lanjutan ---\n\n".join(valid_texts)

        if len(combined_text) > _MAX_CHUNK_CHARS:
            combined_text = combined_text[:_MAX_CHUNK_CHARS]

        try:
            extracted_features = await self._provider.extract(combined_text)

            # Drop rows that fail the prompt's required-field contract:
            # `product_name` is required (str, non-empty). `brand_name` may
            # legitimately be null (e.g. unbranded product family).
            valid_features = [
                f.model_dump() for f in extracted_features
                if f.product_name and f.product_name.strip()
            ]

            if valid_features:
                self._repo.insert_batch(valid_features, document_id)

            return ExtractionResult(
                status="success",
                document_id=document_id,
                total_features_extracted=len(valid_features),
            ).model_dump()

        except Exception as e:
            logger.error(f"Extraction failed: {e}", exc_info=True)
            return ExtractionResult(
                status="failed",
                document_id=document_id,
                total_features_extracted=0,
            ).model_dump()

    @property
    def available_providers(self) -> list[str]:
        return ExtractionFactory.available_providers()
