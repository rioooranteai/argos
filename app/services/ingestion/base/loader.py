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
        Return True if this provider can handle the file.
        Usually checked from the extension or MIME type.
        """

    @abstractmethod
    def load(self, file_path: str) -> list[DocumentElement]:
        """
        Parse the document and return a list of structured elements.
        The elements must be in the order they appear in the document.

        Raises:
            DocumentLoadError: if the document cannot be read.
        """