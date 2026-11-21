"""Context & error classification for document processing jobs (DESIGN_GROUP_B.md §3.2)."""
from __future__ import annotations

import asyncio
import time

import httpx
import openai

from app.core.errors import ArgosError
from app.core.observability.logs import context as log_context
from app.services.library.model import DocumentVersion
from app.services.library.ports import BaseJobRepository
from app.tools.document_parser.base import DocumentLoadError, ParserTimeout, ParserUnavailable


class JobCancelled(Exception):
    """Cancellation was requested (source/document deleted) or the version no longer exists."""


class PermanentJobError(Exception):
    """An error that retrying will not fix. Its message is safe to show the user."""


class TransientJobError(Exception):
    """A temporary error; the job may be retried. Its message is safe to show the user."""


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
    """Return (retryable, message_for_user). Technical details are only for the log."""
    chain = list(_causes(exc))
    for e in chain:
        if isinstance(e, PermanentJobError):
            return False, str(e)
        if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return False, "The AI service is misconfigured. Contact the admin."
        if isinstance(e, (openai.BadRequestError, openai.UnprocessableEntityError)):
            # 400/422: the request was rejected — repeating the same request does not help.
            return False, "The AI service rejected this document's content."
        if isinstance(e, DocumentLoadError):
            return False, "The document cannot be read. Make sure the file is not broken."
        if isinstance(e, ArgosError) and not e.retryable:
            return False, e.message
    for e in chain:
        if isinstance(e, ParserTimeout) or isinstance(e, (TimeoutError, asyncio.TimeoutError)):
            return True, "Processing took too long and was stopped; it will be retried."
        if isinstance(e, TransientJobError):
            return True, str(e)
        if isinstance(e, _TRANSIENT_TYPES):
            return True, "The AI service is having problems; it will be retried."
        if isinstance(e, ArgosError) and e.retryable:
            return True, e.message
    # Unknown error: retried (limited by DOC_MAX_ATTEMPTS), details in the log.
    return True, "Something went wrong while processing the document."


class JobContext:
    """Used by the pipeline to report stage/progress & check for cancellation.

    Every report also extends the lease (heartbeat). Progress reports are
    limited to at most one DB write per second.
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
        log_context.bind_request(stage=stage)  # this job's context dict (worker: scoped)
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
