"""Notebook use cases: a private workspace with at most N sources from the Library.
"""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from app.core.config import AppConfig
from app.core.errors import NotFoundError, ValidationError
from app.services.library.model import FINAL_STAGES, STAGE_READY, IncomingFile, UploadFileResult
from app.services.library.ports import BaseJobRepository, BaseLibraryRepository
from app.services.library.service import LibraryService
from app.services.notebook.model import ActiveSource, Notebook, NotebookSource
from app.services.notebook.ports import (
    BaseNotebookRepository,
    SourceLimitReached,
)
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
            raise NotFoundError("Notebook not found.")
        return notebook

    def open(self, user: CurrentUser, notebook_id: str) -> Notebook:
        """Like `get`, and also records this notebook as the last opened one."""
        notebook = self.get(user, notebook_id)
        self._repo.mark_opened(notebook_id)
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
            self._library_svc.purge_if_unused(source.document_id)

    # ── Sources ────────────────────────────────────────────────────────

    def sources(self, user: CurrentUser, notebook_id: str) -> list[NotebookSource]:
        self.get(user, notebook_id)
        return self._repo.list_sources(notebook_id)

    def add_from_library(
        self, user: CurrentUser, notebook_id: str, document_ids: list[str]
    ) -> list[NotebookSource]:
        self.get(user, notebook_id)
        for document_id in dict.fromkeys(document_ids):  # drop duplicates, keep the order
            version_id = self._pinnable_version(document_id)
            self._add(notebook_id, document_id, version_id)
        return self._repo.list_sources(notebook_id)

    async def upload(
        self, user: CurrentUser, notebook_id: str, files: list[IncomingFile]
    ) -> tuple[list[UploadFileResult], list[NotebookSource]]:
        """Upload to the Library and add to the notebook right away (limited to the free slots)."""
        self.get(user, notebook_id)
        remaining = self._max - len(self._repo.list_sources(notebook_id))
        if remaining <= 0:
            raise ValidationError(
                f"The notebook already has {self._max} sources (the maximum).", code="NOTEBOOK_FULL"
            )
        results = await self._library_svc.upload_documents(user, files, max_files=remaining)
        for r in results:
            if r.document_id and r.version_id:
                try:
                    self._add(notebook_id, r.document_id, r.version_id)
                except ValidationError:
                    # Lost the race to another add: the document stays in the Library.
                    logger.info("Notebook %s is full; %s was not added.", notebook_id, r.document_id)
        return results, self._repo.list_sources(notebook_id)

    async def resolve_pending(
        self,
        user: CurrentUser,
        notebook_id: str,
        pending_id: str,
        action: Literal["new_version", "separate"],
    ) -> tuple[UploadFileResult, list[NotebookSource]]:
        """Resolve an upload that resembles a Library document, then add the result to the notebook.

        If the document is already in the notebook (the "new version" choice), the old pin is kept;
        the "new version available" badge appears once the new version is ready.
        """
        self.get(user, notebook_id)
        result = await self._library_svc.resolve_pending(user, pending_id, action)
        if result.document_id and result.version_id:
            try:
                self._add(notebook_id, result.document_id, result.version_id)
            except ValidationError:
                logger.info("Notebook %s is full; %s was not added.", notebook_id, result.document_id)
        return result, self._repo.list_sources(notebook_id)

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
                raise ValidationError("No version is ready to use yet.", code="NO_READY_VERSION")
            self._repo.set_version(notebook_id, document_id, source.latest_version_id)
        self._repo.touch(notebook_id)
        return self._repo.list_sources(notebook_id)

    def remove_source(self, user: CurrentUser, notebook_id: str, document_id: str) -> list[NotebookSource]:
        source = self._source(user, notebook_id, document_id)
        self._repo.remove_source(notebook_id, document_id)
        self._repo.touch(notebook_id)
        self._maybe_cancel(user, source)
        self._library_svc.purge_if_unused(document_id)
        return self._repo.list_sources(notebook_id)

    def active_sources(self, user: CurrentUser, notebook_id: str) -> list[ActiveSource]:
        self.get(user, notebook_id)
        return self._repo.active_sources(notebook_id)

    # ── Internal ───────────────────────────────────────────────────────

    def _source(self, user: CurrentUser, notebook_id: str, document_id: str) -> NotebookSource:
        for s in self.sources(user, notebook_id):
            if s.document_id == document_id:
                return s
        raise NotFoundError("This source is not in this notebook.")

    def _add(self, notebook_id: str, document_id: str, version_id: str) -> None:
        try:
            self._repo.add_source(notebook_id, document_id, version_id, self._max)
        except SourceLimitReached:
            raise ValidationError(
                f"The notebook already has {self._max} sources (the maximum).", code="NOTEBOOK_FULL"
            ) from None

    def _pinnable_version(self, document_id: str) -> str:
        """The latest ready version; if there is none, the latest one still being processed."""
        document = self._library.get_document(document_id)
        if document is None or document.status != "active":
            raise NotFoundError("Document not found in the Library.")
        if document.latest_version_id:
            return document.latest_version_id
        for v in self._library.list_versions(document_id):
            if v.stage not in FINAL_STAGES:
                return v.id
        raise ValidationError(
            "This document has not been processed successfully. Upload the file again.", code="NO_READY_VERSION"
        )

    def _maybe_cancel(self, user: CurrentUser, source: NotebookSource) -> None:
        """Cancel processing when the removed source is still being processed, was uploaded
        by this user, and no other notebook uses it. The document stays in the Library."""
        if source.stage in FINAL_STAGES or source.stage == STAGE_READY:
            return
        version = self._library.get_version(source.version_id)
        if version is None or version.uploaded_by != user.id:
            return
        if self._repo.count_version_pins(source.version_id) > 0:
            return
        self._jobs.request_cancel(source.version_id)
        logger.info("Processing of version %s cancelled (source removed).", source.version_id)


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned:
        raise ValidationError("The notebook title cannot be empty.")
    return cleaned[:200]
