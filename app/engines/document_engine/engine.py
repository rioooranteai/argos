import asyncio
import hashlib
import logging
from pathlib import Path
from typing import List

from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.vector_store.service import VectorStoreService

logger = logging.getLogger(__name__)


class DocumentProcessingEngine:
    """Orchestrator yang mengatur aliran data dari PDF -> Vector DB -> SQL DB."""

    def __init__(
            self,
            ingestion_svc: IngestionService,
            vector_store_svc: VectorStoreService,
            extraction_svc: ExtractionService,
    ):
        self.ingestion_svc = ingestion_svc
        self.vector_store_svc = vector_store_svc
        self.extraction_svc = extraction_svc

    @staticmethod
    def _document_id_for(file_path: str) -> str:
        """ID berbasis isi file: file yang sama → ID yang sama, apa pun namanya."""
        digest = hashlib.sha256()
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        return f"doc_{digest.hexdigest()[:16]}"

    async def process_single_file(self, file_path: str) -> dict:
        document_id = self._document_id_for(file_path)

        # Dokumen yang sama sudah pernah diproses → lewati Docling, Vision, dan
        # ekstraksi LLM (hemat waktu & biaya API, dan fitur di SQL tidak dobel).
        if self.vector_store_svc.get_by_document_id(document_id):
            logger.info(f"Dokumen {Path(file_path).name} sudah ada ({document_id}), dilewati.")
            return {
                "status": "skipped",
                "reason": "duplicate",
                "file": Path(file_path).name,
                "document_id": document_id,
            }

        # PDF → chunks
        chunks = await self.ingestion_svc.process_document(file_path, document_id=document_id)

        if not chunks:
            return {"status": "failed", "file": file_path}

        # Simpan chunks ke Vector DB
        # Embedding (HTTP ke OpenAI) sinkron → jalankan di thread.
        inserted_ids = await asyncio.to_thread(self.vector_store_svc.add_chunks, chunks)

        # Ambil teks dari Vector DB — engine yang ambil, bukan extraction service
        chunks_text = [chunk.text for chunk in chunks]

        # Kirim teks ke ExtractionService → simpan ke SQL DB
        extraction_result = await self.extraction_svc.process_document_texts(
            document_id=document_id,
            chunks_text=chunks_text,
        )

        return {
            "status": "success",
            "file": Path(file_path).name,
            "document_id": document_id,
            "vector_chunks_saved": len(inserted_ids),
            "sql_features_extracted": extraction_result.get("total_features_extracted", 0),
        }

    async def process_multiple_files(self, file_paths: List[str]) -> dict:
        results = []

        for file_path in file_paths:
            result = await self.process_single_file(file_path)
            results.append(result)

        return {
            "batch_status": "completed",
            "total_files_processed": len(file_paths),
            "details": results,
        }
