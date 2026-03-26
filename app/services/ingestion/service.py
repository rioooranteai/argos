import asyncio
import logging
from typing import List

from app.services.ingestion.factories.loader_factory import LoaderFactory
from app.services.ingestion.factories.vision_factory import VisionFactory
from app.services.ingestion.chunker import ContentAwareChunker
from app.services.ingestion.models import Chunk, DocumentElement

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Service khusus untuk menangani proses ekstraksi dokumen mentah (PDF/MD)
    menjadi potongan-potongan teks (Chunks) yang siap di-embed.
    """

    def __init__(
            self,
            loader_factory: LoaderFactory,
            vision_factory: VisionFactory,
            chunker: ContentAwareChunker,
    ):
        # Menerima alat-alat kerjanya dari luar (Dependency Injection)
        self.loader_factory = loader_factory
        self.vision_factory = vision_factory
        self.chunker = chunker

    async def process_document(self, file_path: str, competitor_name: str) -> List[Chunk]:
        """
        Mengeksekusi siklus penuh (end-to-end) pembacaan satu dokumen.
        """
        logger.info(f"Memulai proses Ingestion (Baca & Potong) untuk: {file_path}")

        # 1. LOADER: Baca file dan jadikan DocumentElement mentah
        loader = self.loader_factory.get_loader(file_path)
        elements = loader.load(file_path)

        if not elements:
            logger.warning(f"Tidak ada elemen yang bisa diekstrak dari {file_path}")
            return []

        # 2. VISION: Cari gambar/grafik dan deskripsikan menggunakan AI
        vision_processor = self.vision_factory.get_processor()
        vision_tasks = []

        for el in elements:
            # Jika elemen ini adalah gambar dan disupport oleh Vision Processor
            if vision_processor.supports(el):
                task = self._process_single_image(vision_processor, el)
                vision_tasks.append(task)

        # Eksekusi semua proses baca gambar secara bersamaan (Paralel) agar cepat!
        if vision_tasks:
            logger.info(f"Memproses {len(vision_tasks)} gambar/grafik ke Vision API...")
            await asyncio.gather(*vision_tasks)

        # 3. CHUNKER: Potong-potong elemen menjadi Chunk dan suntikkan metadata Bab
        chunks = self.chunker.chunk(
            elements=elements,
            source_doc=file_path,
            competitor_name=competitor_name
        )

        logger.info(f"Proses Ingestion selesai. Menghasilkan {len(chunks)} chunks.")
        return chunks

    async def _process_single_image(self, processor, element: DocumentElement):
        """Fungsi pembantu internal untuk memanggil Vision API."""
        try:
            # Panggil AI untuk mendeskripsikan gambar
            deskripsi = await processor.describe_image(element)

            # Timpa teks elemen yang kosong dengan hasil deskripsi AI
            element.content = f"[DESKRIPSI VISUAL GRAFIK/GAMBAR]: {deskripsi}"

            # Hapus byte gambar dari memory agar RAM tidak jebol
            element.image_bytes = None

        except Exception as e:
            logger.error(f"Gagal memproses gambar di halaman {element.page_number}: {str(e)}")
            element.content = "[GAMBAR GAGAL DIPROSES OLEH AI]"
            element.image_bytes = None