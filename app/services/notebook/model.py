from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Notebook:
    id: str
    owner_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None = None


@dataclass(frozen=True)
class NotebookSource:
    """One source in a notebook: a Library document + the pinned version."""

    notebook_id: str
    document_id: str
    display_name: str
    document_status: str  # active | archived
    version_id: str  # the pinned version
    version_no: int
    stage: str
    uploaded_at: datetime
    page_count: int | None
    latest_version_id: str | None  # latest ready version in the Library
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
    """A source the chat really uses: checked AND its version is ready."""

    version_id: str
    document_id: str
    display_name: str
    version_no: int
    uploaded_at: datetime
    # The version's document profile (app/services/ingestion/profile.py) as a dict; None when
    # the version was processed before profiles existed or the profile could not be built.
    profile: dict | None = field(default=None, compare=False)
