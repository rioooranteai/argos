from abc import ABC, abstractmethod
from typing import Any

class BaseVectorStoreProvider(ABC):

    @abstractmethod
    def add_chunks(self, chunks: list) -> list[str]:
        """Menyimpan atau memperbarui chunk ke dalam vector store."""
        ...

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Mencari chunk yang paling relevan dengan query."""
        ...

    @abstractmethod
    def delete_by_ids(self, chunk_ids: list[str]) -> None:
        """Menghapus chunk berdasarkan ID."""
        ...

    @abstractmethod
    def delete_by_metadata(self, filter_dict: dict[str, Any]) -> None:
        """Menghapus chunk berdasarkan kriteria metadata."""
        ...

    @abstractmethod
    def delete_all(self) -> None:
        """Menghapus seluruh data dalam collection."""
        ...

    @abstractmethod
    def get_by_document_id(self, document_id: str) -> list[str]:
        """Ambil semua dokumen berdasarkan document_id dari metadata."""
        ...