"""Konteks & klasifikasi error untuk job pemrosesan dokumen (DESIGN_GROUP_B.md §3.2)."""
from __future__ import annotations

import asyncio
import time

import httpx
import openai

from app.core import log_context
from app.core.errors import ArgosError
from app.infrastructure.interface.job_repository import BaseJobRepository
from app.services.ingestion.exceptions import DocumentLoadError
from app.services.ingestion.providers.loaders.docling_process import (
    ParserTimeout,
    ParserUnavailable,
)
from app.services.library.model import DocumentVersion


class JobCancelled(Exception):
    """Pembatalan diminta (sumber/dokumen dihapus) atau versi sudah tidak ada."""


class PermanentJobError(Exception):
    """Error yang tidak akan sembuh dengan dicoba lagi. Pesannya aman untuk user."""


class TransientJobError(Exception):
    """Error sementara; job boleh dicoba lagi. Pesannya aman untuk user."""


_TRANSIENT_TYPES: tuple[type[BaseException], ...] = (
    TransientJobError,
    ParserUnavailable,
    TimeoutError,
    asyncio.TimeoutError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
    httpx.TimeoutException,
    httpx.TransportError,
)


def _causes(exc: BaseException):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def classify(exc: BaseException) -> tuple[bool, str]:
    """Return (boleh_dicoba_lagi, pesan_untuk_user). Detail teknis hanya untuk log."""
    chain = list(_causes(exc))
    for e in chain:
        if isinstance(e, PermanentJobError):
            return False, str(e)
        if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return False, "Konfigurasi layanan AI bermasalah. Hubungi admin."
        if isinstance(e, (openai.BadRequestError, openai.UnprocessableEntityError)):
            # 400/422: request ditolak — mengulang request yang sama tidak membantu.
            return False, "Layanan AI menolak isi dokumen ini."
        if isinstance(e, DocumentLoadError):
            return False, "Dokumen tidak bisa dibaca. Pastikan file tidak rusak."
        if isinstance(e, ArgosError) and not e.retryable:
            return False, e.message
    for e in chain:
        if isinstance(e, ParserTimeout) or isinstance(e, (TimeoutError, asyncio.TimeoutError)):
            return True, "Pemrosesan terlalu lama dan dihentikan; akan dicoba lagi."
        if isinstance(e, TransientJobError):
            return True, str(e)
        if isinstance(e, _TRANSIENT_TYPES):
            return True, "Layanan AI sedang bermasalah; akan dicoba lagi."
        if isinstance(e, ArgosError) and e.retryable:
            return True, e.message
    # Error tak dikenal: dicoba lagi (dibatasi DOC_MAX_ATTEMPTS), detail di log.
    return True, "Terjadi kesalahan saat memproses dokumen."


class JobContext:
    """Dipakai pipeline untuk melaporkan tahap/progres & memeriksa pembatalan.

    Setiap laporan sekaligus memperpanjang lease (heartbeat). Laporan progres
    dibatasi maksimal satu tulis DB per detik.
    """

    def __init__(self, version: DocumentVersion, jobs: BaseJobRepository, lease_minutes: int) -> None:
        self.version = version
        self._jobs = jobs
        self._lease = lease_minutes
        self._stage = "parsing"
        self._done = 0
        self._total = 0
        self._last_write = 0.0

    async def stage(self, stage: str, total: int = 0) -> None:
        self._stage, self._done, self._total = stage, 0, total
        log_context.bind_request(stage=stage)  # dict konteks milik job ini (worker: scoped)
        await self._write()

    async def progress(self, done: int) -> None:
        self._done = done
        if done >= self._total or time.monotonic() - self._last_write >= 1.0:
            await self._write()

    async def check_cancelled(self) -> None:
        if await asyncio.to_thread(self._jobs.is_cancel_requested, self.version.id):
            raise JobCancelled()

    async def add_vision_failed(self, count: int) -> None:
        await asyncio.to_thread(self._jobs.add_vision_failed, self.version.id, count)

    async def _write(self) -> None:
        self._last_write = time.monotonic()
        await asyncio.to_thread(
            self._jobs.heartbeat, self.version.id, self._stage, self._done, self._total, self._lease
        )
