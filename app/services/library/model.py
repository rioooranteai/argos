from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Tahap pemrosesan versi (DESIGN_GROUP_B.md §3.1)
STAGE_QUEUED = "queued"
STAGE_READY = "ready"
STAGE_FAILED = "failed"
STAGE_CANCELLED = "cancelled"
FINAL_STAGES = frozenset({STAGE_READY, STAGE_FAILED, STAGE_CANCELLED})
# Versi dengan tahap ini boleh diambil alih oleh upload ulang file yang sama.
RECLAIMABLE_STAGES = frozenset({STAGE_FAILED, STAGE_CANCELLED})


@dataclass(frozen=True)
class LibraryDocument:
    id: str
    display_name: str
    owner_id: str
    latest_version_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentVersion:
    id: str
    document_id: str
    version_no: int
    content_hash: str
    original_filename: str
    file_ext: str
    size_bytes: int
    page_count: int | None
    uploaded_by: str
    uploaded_at: datetime
    stage: str
    progress_done: int
    progress_total: int
    attempts: int
    vision_failed: int
    pipeline_version: str
    error: str | None
    finished_at: datetime | None

    @property
    def is_final(self) -> bool:
        return self.stage in FINAL_STAGES


@dataclass(frozen=True)
class NewVersion:
    """Data versi baru yang sudah diterima & divalidasi, siap disimpan."""

    id: str
    content_hash: str
    original_filename: str
    file_ext: str
    size_bytes: int
    page_count: int | None
    uploaded_by: str
    pipeline_version: str


@dataclass(frozen=True)
class DocumentListItem:
    document: LibraryDocument
    latest_version: DocumentVersion | None
    owner_name: str | None
    version_count: int


# ── API schemas ─────────────────────────────────────────────────────────


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

    @classmethod
    def from_version(cls, v: DocumentVersion) -> VersionOut:
        warnings = []
        if v.vision_failed:
            warnings.append(f"{v.vision_failed} gambar tidak terbaca")
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


class UploadFileResult(BaseModel):
    """Hasil per file dalam satu batch upload."""

    filename: str
    status: Literal["queued", "existing", "rejected"]
    document_id: str | None = None
    version_id: str | None = None
    stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class UploadBatchOut(BaseModel):
    results: list[UploadFileResult]


class RenameDocumentRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)
