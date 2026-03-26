import logging

from app.services.ingestion.service import IngestionService
from app.services.chroma_service import ChromaService

logger = logging.getLogger(__name__)


class IndexingEngine:
    """
    Orkestrator utama untuk Bagian A: Data Ingestion & Indexing.
    Menghubungkan proses pemotongan dokumen hingga penyimpanan ke Vector DB.
    """

    def __init__(
            self,
            ingestion_service: IngestionService,
            chroma_service: ChromaService
    ):
        self.ingestion_svc = ingestion_service
        self.chroma_svc = chroma_service

    async def index_competitor_document(self, file_path: str, competitor_name: str) -> dict:
        """
        Alur kerja penuh: Baca PDF -> Extract Vision -> Chunk -> Embed -> Chroma DB.
        """
        logger.info(f"=== MEMULAI INDEXING ENGINE: {competitor_name} ===")

        try:
            # Tahap 1: Ekstraksi dan Chunking (Kerja berat)
            chunks = await self.ingestion_svc.process_document(
                file_path=file_path,
                competitor_name=competitor_name
            )

            if not chunks:
                logger.warning(f"Tidak ada chunk yang dihasilkan dari {file_path}")
                return {"status": "failed", "message": "Dokumen kosong atau gagal diproses"}

            # Tahap 2: Embedding dan Penyimpanan ke Chroma DB
            inserted_ids = self.chroma_svc.add_chunks(chunks)

            logger.info("=== INDEXING SELESAI DENGAN SUKSES ===")

            return {
                "status": "success",
                "competitor": competitor_name,
                "total_chunks_processed": len(chunks),
                "total_chunks_saved": len(inserted_ids)
            }

        except Exception as e:
            logger.error(f"Gagal melakukan indexing pada {file_path}: {str(e)}")
            raise