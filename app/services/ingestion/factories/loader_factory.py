import logging
from typing import Type

from app.services.ingestion.base.loader import BaseDocumentLoader
from app.services.ingestion.exceptions import UnsupportedFileTypeError
from app.services.ingestion.providers.loaders.docling_loader import DoclingLoader

logger = logging.getLogger(__name__)

class LoaderFactory:
    """
    Factory pattern untuk memilih DocumentLoader yang tepat
    berdasarkan tipe atau ekstensi file.
    """

    def __init__(self):
        # Mendaftarkan referensi Class (Bukan object/instance)
        # agar hemat memory saat awal sistem berjalan.
        self._registered_loaders: list[Type[BaseDocumentLoader]] = [
            DoclingLoader
        ]

    def get_loader(self, file_path: str) -> BaseDocumentLoader:
        """
        Mencari loader pertama yang mengembalikan True pada metode supports().
        """

        for LoaderClass in self._registered_loaders:
            temp_instance = LoaderClass()

            if temp_instance.supports(file_path):
                return temp_instance

        raise UnsupportedFileTypeError(file_path=file_path)
