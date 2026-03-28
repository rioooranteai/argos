import logging
from pathlib import Path
from typing import List

from app.services.ingestion.service import IngestionService
from app.services.chroma_service import ChromaService
from app.services.extraction.service import ExtractionService

logger = logging.getLogger(__name__)

class DocumentProcessingEngine:
    """Orchestrator yang mengatur aliran data dari PDF -> Vector DB -> SQL DB."""

    def __init__(
            self,
            ingestion_svc: IngestionService,
            chroma_svc: ChromaService,
            extraction_svc: ExtractionService
    ):
        self.ingestion_svc = ingestion_svc
        self.chroma_svc = chroma_svc
        self.extraction_svc = extraction_svc

    async def process_single_file(self, file_path: str) -> dict:
        chunks = await self.ingestion_svc.process_document(file_path)

        if not chunks:
            return {"status": "failed", "file": file_path}

        document_id = chunks[0].metadata.get("document_id")

        inserted_ids = self.chroma_svc.add_chunks(chunks)

        extraction_result = await self.extraction_svc.process_indexed_document(
            document_id=document_id,
            chroma_svc=self.chroma_svc
        )

        return {
            "status": "success",
            "file": Path(file_path).name,
            "document_id": document_id,
            "vector_chunks_saved": len(inserted_ids),
            "sql_features_extracted": extraction_result.get("total_features_extracted", 0)
        }

    async def process_multiple_files(self, file_paths: List[str]) -> dict:

        results = []
        for file_path in file_paths:
            result = await self.process_single_file(file_path)
            results.append(result)

        return {
            "batch_status": "completed",
            "total_files_processed": len(file_paths),
            "details": results
        }