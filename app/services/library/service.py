"""Use case Library: upload (idempoten), daftar, detail, ganti nama.

Pemrosesan dokumen TIDAK terjadi di sini. Upload hanya menyimpan file ke
folder antrean (``<queue>/<version_id><ext>``) dan mencatat versi berstatus
``queued``; worker (DESIGN_GROUP_B.md §3) yang memprosesnya.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from typing import Literal, Protocol
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
from app.infrastructure.interface.job_repository import BaseJobRepository
from app.infrastructure.interface.user_repository import BaseUserRepository
from app.services.library.model import (
    FINAL_STAGES,
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


class _VectorDeleter(Protocol):
    def delete_version(self, version_id: str) -> None: ...


def queued_file_path(queue_dir: Path, version_id: str, ext: str) -> Path:
    """Lokasi file asli sebuah versi selama menunggu/diproses worker."""
    return queue_dir / f"{version_id}{ext}"


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

    # ── Hapus / arsip (tahap 2, DESIGN_GROUP_A.md §6.6–6.7) ──────────

    def delete_document(self, user: CurrentUser, document_id: str) -> Literal["deleted", "archived"]:
        document = self._repo.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Dokumen tidak ditemukan.")
        self._check_can_manage(user, document.owner_id)

        # Notebook milik pemilik sendiri dilepas; notebook orang lain tidak disentuh.
        self._repo.detach_from_owner_notebooks(document_id, document.owner_id)
        if self._repo.count_notebook_uses(document_id) > 0:
            self._repo.archive_document(document_id)
            logger.info("Dokumen %s diarsipkan (masih dipakai notebook lain).", document_id)
            return "archived"

        self._purge(document_id)
        logger.info("Dokumen %s dihapus permanen.", document_id)
        return "deleted"

    def purge_if_unused(self, document_id: str) -> bool:
        """Hapus permanen dokumen ARSIP yang sudah tidak dipakai notebook mana pun."""
        document = self._repo.get_document(document_id)
        if document is None or document.status != "archived":
            return False
        if self._repo.count_notebook_uses(document_id) > 0:
            return False
        self._purge(document_id)
        logger.info("Dokumen arsip %s dihapus permanen (tidak dipakai lagi).", document_id)
        return True

    def delete_version(self, user: CurrentUser, document_id: str, version_id: str) -> None:
        document = self._repo.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Dokumen tidak ditemukan.")
        self._check_can_manage(user, document.owner_id)

        versions = self._repo.list_versions(document_id)
        version = next((v for v in versions if v.id == version_id), None)
        if version is None:
            raise NotFoundError("Versi dokumen tidak ditemukan.")
        if len(versions) == 1:
            raise ConflictError(
                "Ini satu-satunya versi. Hapus dokumennya jika tidak dipakai lagi.",
                code="ONLY_VERSION",
            )
        pins = self._repo.count_version_pins(version_id)
        if pins:
            raise ConflictError(
                f"Versi {version.version_no} masih dipakai di {pins} notebook. "
                "Minta pemakainya beralih ke versi lain dulu.",
                code="VERSION_IN_USE",
                details={"notebooks": pins},
            )

        if version.stage not in FINAL_STAGES and self._jobs is not None:
            self._jobs.request_cancel(version_id)
        try:
            self._repo.delete_version(document_id, version_id)
        except sqlite3.IntegrityError:
            # Ada notebook yang mem-pin versi ini di antara pengecekan dan penghapusan.
            raise ConflictError(
                f"Versi {version.version_no} baru saja dipakai di notebook.", code="VERSION_IN_USE"
            ) from None
        self._remove_version_data(version)
        logger.info("Versi %s (v%s) dokumen %s dihapus.", version_id, version.version_no, document_id)

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
                "Dokumen baru saja dipakai di notebook lain. Coba lagi.", code="DOCUMENT_IN_USE"
            ) from None
        # Database dulu, baru vektor & file: vektor yatim tidak pernah terbaca chat
        # (versinya sudah tidak ada), sedangkan kebalikannya merusak versi yang masih ada.
        for v in versions:
            self._remove_version_data(v)

    def _remove_version_data(self, version: DocumentVersion) -> None:
        if self._vectors is not None:
            try:
                self._vectors.delete_version(version.id)
            except Exception:
                logger.exception("Vektor versi %s gagal dihapus (tidak terlihat oleh chat).", version.id)
        queued_file_path(self._queue_dir, version.id, version.file_ext).unlink(missing_ok=True)

    def _check_can_manage(self, user: CurrentUser, owner_id: str) -> None:
        if owner_id == user.id:
            return
        if user.is_admin and self._users is not None:
            owner = self._users.get(owner_id)
            if owner is None or not owner.is_active:
                return
        raise PermissionDenied(
            "Hanya pengunggah dokumen yang bisa menghapusnya.", code="NOT_DOCUMENT_OWNER"
        )

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
