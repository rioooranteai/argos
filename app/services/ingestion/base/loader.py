from __future__ import annotations
from abc import ABC, abstractmethod
from app.services.ingestion.model import DocumentElement

class BaseDocumentLoader(ABC):
    """
    Model Contract :
     - supports
     - load
    """

    @abstractmethod
    def supports(self, file_path: str) -> bool:
        """
        Return True jika provider ini bisa handle file tersebut.
        Biasanya dicek dari ekstensi atau MIME type.
        """

    @abstractmethod
    def load(self, file_path: str) -> list[DocumentElement]:
        """
        Parse dokumen dan kembalikan list elemen terstruktur.
        Urutan elemen harus mengikuti urutan kemunculan di dokumen.

        Raises:
            DocumentLoadError: jika dokumen tidak bisa dibaca.
        """