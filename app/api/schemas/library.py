"""HTTP request/response schemas for library."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.services.library.model import DocumentListItem, DocumentVersion, UploadFileResult


class VersionOut(BaseModel):
    id: str
    document_id: str
    version_no: int
    original_filename: str
    size_bytes: int
    page_count: int | None
    uploaded_by: str
    uploaded_at: datetime
    stage: str
    progress_done: int
    progress_total: int
    attempts: int
    error: str | None
    warnings: list[str] = Field(default_factory=list)
    reuse_stats: dict[str, int] | None = None

    @classmethod
    def from_version(cls, v: DocumentVersion) -> VersionOut:
        warnings = []
        if v.vision_failed:
            warnings.append(f"{v.vision_failed} image(s) could not be read")
        return cls(
            id=v.id,
            document_id=v.document_id,
            version_no=v.version_no,
            original_filename=v.original_filename,
            size_bytes=v.size_bytes,
            page_count=v.page_count,
            uploaded_by=v.uploaded_by,
            uploaded_at=v.uploaded_at,
            stage=v.stage,
            progress_done=v.progress_done,
            progress_total=v.progress_total,
            attempts=v.attempts,
            error=v.error,
            warnings=warnings,
            reuse_stats=v.reuse_stats,
        )


class DocumentOut(BaseModel):
    id: str
    display_name: str
    owner_id: str
    owner_name: str | None
    status: str
    latest_version: VersionOut | None
    version_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_item(cls, item: DocumentListItem) -> DocumentOut:
        d = item.document
        return cls(
            id=d.id,
            display_name=d.display_name,
            owner_id=d.owner_id,
            owner_name=item.owner_name,
            status=d.status,
            latest_version=VersionOut.from_version(item.latest_version) if item.latest_version else None,
            version_count=item.version_count,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )


class DocumentDetailOut(DocumentOut):
    versions: list[VersionOut]


class UploadBatchOut(BaseModel):
    results: list[UploadFileResult]


class ResolvePendingRequest(BaseModel):
    action: Literal["new_version", "separate"]


class RenameDocumentRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)
