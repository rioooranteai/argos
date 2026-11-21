from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.library.model import (
    DocumentListItem,
    DocumentVersion,
    LibraryDocument,
    NewVersion,
    PendingUpload,
)


class BaseLibraryRepository(ABC):
    """Persistence for Library documents & their versions."""

    @abstractmethod
    def find_version_by_hash(self, content_hash: str) -> DocumentVersion | None:
        """The version with identical file content (idempotency key), or None."""

    @abstractmethod
    def create_document_with_version(
        self, document_id: str, display_name: str, owner_id: str, version: NewVersion
    ) -> DocumentVersion | None:
        """Atomically create a document + its first version.

        Returns None when `content_hash` is already taken (lost the race to another
        identical upload) — the caller re-reads the existing version.
        """

    @abstractmethod
    def create_next_version(self, document_id: str, version: NewVersion) -> DocumentVersion | None:
        """Add a new version (version_no = max + 1). None when the hash is already taken."""

    @abstractmethod
    def requeue_version(self, version_id: str, uploaded_by: str) -> DocumentVersion:
        """Reset a failed/cancelled version so it is processed again from scratch."""

    @abstractmethod
    def get_document(self, document_id: str) -> LibraryDocument | None: ...

    @abstractmethod
    def get_version(self, version_id: str) -> DocumentVersion | None: ...

    @abstractmethod
    def list_versions(self, document_id: str) -> list[DocumentVersion]:
        """All versions of a document, newest first."""

    @abstractmethod
    def list_documents(
        self, query: str | None, uploaded_by: str | None, limit: int, offset: int
    ) -> list[DocumentListItem]:
        """Active (not archived) documents, most recently updated first."""

    @abstractmethod
    def get_document_item(self, document_id: str) -> DocumentListItem | None: ...

    @abstractmethod
    def rename_document(self, document_id: str, display_name: str) -> None: ...

    # ── Stage 2: delete / archive ───────────────────────────────────────

    @abstractmethod
    def detach_from_owner_notebooks(self, document_id: str, owner_id: str) -> int:
        """Remove the document from the notebooks of `owner_id`. Returns the number of notebooks."""

    @abstractmethod
    def count_notebook_uses(self, document_id: str) -> int:
        """Number of notebooks (anyone's) still using this document."""

    @abstractmethod
    def count_version_pins(self, version_id: str) -> int: ...

    @abstractmethod
    def archive_document(self, document_id: str) -> None: ...

    @abstractmethod
    def delete_document(self, document_id: str) -> None:
        """Permanently delete a document + every version (sections & features go too)."""

    @abstractmethod
    def delete_version(self, document_id: str, version_id: str) -> None:
        """Delete one version, then recompute `latest_version_id`."""

    @abstractmethod
    def transfer_ownership(self, from_user_id: str, to_user_id: str) -> int:
        """Transfer ownership of every document. Returns the number of documents."""

    # ── Stage 3: similarity suggestions ─────────────────────────────────

    @abstractmethod
    def list_fingerprints(self) -> list[tuple[str, str, bytes]]:
        """(document_id, display_name, fingerprint) from the latest version with a fingerprint,
        for every active document. Failed/cancelled versions are skipped."""

    @abstractmethod
    def create_pending(self, pending: PendingUpload) -> None: ...

    @abstractmethod
    def get_pending(self, pending_id: str) -> PendingUpload | None: ...

    @abstractmethod
    def delete_pending(self, pending_id: str) -> bool:
        """Returns False when it no longer exists (e.g. another request resolved it)."""

    @abstractmethod
    def list_expired_pending(self, older_than_minutes: int) -> list[PendingUpload]: ...
