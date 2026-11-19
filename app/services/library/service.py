"""Use case Library: upload (idempoten), daftar, detail, ganti nama.

Pemrosesan dokumen TIDAK terjadi di sini. Upload hanya menyimpan file ke
folder antrean (``<queue>/<version_id><ext>``) dan mencatat versi berstatus
``queued``; worker (DESIGN_GROUP_B.md §3) yang memprosesnya.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path, PurePath

from fastapi import UploadFile

from app.core.config import AppConfig
from app.core.errors import (
    ArgosError,
    ConflictError,
    NotFoundError,
    PayloadTooLarge,
    PermissionDenied,
    ValidationError,
)
from app.infrastructure.interface.library_repository import BaseLibraryRepository
from app.services.library.model import (
    RECLAIMABLE_STAGES,
    DocumentListItem,
    DocumentVersion,
    NewVersion,
    UploadFileResult,
)
from app.services.library.upload import ReceivedFile, count_pages, receive_upload
from app.services.user.model import CurrentUser

logger = logging.getLogger(__name__)

_MB = 1024 * 1024


def queued_file_path(queue_dir: Path, version_id: str, ext: str) -> Path:
    """Lokasi file asli sebuah versi selama menunggu/diproses worker."""
    return queue_dir / f"{version_id}{ext}"


class LibraryService:
    def __init__(self, repository: BaseLibraryRepository, queue_dir: Path, config: AppConfig) -> None:
        self._repo = repository
        self._queue_dir = queue_dir
        self._cfg = config

    # ── Upload ─────────────────────────────────────────────────────────

    async def upload_documents(
        self, user: CurrentUser, files: list[UploadFile], max_files: int | None = None
    ) -> list[UploadFileResult]:
        """Upload satu batch dokumen baru. Hasil dilaporkan per file.

        ``max_files`` dipakai pemanggil (mis. notebook) untuk membatasi ke sisa slot.
        """
        limit = self._cfg.UPLOAD_MAX_FILES_PER_BATCH
        if max_files is not None:
            limit = min(limit, max_files)
        if not files:
            raise ValidationError("Pilih minimal satu file.", code="NO_FILES")
        if len(files) > limit:
            raise ValidationError(
                f"Maksimal {limit} file per upload.", code="TOO_MANY_FILES"
            )

        results: list[UploadFileResult] = []
        per_file = self._cfg.UPLOAD_MAX_FILE_MB * _MB
        batch_limit = self._cfg.UPLOAD_MAX_BATCH_MB * _MB
        batch_bytes = 0
        batch_error = ValidationError(
            f"Total upload melebihi {self._cfg.UPLOAD_MAX_BATCH_MB} MB.", code="BATCH_TOO_LARGE"
        )

        for file in files:
            filename = PurePath((file.filename or "").replace("\\", "/")).name or "dokumen"
            try:
                self._check_extension(filename)
                cap = min(per_file, batch_limit - batch_bytes)
                if cap <= 0:
                    raise batch_error
                try:
                    received = await receive_upload(file, self._queue_dir, cap)
                except PayloadTooLarge:
                    # Yang terlewati bisa batas batch (sisa kuota < batas per file).
                    if cap < per_file:
                        raise batch_error from None
                    raise
                batch_bytes += received.size_bytes
                results.append(self._register_new_document(user, received))
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
        self, user: CurrentUser, document_id: str, file: UploadFile
    ) -> UploadFileResult:
        document = self._repo.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Dokumen tidak ditemukan.")

        filename = PurePath((file.filename or "").replace("\\", "/")).name or "dokumen"
        self._check_extension(filename)
        received = await receive_upload(file, self._queue_dir, self._cfg.UPLOAD_MAX_FILE_MB * _MB)
        try:
            page_count = self._validate_pages(received)
            existing = self._repo.find_version_by_hash(received.sha256)
            if existing is not None:
                if existing.document_id != document_id:
                    raise ConflictError(
                        "File ini sudah ada di Library sebagai dokumen lain.",
                        code="FILE_BELONGS_TO_OTHER_DOCUMENT",
                        details={"document_id": existing.document_id},
                    )
                return self._handle_existing(user, existing, received)

            new = self._new_version(user, received, page_count)
            version = self._repo.create_next_version(document_id, new)
            if version is None:  # kalah balapan dengan upload identik
                return self._handle_existing(user, self._repo.find_version_by_hash(received.sha256), received)
            self._move_to_queue(received, version)
            logger.info("Versi baru v%s untuk dokumen %s (%s)", version.version_no, document_id, version.id)
            return self._result(received, "queued", version)
        finally:
            received.path.unlink(missing_ok=True)

    # ── Query ──────────────────────────────────────────────────────────

    def list_documents(
        self, query: str | None, uploaded_by: str | None, limit: int, offset: int
    ) -> list[DocumentListItem]:
        return self._repo.list_documents(query, uploaded_by, limit=min(limit, 100), offset=offset)

    def get_document(self, document_id: str) -> tuple[DocumentListItem, list[DocumentVersion]]:
        item = self._repo.get_document_item(document_id)
        if item is None or item.document.status != "active":
            raise NotFoundError("Dokumen tidak ditemukan.")
        return item, self._repo.list_versions(document_id)

    def get_version(self, version_id: str) -> DocumentVersion:
        version = self._repo.get_version(version_id)
        if version is None:
            raise NotFoundError("Versi dokumen tidak ditemukan.")
        return version

    def rename_document(self, user: CurrentUser, document_id: str, display_name: str) -> DocumentListItem:
        document = self._repo.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Dokumen tidak ditemukan.")
        if document.owner_id != user.id and not user.is_admin:
            raise PermissionDenied("Hanya pengunggah yang dapat mengganti nama dokumen.")
        name = " ".join(display_name.split())
        if not name:
            raise ValidationError("Nama dokumen tidak boleh kosong.")
        self._repo.rename_document(document_id, name)
        return self._repo.get_document_item(document_id)

    # ── Internal ───────────────────────────────────────────────────────

    def _check_extension(self, filename: str) -> None:
        ext = PurePath(filename).suffix.lower()
        if ext not in self._cfg.UPLOAD_ALLOWED_EXTENSIONS:
            allowed = ", ".join(e.lstrip(".").upper() for e in self._cfg.UPLOAD_ALLOWED_EXTENSIONS)
            raise ValidationError(f"Format tidak didukung. Gunakan {allowed}.", code="UNSUPPORTED_FILE_TYPE")

    def _validate_pages(self, received: ReceivedFile) -> int | None:
        pages = count_pages(received.path, received.ext)
        if pages is not None and pages > self._cfg.UPLOAD_MAX_PAGES:
            raise ValidationError(
                f"Dokumen {pages} halaman melebihi batas {self._cfg.UPLOAD_MAX_PAGES} halaman.",
                code="TOO_MANY_PAGES",
            )
        return pages

    def _register_new_document(self, user: CurrentUser, received: ReceivedFile) -> UploadFileResult:
        try:
            page_count = self._validate_pages(received)
            existing = self._repo.find_version_by_hash(received.sha256)
            if existing is not None:
                return self._handle_existing(user, existing, received)

            new = self._new_version(user, received, page_count)
            display_name = PurePath(received.original_filename).stem or received.original_filename
            version = self._repo.create_document_with_version(
                document_id=str(uuid.uuid4()),
                display_name=display_name,
                owner_id=user.id,
                version=new,
            )
            if version is None:  # upload identik lain menang lebih dulu
                return self._handle_existing(user, self._repo.find_version_by_hash(received.sha256), received)
            self._move_to_queue(received, version)
            logger.info("Dokumen baru %s (versi %s) masuk antrean", version.document_id, version.id)
            return self._result(received, "queued", version)
        finally:
            received.path.unlink(missing_ok=True)

    def _handle_existing(
        self, user: CurrentUser, existing: DocumentVersion | None, received: ReceivedFile
    ) -> UploadFileResult:
        if existing is None:  # sangat jarang: versi terhapus di antara dua query
            raise ConflictError("Upload bertabrakan dengan proses lain. Coba lagi.", retryable=True)
        if existing.stage in RECLAIMABLE_STAGES:
            # Upload ulang file yang sebelumnya gagal/dibatalkan → proses ulang.
            self._move_to_queue(received, existing)
            version = self._repo.requeue_version(existing.id, user.id)
            logger.info("Versi %s (%s) diproses ulang", version.id, existing.stage)
            return self._result(received, "queued", version)
        # Sudah ready atau sedang diproses → pakai yang ada, tanpa biaya.
        return self._result(received, "existing", existing)

    def _new_version(self, user: CurrentUser, received: ReceivedFile, page_count: int | None) -> NewVersion:
        return NewVersion(
            id=str(uuid.uuid4()),
            content_hash=received.sha256,
            original_filename=received.original_filename,
            file_ext=received.ext,
            size_bytes=received.size_bytes,
            page_count=page_count,
            uploaded_by=user.id,
            pipeline_version=self._cfg.PIPELINE_VERSION,
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
