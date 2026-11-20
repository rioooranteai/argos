"""Worker antrean dokumen in-process (DESIGN_GROUP_B.md §3, §9).

- `DOC_WORKERS` loop asyncio mengambil job dari tabel `document_versions`.
- Setiap job dibatasi `DOC_TOTAL_TIMEOUT`.
- Error sementara → dicoba lagi dengan jeda 1/5/15 menit, maks. `DOC_MAX_ATTEMPTS`.
- Saat start, job yatim dari proses sebelumnya dikembalikan ke antrean.
- Saat shutdown, job yang terputus dilepas tanpa dihitung sebagai percobaan.

App WAJIB berjalan satu proses (`uvicorn --workers 1`).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core import log_context
from app.core.config import AppConfig
from app.engines.document_engine.jobs import JobCancelled, JobContext, classify
from app.infrastructure.interface.job_repository import BaseJobRepository
from app.services.library.model import DocumentVersion

logger = logging.getLogger(__name__)

ProcessFn = Callable[[DocumentVersion, JobContext], Awaitable[None]]
CleanupFn = Callable[[str], Awaitable[None]]
PathFn = Callable[[DocumentVersion], Path]


class DocumentWorker:
    def __init__(
        self,
        jobs: BaseJobRepository,
        process: ProcessFn,
        cleanup: CleanupFn,
        source_path: PathFn,
        config: AppConfig,
    ) -> None:
        self._jobs = jobs
        self._process = process
        self._cleanup = cleanup
        self._source_path = source_path
        self._cfg = config
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    @property
    def is_running(self) -> bool:
        return any(not t.done() for t in self._tasks)

    async def start(self) -> None:
        recovered = await asyncio.to_thread(self._jobs.recover_orphans)
        if recovered:
            logger.info("%d job yatim dari proses sebelumnya dikembalikan ke antrean.", recovered)
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._loop(i), name=f"doc-worker-{i}")
            for i in range(self._cfg.DOC_WORKERS)
        ]
        logger.info("Worker dokumen berjalan (%d slot).", self._cfg.DOC_WORKERS)

    async def stop(self) -> None:
        self._stopping.set()
        if not self._tasks:
            return
        _, pending = await asyncio.wait(self._tasks, timeout=self._cfg.WORKER_SHUTDOWN_GRACE)
        for task in pending:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("Worker dokumen berhenti.")

    async def run_once(self) -> bool:
        """Ambil & proses satu job jika ada. Return True jika ada job diproses (untuk test)."""
        job = await asyncio.to_thread(self._jobs.claim_next, self._cfg.VERSION_LEASE_MINUTES)
        if job is None:
            return False
        await self._run_job(job)
        return True

    async def _loop(self, slot: int) -> None:
        while not self._stopping.is_set():
            try:
                worked = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker slot %d: error tak terduga di loop.", slot)
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self._stopping.wait(), self._cfg.WORKER_POLL_SECONDS)
                except TimeoutError:
                    pass

    async def _run_job(self, job: DocumentVersion) -> None:
        # Semua log & catatan llm_calls selama job ini membawa version_id (+ stage).
        with log_context.scoped(version_id=job.id, stage="queued"):
            await self._run_job_in_context(job)

    async def _run_job_in_context(self, job: DocumentVersion) -> None:
        ctx = JobContext(job, self._jobs, self._cfg.VERSION_LEASE_MINUTES)
        logger.info("Memproses versi %s (percobaan %d).", job.id, job.attempts)
        try:
            await asyncio.wait_for(self._process(job, ctx), timeout=self._cfg.DOC_TOTAL_TIMEOUT)
        except asyncio.CancelledError:
            # Shutdown: lepas job; sisa data dibersihkan saat job diambil lagi.
            await asyncio.shield(asyncio.to_thread(self._jobs.release, job.id))
            logger.info("Versi %s dilepas karena shutdown.", job.id)
            raise
        except JobCancelled:
            await self._safe_cleanup(job.id)
            await asyncio.to_thread(self._jobs.mark_cancelled, job.id)
            self._remove_source(job)
            logger.info("Versi %s dibatalkan.", job.id)
        except Exception as exc:
            retryable, message = classify(exc)
            await self._safe_cleanup(job.id)
            if retryable and job.attempts < self._cfg.DOC_MAX_ATTEMPTS:
                backoff = self._cfg.DOC_RETRY_BACKOFF_MINUTES
                delay = backoff[min(job.attempts, len(backoff)) - 1]
                await asyncio.to_thread(self._jobs.schedule_retry, job.id, delay, message)
                logger.warning(
                    "Versi %s gagal (percobaan %d), dicoba lagi dalam %d menit.",
                    job.id, job.attempts, delay, exc_info=exc,
                )
            else:
                await asyncio.to_thread(self._jobs.mark_failed, job.id, message)
                self._remove_source(job)
                logger.error("Versi %s gagal permanen: %s", job.id, message, exc_info=exc)
        else:
            self._remove_source(job)

    async def _safe_cleanup(self, version_id: str) -> None:
        try:
            await self._cleanup(version_id)
        except Exception:
            # Data yatim tetap tak terlihat (versi tidak ready) dan dibersihkan
            # lagi saat versi ini diproses ulang.
            logger.exception("Pembersihan data versi %s gagal.", version_id)

    def _remove_source(self, job: DocumentVersion) -> None:
        try:
            self._source_path(job).unlink(missing_ok=True)
        except OSError:
            logger.warning("File antrean versi %s tidak bisa dihapus.", job.id, exc_info=True)
