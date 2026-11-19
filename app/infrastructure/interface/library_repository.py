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

    # ── Tahap 2: hapus / arsip ──────────────────────────────────────────

    @abstractmethod
    def detach_from_owner_notebooks(self, document_id: str, owner_id: str) -> int:
        """Lepas dokumen dari notebook milik `owner_id`. Return jumlah notebook."""

    @abstractmethod
    def count_notebook_uses(self, document_id: str) -> int:
        """Jumlah notebook (siapa pun) yang masih memakai dokumen ini."""

    @abstractmethod
    def count_version_pins(self, version_id: str) -> int: ...

    @abstractmethod
    def archive_document(self, document_id: str) -> None: ...

    @abstractmethod
    def delete_document(self, document_id: str) -> None:
        """Hapus permanen dokumen + semua versi (bagian & features ikut terhapus)."""

    @abstractmethod
    def delete_version(self, document_id: str, version_id: str) -> None:
        """Hapus satu versi lalu hitung ulang `latest_version_id`."""

    @abstractmethod
    def transfer_ownership(self, from_user_id: str, to_user_id: str) -> int:
        """Pindahkan kepemilikan semua dokumen. Return jumlah dokumen."""
