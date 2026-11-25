"""Library use cases: upload (idempotent), list, details, rename.

Documents are NOT processed here. An upload only stores the file in the queue
folder (``<queue>/<version_id><ext>``) and records a version with status
``queued``; the worker processes it.

A new document whose content resembles a Library document is
not registered right away: the file is kept as *pending* (``<queue>/pending-<id><ext>``)
until the user chooses "new version" or "separate document".
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import uuid
from pathlib import Path, PurePath
from typing import Literal, Protocol

from app.core.config import AppConfig
from app.core.errors import (
    ArgosError,
    ConflictError,
    NotFoundError,
    PayloadTooLarge,
    PermissionDenied,
    ValidationError,
)
from app.services.library.model import (
    FINAL_STAGES,
    RECLAIMABLE_STAGES,
    DocumentListItem,
    DocumentVersion,
    IncomingFile,
    NewVersion,
    PendingUpload,
    UploadFileResult,
)
from app.services.library.ports import BaseJobRepository, BaseLibraryRepository
from app.services.library.similarity import SimilarDocument, extract_text, fingerprint, most_similar
from app.services.library.upload import ReceivedFile, count_pages, receive_upload
from app.services.user.model import CurrentUser
from app.services.user.ports import BaseUserRepository

logger = logging.getLogger(__name__)

_MB = 1024 * 1024


class _VectorDeleter(Protocol):
    def delete_version(self, version_id: str) -> None: ...


def queued_file_path(queue_dir: Path, version_id: str, ext: str) -> Path:
    """Where a version's original file lives while it waits for / is processed by the worker."""
    return queue_dir / f"{version_id}{ext}"


def pending_file_path(queue_dir: Path, pending_id: str, ext: str) -> Path:
    """Where an upload waiting for the "new version / separate document" choice lives."""
    return queue_dir / f"pending-{pending_id}{ext}"


