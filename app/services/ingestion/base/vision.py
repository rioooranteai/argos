from __future__ import annotations
from abc import ABC, abstractmethod
from app.services.ingestion.models import DocumentElement

class BaseVisionProcessor(ABC):
    """
    Model Contract :
        - chunk
    """

    @abstractmethod
    def supports(self, element: DocumentElement) -> bool:
        """
        Return True jika element ini bisa diproses.
        Umumnya hanya True untuk ElementType.FIGURE yang punya image_bytes.
        """

    @abstractmethod
    async def describe(self, element: DocumentElement) -> str:
        """
        Kirim gambar ke VLM dan kembalikan deskripsi teks.
        Deskripsi harus mencakup: angka, label, tren, dan konteks visual.

        Raises:
            VisionProcessingError: jika VLM gagal memproses gambar.
        """