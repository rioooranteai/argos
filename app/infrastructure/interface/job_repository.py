"""Processing queue port: `document_versions` rows act as jobs."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.library.model import DocumentVersion


class BaseJobRepository(ABC):
    @abstractmethod
    def claim_next(self, lease_minutes: int) -> DocumentVersion | None:
        """Atomically take one job: a `queued` one that is due, or a running job
        whose lease expired. Increments `attempts` and sets a lease."""

    @abstractmethod
    def recover_orphans(self) -> int:
        """On start (single-process app): jobs still 'running' must be orphans of the
        previous process → put them back to `queued`. Returns how many."""

    @abstractmethod
    def heartbeat(
        self, version_id: str, stage: str, done: int, total: int, lease_minutes: int
    ) -> None:
        """Update the stage & progress and extend the lease."""

    @abstractmethod
    def is_cancel_requested(self, version_id: str) -> bool: ...

    @abstractmethod
    def request_cancel(self, version_id: str) -> None: ...

    @abstractmethod
    def add_vision_failed(self, version_id: str, count: int) -> None: ...

    @abstractmethod
    def schedule_retry(self, version_id: str, delay_minutes: int, error: str) -> None:
        """Put back in the queue to retry after a delay."""

    @abstractmethod
    def release(self, version_id: str) -> None:
        """Release a job interrupted by shutdown, without counting the attempt."""

    @abstractmethod
    def mark_failed(self, version_id: str, error: str) -> None: ...

    @abstractmethod
    def mark_cancelled(self, version_id: str) -> None: ...
