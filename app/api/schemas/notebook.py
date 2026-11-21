"""HTTP request/response schemas for notebook (DESIGN_GROUP_E.md §3.7)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.library.model import UploadFileResult
from app.services.notebook.model import NotebookSource


class NotebookOut(BaseModel):
    id: str
    title: str
    source_count: int
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None = None  # to pick the default notebook (D8)


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
            warnings=[f"{s.vision_failed} image(s) could not be read"] if s.vision_failed else [],
        )


class NotebookDetailOut(NotebookOut):
    max_sources: int
    sources: list[NotebookSourceOut]


class CreateNotebookRequest(BaseModel):
    title: str = Field(default="New notebook", min_length=1, max_length=200)


class RenameNotebookRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class AddSourcesRequest(BaseModel):
    document_ids: list[str] = Field(..., min_length=1, max_length=10)


class UpdateSourceRequest(BaseModel):
    enabled: bool | None = None
    use_latest_version: bool = False


class SourceUploadOut(BaseModel):
    """Result of uploading straight to a notebook: per-file results + the updated source list."""

    results: list[UploadFileResult]
    sources: list[NotebookSourceOut]
