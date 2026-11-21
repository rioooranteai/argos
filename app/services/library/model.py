from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel


class IncomingFile(Protocol):
    """An uploaded file as the services see it. FastAPI's ``UploadFile`` fits this shape,
    so services do not depend on the web framework (DESIGN_GROUP_E.md §3.7)."""

    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


# Version processing stages (DESIGN_GROUP_B.md §3.1)
STAGE_QUEUED = "queued"
STAGE_READY = "ready"
STAGE_FAILED = "failed"
STAGE_CANCELLED = "cancelled"
FINAL_STAGES = frozenset({STAGE_READY, STAGE_FAILED, STAGE_CANCELLED})
# A version in one of these stages may be taken over by a re-upload of the same file.
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
    # {chunks, chunks_reused, units, units_cached, images, images_cached}; None before ready
    reuse_stats: dict[str, int] | None = None

    @property
    def is_final(self) -> bool:
        return self.stage in FINAL_STAGES


@dataclass(frozen=True)
class NewVersion:
    """A new version that has been received & validated, ready to store."""

    id: str
    content_hash: str
    original_filename: str
    file_ext: str
    size_bytes: int
    page_count: int | None
    uploaded_by: str
    pipeline_version: str
    fingerprint: bytes | None = None


@dataclass(frozen=True)
class PendingUpload:
    """An upload that resembles a Library document and waits for the user's choice (A §6.3)."""

    id: str
    user_id: str
    original_filename: str
    file_ext: str
    size_bytes: int
    content_hash: str
    page_count: int | None
    fingerprint: bytes | None
    candidate_document_id: str
    score: float
    created_at: datetime | None = None


@dataclass(frozen=True)
class DocumentListItem:
    document: LibraryDocument
    latest_version: DocumentVersion | None
    owner_name: str | None
    version_count: int


class UploadFileResult(BaseModel):
    """Result per file in one upload batch."""

    filename: str
    status: Literal["queued", "existing", "rejected", "similar"]
    document_id: str | None = None
    version_id: str | None = None
    stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    # status "similar": the file is kept temporarily, waiting for POST .../pending/{id}/resolve
    pending_id: str | None = None
    similar_document_id: str | None = None
    similar_document_name: str | None = None
    similarity: float | None = None
