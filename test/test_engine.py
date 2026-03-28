import asyncio
import logging
import os
import json
from pathlib import Path

# 1. NYALAKAN LOGGER PALING PERTAMA SEBELUM IMPORT MODULE LOKAL
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# 2. BARU KITA IMPORT SEMUA KOMPONEN SISTEM KITA
from app.core.database import init_db
from app.engines.document_engine import DocumentProcessingEngine
from app.services.ingestion.factories.loader_factory import LoaderFactory
from app.services.ingestion.factories.vision_factory import VisionFactory
from app.services.ingestion.chunker import ContentAwareChunker
from app.services.ingestion.service import IngestionService
from app.services.chroma_service import ChromaService
from app.services.shared.factories.embedder_factory import get_embedder
from app.services.extraction.service import ExtractionService

async def run_test():
    logger.info("=== MEMULAI TEST ENGINE MANDIRI ===")

    # 3. Siapkan Database SQLite
    logger.info("Menginisialisasi tabel database...")
    init_db()

    # 4. Tentukan file yang akan dites
    # Sesuaikan dengan nama file PDF yang Anda gunakan tadi (contoh: 4x-strategy.pdf)
    test_file_path = r"D:\argos\example_document\EN-State-of-Mobile-Game-Market-Outlook-2024-Report.pdf" 
    
    if not os.path.exists(test_file_path):
        logger.error(f"Gagal: File '{test_file_path}' tidak ditemukan di {os.getcwd()}")
        logger.info(f"Silakan pastikan file PDF kompetitor Anda bernama '{test_file_path}' dan ada di folder ini.")
        return

    # 5. Rakit semua komponen (Dependencies Injection Manual)
    logger.info("Merakit komponen AI dan Database...")
    chroma_svc = ChromaService(embedder=get_embedder())
    
    ingestion_svc = IngestionService(
        loader_factory=LoaderFactory(),
        vision_factory=VisionFactory(),
        chunker=ContentAwareChunker()
    )
    
    extraction_svc = ExtractionService()

    # 6. Bangun Engine
    engine = DocumentProcessingEngine(
        ingestion_svc=ingestion_svc,
        chroma_svc=chroma_svc,
        extraction_svc=extraction_svc
    )

    # 7. Eksekusi Engine
    logger.info(f"Mengirim dokumen {test_file_path} ke Engine untuk diproses penuh...")
    
    result = await engine.process_single_file(test_file_path)

    # 8. Tampilkan Hasil Akhir
    logger.info("=== HASIL EKSEKUSI ENGINE ===")
    print(json.dumps(result, indent=4))

if __name__ == "__main__":
    asyncio.run(run_test())