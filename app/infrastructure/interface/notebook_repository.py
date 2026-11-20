from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.notebook.model import ActiveSource, Notebook, NotebookSource


class SourceLimitReached(Exception):
    """Notebook sudah mencapai batas jumlah sumber."""


class BaseNotebookRepository(ABC):
    @abstractmethod
    def create(self, notebook_id: str, owner_id: str, title: str) -> Notebook: ...

    @abstractmethod
    def get(self, notebook_id: str, owner_id: str) -> Notebook | None:
        """None bila tidak ada atau bukan milik `owner_id`."""

    @abstractmethod
    def list_for_owner(self, owner_id: str) -> list[tuple[Notebook, int]]:
        """Notebook milik user beserta jumlah sumbernya, terbaru dulu."""

    @abstractmethod
    def rename(self, notebook_id: str, title: str) -> None: ...

    @abstractmethod
    def delete(self, notebook_id: str) -> None: ...

    @abstractmethod
    def touch(self, notebook_id: str) -> None: ...

    @abstractmethod
    def mark_opened(self, notebook_id: str) -> None:
        """Catat waktu notebook dibuka (pengganti localStorage di browser)."""

    @abstractmethod
    def list_sources(self, notebook_id: str) -> list[NotebookSource]: ...

    @abstractmethod
    def add_source(self, notebook_id: str, document_id: str, version_id: str, max_sources: int) -> bool:
        """Tambah sumber secara atomik (batas dicek dalam transaksi yang sama).

        Return False bila dokumen sudah ada di notebook.
        Raises SourceLimitReached bila notebook penuh.
        """

    @abstractmethod
    def set_enabled(self, notebook_id: str, document_id: str, enabled: bool) -> bool: ...

    @abstractmethod
    def set_version(self, notebook_id: str, document_id: str, version_id: str) -> bool: ...

    @abstractmethod
    def remove_source(self, notebook_id: str, document_id: str) -> bool: ...

    @abstractmethod
    def count_version_pins(self, version_id: str) -> int:
        """Jumlah notebook (mana pun) yang mem-pin versi ini."""

    @abstractmethod
    def active_sources(self, notebook_id: str) -> list[ActiveSource]:
        """Sumber yang dicentang dan versinya `ready`, urut waktu ditambahkan."""
