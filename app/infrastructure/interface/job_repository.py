"""Port antrean pemrosesan: baris `document_versions` berfungsi sebagai job."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.library.model import DocumentVersion


class BaseJobRepository(ABC):
    @abstractmethod
    def claim_next(self, lease_minutes: int) -> DocumentVersion | None:
        """Ambil satu job secara atomik: `queued` yang sudah waktunya, atau job
        berjalan yang lease-nya habis. Menaikkan `attempts` dan memasang lease."""

    @abstractmethod
    def recover_orphans(self) -> int:
        """Saat start (app 1 proses): job yang masih 'berjalan' pasti yatim dari
        proses sebelumnya → kembalikan ke `queued`. Return jumlahnya."""

    @abstractmethod
    def heartbeat(
        self, version_id: str, stage: str, done: int, total: int, lease_minutes: int
    ) -> None:
        """Perbarui tahap & progres sekaligus memperpanjang lease."""

    @abstractmethod
    def is_cancel_requested(self, version_id: str) -> bool: ...

    @abstractmethod
    def request_cancel(self, version_id: str) -> None: ...

    @abstractmethod
    def add_vision_failed(self, version_id: str, count: int) -> None: ...

    @abstractmethod
    def schedule_retry(self, version_id: str, delay_minutes: int, error: str) -> None:
        """Kembalikan ke antrean untuk dicoba lagi setelah jeda."""

    @abstractmethod
    def release(self, version_id: str) -> None:
        """Lepas job yang terputus karena shutdown, tanpa menghitung percobaan."""

    @abstractmethod
    def mark_failed(self, version_id: str, error: str) -> None: ...

    @abstractmethod
    def mark_cancelled(self, version_id: str) -> None: ...
