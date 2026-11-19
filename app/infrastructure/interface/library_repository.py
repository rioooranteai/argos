from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.library.model import (
    DocumentListItem,
    DocumentVersion,
    LibraryDocument,
    NewVersion,
)


class BaseLibraryRepository(ABC):
    """Persistence untuk dokumen Library & versinya."""

    @abstractmethod
    def find_version_by_hash(self, content_hash: str) -> DocumentVersion | None:
        """Versi dengan isi file identik (kunci idempotensi), atau None."""

    @abstractmethod
    def create_document_with_version(
        self, document_id: str, display_name: str, owner_id: str, version: NewVersion
    ) -> DocumentVersion | None:
        """Buat dokumen + versi pertama secara atomik.

        Return None bila `content_hash` sudah dipakai (kalah balapan dengan upload
        lain yang sama) — caller membaca ulang versi yang sudah ada.
        """

    @abstractmethod
    def create_next_version(self, document_id: str, version: NewVersion) -> DocumentVersion | None:
        """Tambah versi baru (version_no = maks + 1). None bila hash sudah dipakai."""

    @abstractmethod
    def requeue_version(self, version_id: str, uploaded_by: str) -> DocumentVersion:
        """Reset versi failed/cancelled agar diproses ulang dari awal."""

    @abstractmethod
    def get_document(self, document_id: str) -> LibraryDocument | None: ...

    @abstractmethod
    def get_version(self, version_id: str) -> DocumentVersion | None: ...

    @abstractmethod
    def list_versions(self, document_id: str) -> list[DocumentVersion]:
        """Semua versi dokumen, terbaru dulu."""

    @abstractmethod
    def list_documents(
        self, query: str | None, uploaded_by: str | None, limit: int, offset: int
    ) -> list[DocumentListItem]:
        """Dokumen aktif (bukan archived), terbaru diperbarui dulu."""

    @abstractmethod
    def get_document_item(self, document_id: str) -> DocumentListItem | None: ...

    @abstractmethod
    def rename_document(self, document_id: str, display_name: str) -> None: ...
