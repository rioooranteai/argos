from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from app.services.library.model import UploadFileResult


@dataclass(frozen=True)
class Notebook:
    id: str
    owner_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class NotebookSource:
    """Satu sumber di notebook: dokumen Library + versi yang di-pin."""

    notebook_id: str
    document_id: str
    display_name: str
    document_status: str  # active | archived
    version_id: str  # versi yang di-pin
    version_no: int
    stage: str
    uploaded_at: datetime
    page_count: int | None
    latest_version_id: str | None  # versi ready terbaru di Library
    latest_version_no: int | None
    enabled: bool
    added_at: datetime
    progress_done: int = 0
    progress_total: int = 0
    error: str | None = None
    vision_failed: int = 0

    @property
    def is_ready(self) -> bool:
        return self.stage == "ready"

    @property
    def update_available(self) -> bool:
        return (
            self.latest_version_id is not None
            and self.latest_version_id != self.version_id
            and (self.latest_version_no or 0) > self.version_no
        )


@dataclass(frozen=True)
class ActiveSource:
    """Sumber yang benar-benar dipakai chat: dicentang DAN versinya ready."""

    version_id: str
    document_id: str
    display_name: str
    version_no: int
    uploaded_at: datetime


# ── API schemas ─────────────────────────────────────────────────────────


class NotebookOut(BaseModel):
    id: str
    title: str
    source_count: int
    created_at: datetime
    updated_at: datetime


class NotebookSourceOut(BaseModel):
    document_id: str
    display_name: str
    version_id: str
    version_no: int
    stage: str
    uploaded_at: datetime
    page_count: int | None
    enabled: bool
    archived: bool
    update_available: bool
    latest_version_no: int | None
    progress_done: int
    progress_total: int
    error: str | None
    warnings: list[str]

    @classmethod
    def from_source(cls, s: NotebookSource) -> NotebookSourceOut:
        return cls(
            document_id=s.document_id,
            display_name=s.display_name,
            version_id=s.version_id,
            version_no=s.version_no,
            stage=s.stage,
            uploaded_at=s.uploaded_at,
            page_count=s.page_count,
            enabled=s.enabled,
            archived=s.document_status == "archived",
            update_available=s.update_available,
            latest_version_no=s.latest_version_no,
            progress_done=s.progress_done,
            progress_total=s.progress_total,
            error=s.error,
            warnings=[f"{s.vision_failed} gambar tidak terbaca"] if s.vision_failed else [],
        )


class NotebookDetailOut(NotebookOut):
    max_sources: int
    sources: list[NotebookSourceOut]


class CreateNotebookRequest(BaseModel):
    title: str = Field(default="Notebook baru", min_length=1, max_length=200)


class RenameNotebookRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class AddSourcesRequest(BaseModel):
    document_ids: list[str] = Field(..., min_length=1, max_length=10)


class UpdateSourceRequest(BaseModel):
    enabled: bool | None = None
    use_latest_version: bool = False


class SourceUploadOut(BaseModel):
    """Hasil upload langsung ke notebook: hasil per file + daftar sumber terbaru."""

    results: list[UploadFileResult]
    sources: list[NotebookSourceOut]
