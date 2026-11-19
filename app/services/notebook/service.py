"""Use case Notebook: ruang kerja pribadi berisi maks. N sumber dari Library.

(DESIGN_GROUP_A.md §6.2–6.5)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import UploadFile

from app.core.config import AppConfig
from app.core.errors import NotFoundError, ValidationError
from app.infrastructure.interface.job_repository import BaseJobRepository
from app.infrastructure.interface.library_repository import BaseLibraryRepository
from app.infrastructure.interface.notebook_repository import (
    BaseNotebookRepository,
    SourceLimitReached,
)
from app.services.library.model import FINAL_STAGES, STAGE_READY, UploadFileResult
from app.services.library.service import LibraryService
from app.services.notebook.model import ActiveSource, Notebook, NotebookSource
from app.services.user.model import CurrentUser

logger = logging.getLogger(__name__)


class NotebookService:
    def __init__(
        self,
        repository: BaseNotebookRepository,
        library_repo: BaseLibraryRepository,
        library_service: LibraryService,
        jobs: BaseJobRepository,
        config: AppConfig,
    ) -> None:
        self._repo = repository
        self._library = library_repo
        self._library_svc = library_service
        self._jobs = jobs
        self._max = config.NOTEBOOK_MAX_SOURCES

    @property
    def max_sources(self) -> int:
        return self._max

    # ── Notebook ───────────────────────────────────────────────────────

    def list(self, user: CurrentUser) -> list[tuple[Notebook, int]]:
        return self._repo.list_for_owner(user.id)

    def create(self, user: CurrentUser, title: str) -> Notebook:
        return self._repo.create(str(uuid.uuid4()), user.id, _clean_title(title))

    def get(self, user: CurrentUser, notebook_id: str) -> Notebook:
        notebook = self._repo.get(notebook_id, user.id)
        if notebook is None:
            raise NotFoundError("Notebook tidak ditemukan.")
        return notebook

    def rename(self, user: CurrentUser, notebook_id: str, title: str) -> Notebook:
        self.get(user, notebook_id)
        self._repo.rename(notebook_id, _clean_title(title))
        return self.get(user, notebook_id)

    def delete(self, user: CurrentUser, notebook_id: str) -> None:
        sources = self.sources(user, notebook_id)
        self._repo.delete(notebook_id)
        for source in sources:
            self._maybe_cancel(user, source)

    # ── Sumber ─────────────────────────────────────────────────────────

    def sources(self, user: CurrentUser, notebook_id: str) -> list[NotebookSource]:
        self.get(user, notebook_id)
        return self._repo.list_sources(notebook_id)

    def add_from_library(
        self, user: CurrentUser, notebook_id: str, document_ids: list[str]
    ) -> list[NotebookSource]:
        self.get(user, notebook_id)
        for document_id in dict.fromkeys(document_ids):  # buang duplikat, jaga urutan
            version_id = self._pinnable_version(document_id)
            self._add(notebook_id, document_id, version_id)
        return self._repo.list_sources(notebook_id)

    async def upload(
        self, user: CurrentUser, notebook_id: str, files: list[UploadFile]
    ) -> tuple[list[UploadFileResult], list[NotebookSource]]:
        """Upload ke Library lalu langsung pasang ke notebook (dibatasi sisa slot)."""
        self.get(user, notebook_id)
        remaining = self._max - len(self._repo.list_sources(notebook_id))
        if remaining <= 0:
            raise ValidationError(
                f"Notebook sudah berisi {self._max} sumber (maksimal).", code="NOTEBOOK_FULL"
            )
        results = await self._library_svc.upload_documents(user, files, max_files=remaining)
        for r in results:
            if r.document_id and r.version_id:
                try:
                    self._add(notebook_id, r.document_id, r.version_id)
                except ValidationError:
                    # Kalah balapan dengan penambahan lain: dokumen tetap ada di Library.
                    logger.info("Notebook %s penuh; %s tidak dipasang.", notebook_id, r.document_id)
        return results, self._repo.list_sources(notebook_id)

    def update_source(
        self,
        user: CurrentUser,
        notebook_id: str,
        document_id: str,
        enabled: bool | None,
        use_latest_version: bool,
    ) -> list[NotebookSource]:
        source = self._source(user, notebook_id, document_id)
        if enabled is not None:
            self._repo.set_enabled(notebook_id, document_id, enabled)
        if use_latest_version:
            if not source.latest_version_id:
                raise ValidationError("Belum ada versi yang siap dipakai.", code="NO_READY_VERSION")
            self._repo.set_version(notebook_id, document_id, source.latest_version_id)
        self._repo.touch(notebook_id)
        return self._repo.list_sources(notebook_id)

    def remove_source(self, user: CurrentUser, notebook_id: str, document_id: str) -> list[NotebookSource]:
        source = self._source(user, notebook_id, document_id)
        self._repo.remove_source(notebook_id, document_id)
        self._repo.touch(notebook_id)
        self._maybe_cancel(user, source)
        return self._repo.list_sources(notebook_id)

    def active_sources(self, user: CurrentUser, notebook_id: str) -> list[ActiveSource]:
        self.get(user, notebook_id)
        return self._repo.active_sources(notebook_id)

    # ── Internal ───────────────────────────────────────────────────────

    def _source(self, user: CurrentUser, notebook_id: str, document_id: str) -> NotebookSource:
        for s in self.sources(user, notebook_id):
            if s.document_id == document_id:
                return s
        raise NotFoundError("Sumber tidak ada di notebook ini.")

    def _add(self, notebook_id: str, document_id: str, version_id: str) -> None:
        try:
            self._repo.add_source(notebook_id, document_id, version_id, self._max)
        except SourceLimitReached:
            raise ValidationError(
                f"Notebook sudah berisi {self._max} sumber (maksimal).", code="NOTEBOOK_FULL"
            ) from None

    def _pinnable_version(self, document_id: str) -> str:
        """Versi ready terbaru; jika belum ada, versi terbaru yang masih diproses."""
        document = self._library.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Dokumen tidak ditemukan di Library.")
        if document.latest_version_id:
            return document.latest_version_id
        for v in self._library.list_versions(document_id):
            if v.stage not in FINAL_STAGES:
                return v.id
        raise ValidationError(
            "Dokumen ini belum berhasil diproses. Upload ulang file-nya.", code="NO_READY_VERSION"
        )

    def _maybe_cancel(self, user: CurrentUser, source: NotebookSource) -> None:
        """Batalkan pemrosesan bila sumber yang dilepas masih diproses, diunggah user ini,
        dan tidak dipakai notebook lain (B §9). Dokumen tetap ada di Library."""
        if source.stage in FINAL_STAGES or source.stage == STAGE_READY:
            return
        version = self._library.get_version(source.version_id)
        if version is None or version.uploaded_by != user.id:
            return
        if self._repo.count_version_pins(source.version_id) > 0:
            return
        self._jobs.request_cancel(source.version_id)
        logger.info("Pemrosesan versi %s dibatalkan (sumber dilepas).", source.version_id)


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned:
        raise ValidationError("Judul notebook tidak boleh kosong.")
    return cleaned[:200]
