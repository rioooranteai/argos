"""In-process document queue worker.

- `DOC_WORKERS` asyncio loops take jobs from the `document_versions` table.
- Every job is limited by `DOC_TOTAL_TIMEOUT`.
- Temporary errors → retried after 1/5/15 minutes, at most `DOC_MAX_ATTEMPTS`.
- On start, orphan jobs from the previous process go back to the queue.
- On shutdown, interrupted jobs are released without counting as an attempt.

The app MUST run as a single process (`uvicorn --workers 1`).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.config import AppConfig
from app.core.observability.logs import context as log_context
from app.core.observability.telemetry import spans
from app.core.observability.telemetry.context import bind_trace, trace_attributes, trace_scope
from app.engines.document_engine.jobs import JobCancelled, JobContext, classify
from app.services.library.model import DocumentVersion
from app.services.library.ports import BaseJobRepository

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
        # For /health/ready.
        self._last_tick: float | None = None  # time.monotonic() of the last loop iteration
        self._active_jobs = 0

    @property
    def is_running(self) -> bool:
        return any(not t.done() for t in self._tasks)

    @property
    def active_jobs(self) -> int:
        return self._active_jobs

    def seconds_since_tick(self) -> float | None:
        """Seconds since any slot last checked the queue (None = never)."""
        return None if self._last_tick is None else time.monotonic() - self._last_tick

    async def start(self) -> None:
        recovered = await asyncio.to_thread(self._jobs.recover_orphans)
        if recovered:
            logger.info("%d orphan job(s) from the previous process returned to the queue.", recovered)
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._loop(i), name=f"doc-worker-{i}")
            for i in range(self._cfg.DOC_WORKERS)
        ]
        logger.info("Document worker running (%d slots).", self._cfg.DOC_WORKERS)

    async def stop(self) -> None:
        self._stopping.set()
        if not self._tasks:
            return
        _, pending = await asyncio.wait(self._tasks, timeout=self._cfg.WORKER_SHUTDOWN_GRACE)
        for task in pending:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("Document worker stopped.")

    async def run_once(self) -> bool:
        """Take & process one job if there is one. Return True if a job was processed (for tests)."""
        job = await asyncio.to_thread(self._jobs.claim_next, self._cfg.VERSION_LEASE_MINUTES)
        if job is None:
            return False
        await self._run_job(job)
        return True

    async def _loop(self, slot: int) -> None:
        while not self._stopping.is_set():
            self._last_tick = time.monotonic()
            try:
                worked = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker slot %d: unexpected error in the loop.", slot)
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self._stopping.wait(), self._cfg.WORKER_POLL_SECONDS)
                except TimeoutError:
                    pass

    async def _run_job(self, job: DocumentVersion) -> None:
        # Every log line & llm_calls record during this job carries version_id (+ stage).
        self._active_jobs += 1
        try:
            with log_context.scoped(version_id=job.id, stage="queued", user_id=job.uploaded_by):
                await self._run_traced(job)
        finally:
            self._active_jobs -= 1

    async def _run_traced(self, job: DocumentVersion) -> None:
        """One trace per processing attempt: document.process → parsing / vision / indexing /
        extracting / publish. The user is the uploader."""
        with trace_scope(), spans.span("document.process", spans.CHAIN) as root:
            spans.set_attributes(root, **{"langfuse.trace.name": "document.process"})
            bind_trace(
                tags=["retry"] if job.attempts > 1 else [],
                document_id=job.document_id, attempt=job.attempts, version_no=job.version_no,
                file=job.original_filename, pages=job.page_count, size_bytes=job.size_bytes,
            )
            spans.set_input(root, {"file": job.original_filename, "attempt": job.attempts})
            try:
                outcome = await self._run_job_in_context(job)
                spans.set_output(root, outcome)
                if outcome["result"] == "cancelled":
                    bind_trace(tags=["cancelled"])
                    spans.set_warning(root, "CANCELLED")
                elif outcome["result"] != "ready":
                    bind_trace(tags=[outcome["result"]])
                    spans.set_error(root, outcome["code"], outcome["message"])
            finally:
                spans.set_attributes(root, **trace_attributes())

    async def _run_job_in_context(self, job: DocumentVersion) -> dict:
        """Process the job and settle its state; returns the outcome (for the trace)."""
        ctx = JobContext(job, self._jobs, self._cfg.VERSION_LEASE_MINUTES)
        logger.info("Processing version %s (attempt %d).", job.id, job.attempts)
        try:
            await asyncio.wait_for(self._process(job, ctx), timeout=self._cfg.DOC_TOTAL_TIMEOUT)
        except asyncio.CancelledError:
            # Shutdown: release the job; leftover data is cleaned up when it is taken again.
            await asyncio.shield(asyncio.to_thread(self._jobs.release, job.id))
            logger.info("Version %s released because of shutdown.", job.id)
            raise
        except JobCancelled:
            await self._safe_cleanup(job.id)
            await asyncio.to_thread(self._jobs.mark_cancelled, job.id)
            self._remove_source(job)
            logger.info("Version %s cancelled.", job.id)
            return {"result": "cancelled"}
        except Exception as exc:
            retryable, message = classify(exc)
            await self._safe_cleanup(job.id)
            if retryable and job.attempts < self._cfg.DOC_MAX_ATTEMPTS:
                backoff = self._cfg.DOC_RETRY_BACKOFF_MINUTES
                delay = backoff[min(job.attempts, len(backoff)) - 1]
                await asyncio.to_thread(self._jobs.schedule_retry, job.id, delay, message)
                logger.warning(
                    "Version %s failed (attempt %d), retrying in %d minutes.",
                    job.id, job.attempts, delay, exc_info=exc,
                )
                return {"result": "retry_scheduled", "code": _error_code(exc), "message": message,
                        "will_retry_in_minutes": delay}
            else:
                await asyncio.to_thread(self._jobs.mark_failed, job.id, message)
                self._remove_source(job)
                logger.error("Version %s failed permanently: %s", job.id, message, exc_info=exc)
                return {"result": "failed", "code": _error_code(exc), "message": message}
        self._remove_source(job)
        return {"result": "ready"}

    async def _safe_cleanup(self, version_id: str) -> None:
        try:
            await self._cleanup(version_id)
        except Exception:
            # Orphan data stays invisible (the version is not ready) and is cleaned
            # up again when this version is reprocessed.
            logger.exception("Cleaning up the data of version %s failed.", version_id)

    def _remove_source(self, job: DocumentVersion) -> None:
        try:
            self._source_path(job).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete the queue file of version %s.", job.id, exc_info=True)


def _error_code(exc: BaseException) -> str:
    """Stable code for the trace: the ArgosError/SQL code when there is one, else the type."""
    return getattr(exc, "code", None) or type(exc).__name__
