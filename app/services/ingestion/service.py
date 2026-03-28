import asyncio
import logging
import uuid
from pathlib import Path
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
        self.loader_factory = loader_factory
        self.vision_factory = vision_factory
        self.chunker = chunker

    async def process_document(self, file_path: str) -> List[Chunk]:
        """
        Mengeksekusi siklus penuh (end-to-end) pembacaan satu dokumen.
        """
        doc_filename = Path(file_path).name
        document_id = f"doc_{uuid.uuid4().hex[:8]}"

        loader = self.loader_factory.get_loader(file_path)
        elements = loader.load(file_path)

        if not elements:
            return []

        vision_processor = self.vision_factory.get_processor()
        vision_tasks = []

        for el in elements:
            if vision_processor.supports(el):
                task = self._process_single_image(vision_processor, el)
                vision_tasks.append(task)

        if vision_tasks:
            await asyncio.gather(*vision_tasks)

        chunks = self.chunker.process_elements(
            elements=elements,
            document_id=document_id
        )

        return chunks

    async def _process_single_image(self, processor, element: DocumentElement):
        """Fungsi pembantu internal untuk memanggil Vision API."""
        try:
            deskripsi = await processor.describe_image(element)
            element.content = f"[DESKRIPSI VISUAL GRAFIK/GAMBAR]: {deskripsi}"
            element.image_bytes = None
        except Exception as e:
            element.content = "[GAMBAR GAGAL DIPROSES OLEH AI]"
            element.image_bytes = None