class LibraryService:
    def __init__(
        self,
        repository: BaseLibraryRepository,
        queue_dir: Path,
        config: AppConfig,
        vector_store: _VectorDeleter | None = None,
        jobs: BaseJobRepository | None = None,
        users: BaseUserRepository | None = None,
    ) -> None:
        self._repo = repository
        self._queue_dir = queue_dir
        self._cfg = config
        self._vectors = vector_store
        self._jobs = jobs
        self._users = users

    # ── Upload ─────────────────────────────────────────────────────────

    async def upload_documents(
        self, user: CurrentUser, files: list[IncomingFile], max_files: int | None = None
    ) -> list[UploadFileResult]:
        """Upload one batch of new documents. Results are reported per file.

        ``max_files`` lets the caller (e.g. a notebook) limit it to the remaining slots.
        """
        limit = self._cfg.UPLOAD_MAX_FILES_PER_BATCH
        if max_files is not None:
            limit = min(limit, max_files)
        if not files:
            raise ValidationError("Choose at least one file.", code="NO_FILES")
        if len(files) > limit:
            raise ValidationError(
                f"At most {limit} files per upload.", code="TOO_MANY_FILES"
            )
        self.purge_expired_pending()

        results: list[UploadFileResult] = []
        per_file = self._cfg.UPLOAD_MAX_FILE_MB * _MB
        batch_limit = self._cfg.UPLOAD_MAX_BATCH_MB * _MB
        batch_bytes = 0
        batch_error = ValidationError(
            f"The upload is larger than {self._cfg.UPLOAD_MAX_BATCH_MB} MB in total.", code="BATCH_TOO_LARGE"
        )

        for file in files:
            filename = PurePath((file.filename or "").replace("\\", "/")).name or "document"
            try:
                self._check_extension(filename)
                cap = min(per_file, batch_limit - batch_bytes)
                if cap <= 0:
                    raise batch_error
                try:
                    received = await receive_upload(file, self._queue_dir, cap)
                except PayloadTooLarge:
                    # The limit hit may be the batch limit (remaining quota < per-file limit).
                    if cap < per_file:
                        raise batch_error from None
                    raise
                batch_bytes += received.size_bytes
                results.append(await self._register_new_document(user, received))
            except ArgosError as exc:
                results.append(
                    UploadFileResult(
                        filename=filename,
                        status="rejected",
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )
        return results

    async def upload_new_version(
        self, user: CurrentUser, document_id: str, file: IncomingFile
    ) -> UploadFileResult:
        document = self._repo.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Document not found.")

        filename = PurePath((file.filename or "").replace("\\", "/")).name or "document"
        self._check_extension(filename)
        received = await receive_upload(file, self._queue_dir, self._cfg.UPLOAD_MAX_FILE_MB * _MB)
        try:
            page_count = await asyncio.to_thread(self._validate_pages, received)
            existing = self._repo.find_version_by_hash(received.sha256)
            if existing is not None:
                if existing.document_id != document_id:
                    raise ConflictError(
                        "This file is already in the Library as a different document.",
                        code="FILE_BELONGS_TO_OTHER_DOCUMENT",
                        details={"document_id": existing.document_id},
                    )
                return self._handle_existing(user, existing, received)
            # An explicit version upload is not similarity-checked, but its fingerprint is
            # stored so this version is compared against future uploads.
            sketch = await asyncio.to_thread(self._fingerprint, received)
            return self._create_version(user, document_id, received, page_count, sketch)
        finally:
            received.path.unlink(missing_ok=True)

    # ── Uploads that resemble a Library document ───────────────────────

    async def resolve_pending(
        self, user: CurrentUser, pending_id: str, action: Literal["new_version", "separate"]
    ) -> UploadFileResult:
        """Resolve a *pending* upload: make it a new version of the candidate, or a separate document."""
        self.purge_expired_pending()
        pending = self._repo.get_pending(pending_id)
        if pending is None or pending.user_id != user.id:
            raise NotFoundError(
                "This upload has expired or was already handled. Upload the file again.",
                code="PENDING_UPLOAD_NOT_FOUND",
            )
        if action == "new_version":
            target = self._repo.get_document(pending.candidate_document_id)
            if target is None or target.status != "active":
                raise ConflictError(
                    "The similar document was deleted. Save it as a separate document.",
                    code="SIMILAR_DOCUMENT_GONE",
                )
        # Claim: only one request can resolve this pending upload.
        if not self._repo.delete_pending(pending_id):
            raise NotFoundError(
                "This upload was already handled.", code="PENDING_UPLOAD_NOT_FOUND"
            )
        path = pending_file_path(self._queue_dir, pending.id, pending.file_ext)
        if not path.exists():
            raise NotFoundError(
                "The uploaded file is gone. Upload the file again.", code="PENDING_UPLOAD_NOT_FOUND"
            )
        received = ReceivedFile(
            path=path,
            original_filename=pending.original_filename,
            ext=pending.file_ext,
            size_bytes=pending.size_bytes,
            sha256=pending.content_hash,
        )
        try:
            existing = self._repo.find_version_by_hash(pending.content_hash)
            if existing is not None:  # an identical file came in another way while waiting
                return self._handle_existing(user, existing, received)
            if action == "separate":
                return self._create_document(user, received, pending.page_count, pending.fingerprint)
            return self._create_version(
                user, pending.candidate_document_id, received, pending.page_count, pending.fingerprint
            )
        finally:
            path.unlink(missing_ok=True)

    def purge_expired_pending(self) -> int:
        """Delete *pending* uploads not resolved in time (file + row)."""
        purged = 0
        for pending in self._repo.list_expired_pending(self._cfg.PENDING_UPLOAD_TTL_MINUTES):
            if self._repo.delete_pending(pending.id):
                pending_file_path(self._queue_dir, pending.id, pending.file_ext).unlink(missing_ok=True)
                purged += 1
        if purged:
            logger.info("Deleted %d expired pending uploads.", purged)
        return purged

    # ── Query ──────────────────────────────────────────────────────────

    def list_documents(
        self, query: str | None, uploaded_by: str | None, limit: int, offset: int
    ) -> list[DocumentListItem]:
        return self._repo.list_documents(query, uploaded_by, limit=min(limit, 100), offset=offset)

    def get_document(self, document_id: str) -> tuple[DocumentListItem, list[DocumentVersion]]:
        item = self._repo.get_document_item(document_id)
        if item is None or item.document.status != "active":
            raise NotFoundError("Document not found.")
        return item, self._repo.list_versions(document_id)

    def get_version(self, version_id: str) -> DocumentVersion:
        version = self._repo.get_version(version_id)
        if version is None:
            raise NotFoundError("Document version not found.")
        return version

    def rename_document(self, user: CurrentUser, document_id: str, display_name: str) -> DocumentListItem:
        document = self._repo.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Document not found.")
        if document.owner_id != user.id and not user.is_admin:
            raise PermissionDenied("Only the uploader can rename this document.")
        name = " ".join(display_name.split())
        if not name:
            raise ValidationError("The document name cannot be empty.")
        self._repo.rename_document(document_id, name)
        return self._repo.get_document_item(document_id)

    # ── Delete / archive ───────────────────────────────────────────────

    def delete_document(self, user: CurrentUser, document_id: str) -> Literal["deleted", "archived"]:
        document = self._repo.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Document not found.")
        self._check_can_manage(user, document.owner_id)

        # The owner's own notebooks drop the source; other users' notebooks are left alone.
        self._repo.detach_from_owner_notebooks(document_id, document.owner_id)
        if self._repo.count_notebook_uses(document_id) > 0:
            self._repo.archive_document(document_id)
            logger.info("Document %s archived (still used by another notebook).", document_id)
            return "archived"

        self._purge(document_id)
        logger.info("Document %s permanently deleted.", document_id)
        return "deleted"

    def purge_if_unused(self, document_id: str) -> bool:
        """Permanently delete an ARCHIVED document that no notebook uses any more."""
        document = self._repo.get_document(document_id)
        if document is None or document.status != "archived":
            return False
        if self._repo.count_notebook_uses(document_id) > 0:
            return False
        self._purge(document_id)
        logger.info("Archived document %s permanently deleted (no longer used).", document_id)
        return True

    def delete_version(self, user: CurrentUser, document_id: str, version_id: str) -> None:
        document = self._repo.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Document not found.")
        self._check_can_manage(user, document.owner_id)

        versions = self._repo.list_versions(document_id)
        version = next((v for v in versions if v.id == version_id), None)
        if version is None:
            raise NotFoundError("Document version not found.")
        if len(versions) == 1:
            raise ConflictError(
                "This is the only version. Delete the document if it is no longer needed.",
                code="ONLY_VERSION",
            )
        pins = self._repo.count_version_pins(version_id)
        if pins:
            raise ConflictError(
                f"Version {version.version_no} is still used in {pins} notebook(s). "
                "Ask its users to switch to another version first.",
                code="VERSION_IN_USE",
                details={"notebooks": pins},
            )

        if version.stage not in FINAL_STAGES and self._jobs is not None:
            self._jobs.request_cancel(version_id)
        try:
            self._repo.delete_version(document_id, version_id)
        except sqlite3.IntegrityError:
            # A notebook pinned this version between the check and the delete.
            raise ConflictError(
                f"Version {version.version_no} was just added to a notebook.", code="VERSION_IN_USE"
            ) from None
        self._remove_version_data(version)
        logger.info("Version %s (v%s) of document %s deleted.", version_id, version.version_no, document_id)

    def _purge(self, document_id: str) -> None:
        versions = self._repo.list_versions(document_id)
        if self._jobs is not None:
            for v in versions:
                if v.stage not in FINAL_STAGES:
                    self._jobs.request_cancel(v.id)
        try:
            self._repo.delete_document(document_id)
        except sqlite3.IntegrityError:
            raise ConflictError(
                "The document was just added to another notebook. Try again.", code="DOCUMENT_IN_USE"
            ) from None
        # Database first, then vectors & files: orphan vectors are never read by chat
        # (their version no longer exists), while the reverse would break a live version.
        for v in versions:
            self._remove_version_data(v)

    def _remove_version_data(self, version: DocumentVersion) -> None:
        if self._vectors is not None:
            try:
                self._vectors.delete_version(version.id)
            except Exception:
                logger.exception("Failed to delete vectors of version %s (they are invisible to chat).", version.id)
        queued_file_path(self._queue_dir, version.id, version.file_ext).unlink(missing_ok=True)

    def _check_can_manage(self, user: CurrentUser, owner_id: str) -> None:
        if owner_id == user.id:
            return
        if user.is_admin and self._users is not None:
            owner = self._users.get(owner_id)
            if owner is None or not owner.is_active:
                return
        raise PermissionDenied(
            "Only the document's uploader can delete it.", code="NOT_DOCUMENT_OWNER"
        )

    # ── Internal ───────────────────────────────────────────────────────

    def _check_extension(self, filename: str) -> None:
        ext = PurePath(filename).suffix.lower()
        if ext not in self._cfg.UPLOAD_ALLOWED_EXTENSIONS:
            allowed = ", ".join(e.lstrip(".").upper() for e in self._cfg.UPLOAD_ALLOWED_EXTENSIONS)
            raise ValidationError(f"Unsupported format. Use {allowed}.", code="UNSUPPORTED_FILE_TYPE")

    def _validate_pages(self, received: ReceivedFile) -> int | None:
        pages = count_pages(received.path, received.ext)
        if pages is not None and pages > self._cfg.UPLOAD_MAX_PAGES:
            raise ValidationError(
                f"The document has {pages} pages, over the {self._cfg.UPLOAD_MAX_PAGES}-page limit.",
                code="TOO_MANY_PAGES",
            )
        return pages

    async def _register_new_document(self, user: CurrentUser, received: ReceivedFile) -> UploadFileResult:
        try:
            page_count = await asyncio.to_thread(self._validate_pages, received)
            existing = self._repo.find_version_by_hash(received.sha256)
            if existing is not None:
                return self._handle_existing(user, existing, received)

            sketch = await asyncio.to_thread(self._fingerprint, received)
            similar = await asyncio.to_thread(self._find_similar, sketch)
            if similar is not None:
                return self._hold_pending(user, received, page_count, sketch, similar)
            return self._create_document(user, received, page_count, sketch)
        finally:
            received.path.unlink(missing_ok=True)  # no-op when the file was already moved

    def _create_document(
        self, user: CurrentUser, received: ReceivedFile, page_count: int | None, sketch: bytes | None
    ) -> UploadFileResult:
        new = self._new_version(user, received, page_count, sketch)
        display_name = PurePath(received.original_filename).stem or received.original_filename
        version = self._repo.create_document_with_version(
            document_id=str(uuid.uuid4()),
            display_name=display_name,
            owner_id=user.id,
            version=new,
        )
        if version is None:  # another identical upload won first
            return self._handle_existing(user, self._repo.find_version_by_hash(received.sha256), received)
        self._move_to_queue(received, version)
        logger.info("New document %s (version %s) queued", version.document_id, version.id)
        return self._result(received, "queued", version)

    def _create_version(
        self,
        user: CurrentUser,
        document_id: str,
        received: ReceivedFile,
        page_count: int | None,
        sketch: bytes | None,
    ) -> UploadFileResult:
        new = self._new_version(user, received, page_count, sketch)
        version = self._repo.create_next_version(document_id, new)
        if version is None:  # lost the race to an identical upload
            return self._handle_existing(user, self._repo.find_version_by_hash(received.sha256), received)
        self._move_to_queue(received, version)
        logger.info("New version v%s for document %s (%s)", version.version_no, document_id, version.id)
        return self._result(received, "queued", version)

    def _fingerprint(self, received: ReceivedFile) -> bytes | None:
        return fingerprint(
            extract_text(received.path, received.ext), self._cfg.SIMILARITY_MIN_SHINGLES
        )

    def _find_similar(self, sketch: bytes | None) -> SimilarDocument | None:
        if sketch is None:
            return None
        return most_similar(sketch, self._repo.list_fingerprints(), self._cfg.SIMILARITY_THRESHOLD)

    def _hold_pending(
        self,
        user: CurrentUser,
        received: ReceivedFile,
        page_count: int | None,
        sketch: bytes | None,
        similar: SimilarDocument,
    ) -> UploadFileResult:
        pending = PendingUpload(
            id=str(uuid.uuid4()),
            user_id=user.id,
            original_filename=received.original_filename,
            file_ext=received.ext,
            size_bytes=received.size_bytes,
            content_hash=received.sha256,
            page_count=page_count,
            fingerprint=sketch,
            candidate_document_id=similar.document_id,
            score=similar.score,
        )
        self._repo.create_pending(pending)
        try:
            os.replace(received.path, pending_file_path(self._queue_dir, pending.id, received.ext))
        except OSError:
            self._repo.delete_pending(pending.id)
            raise
        logger.info(
            "Upload %r resembles document %s (score %.3f); waiting for the user's choice.",
            received.original_filename, similar.document_id, similar.score,
        )
        return UploadFileResult(
            filename=received.original_filename,
            status="similar",
            pending_id=pending.id,
            similar_document_id=similar.document_id,
            similar_document_name=similar.display_name,
            similarity=similar.score,
        )

    def _handle_existing(
        self, user: CurrentUser, existing: DocumentVersion | None, received: ReceivedFile
    ) -> UploadFileResult:
        if existing is None:  # very rare: the version was deleted between two queries
            raise ConflictError("The upload collided with another operation. Try again.", retryable=True)
        if existing.stage in RECLAIMABLE_STAGES:
            # Re-upload of a file that previously failed/was cancelled → process it again.
            self._move_to_queue(received, existing)
            version = self._repo.requeue_version(existing.id, user.id)
            logger.info("Reprocessing version %s (%s)", version.id, existing.stage)
            return self._result(received, "queued", version)
        # Already ready or being processed → reuse it, at no cost.
        return self._result(received, "existing", existing)

    def _new_version(
        self,
        user: CurrentUser,
        received: ReceivedFile,
        page_count: int | None,
        sketch: bytes | None = None,
    ) -> NewVersion:
        return NewVersion(
            id=str(uuid.uuid4()),
            content_hash=received.sha256,
            original_filename=received.original_filename,
            file_ext=received.ext,
            size_bytes=received.size_bytes,
            page_count=page_count,
            uploaded_by=user.id,
            pipeline_version=self._cfg.PIPELINE_VERSION,
            fingerprint=sketch,
        )

    def _move_to_queue(self, received: ReceivedFile, version: DocumentVersion) -> None:
        target = queued_file_path(self._queue_dir, version.id, received.ext)
        os.replace(received.path, target)

    @staticmethod
    def _result(received: ReceivedFile, status: str, version: DocumentVersion) -> UploadFileResult:
        return UploadFileResult(
            filename=received.original_filename,
            status=status,  # type: ignore[arg-type]
            document_id=version.document_id,
            version_id=version.id,
            stage=version.stage,
        )
