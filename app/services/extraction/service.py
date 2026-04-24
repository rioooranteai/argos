import logging
from typing import Any

from app.core.database import db
from app.services.extraction.base.extraction_base import BaseExtractionProvider
from app.services.extraction.factories.extraction_factory import ExtractionFactory
from app.services.extraction.models import ExtractionResult

logger = logging.getLogger(__name__)

_MAX_CHUNK_CHARS = 100_000
_MIN_CHUNK_CHARS = 80

class ExtractionService:

    def __init__(
        self,
        provider: str = "pydantic_ai",
        **kwargs: Any,
    ):
        self._provider: BaseExtractionProvider = ExtractionFactory.create(
            provider=provider,
            **kwargs,
        )
        logger.info(f"ExtractionService siap dengan provider: '{provider}'")

    async def process_document_texts(
        self,
        document_id: str,
        chunks_text: list[str],
    ) -> dict:

        valid_texts = [t for t in chunks_text if len(t.strip()) >= _MIN_CHUNK_CHARS]

        if not valid_texts:
            logger.warning(f"Tidak ada teks valid untuk document_id: {document_id}")
            return ExtractionResult(
                status="failed",
                document_id=document_id,
                total_features_extracted=0,
            ).model_dump()

        combined_text = "\n\n--- Bagian Lanjutan ---\n\n".join(valid_texts)

        if len(combined_text) > _MAX_CHUNK_CHARS:
            combined_text = combined_text[:_MAX_CHUNK_CHARS]

        total_saved = 0

        try:
            extracted_features = await self._provider.extract(combined_text)

            valid_features = [
                f.model_dump for f in extracted_features
                if f.competitor_name and f.feature_name
            ]

            if valid_features:
                db.insert_features_batch(valid_features, document_id)
                total_saved = len(valid_features)

        except Exception as e:
            logger.error(f"Gagal saat proses ekstraksi: {e}", exc_info=True)

        return ExtractionResult(
            status="success",
            document_id=document_id,
            total_features_extracted=total_saved,
        ).model_dump()

    @property
    def available_providers(self) -> list[str]:
        return ExtractionFactory.available_providers()