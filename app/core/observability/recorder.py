"""AI call recorder (DESIGN_GROUP_C.md §7.3).

Every OpenAI provider wraps its calls with ``recorder.track(...)``::

    with recorder.track("router", model) as call:
        response = await client.ainvoke(...)
        call.usage(input_tokens=..., output_tokens=...)

Rules:
- Recording **never** fails or slows down an AI call.
  ``track`` only measures time and puts a record in a queue; one background
  thread writes the records to SQLite in batches.
- ``request_id``, ``version_id`` and ``message_id`` come from the context
  (``request_context`` / ``log_context``), so providers do not need to know them.
- Prompts and document content are never recorded.
- The status of the latest call per ``purpose`` is kept in memory for
  ``/health/ready`` (which must not call OpenAI).
- ``collect()`` gathers the records made during a block (used by ChatEngine for
  the token summary in the message trace).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core import log_context
from app.core.llm_errors import classify_llm_error
from app.core.request_context import get_request_id
from app.core.observability.ports import BaseLLMCallRepository
from app.core.observability.model import LLMCall

logger = logging.getLogger(__name__)

_BATCH_MAX = 200
_STOP = object()

_sink: ContextVar[list[LLMCall] | None] = ContextVar("llm_call_sink", default=None)


@dataclass
class LastCall:
    ts: datetime
    status: str
    error_code: str | None


class _CallHandle:
    """Returned by ``track``; the provider fills in token usage when available."""

    def __init__(self) -> None:
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None

    def usage(self, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class LLMCallRecorder:
    def __init__(self) -> None:
        self._repo: BaseLLMCallRepository | None = None
        self._queue: queue.SimpleQueue[object] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last: dict[str, LastCall] = {}

    # ── Siklus hidup ────────────────────────────────────────────────

    def attach(self, repository: BaseLLMCallRepository) -> None:
        """Start writing to ``repository``. Without this, records only go to memory."""
        with self._lock:
            self._repo = repository
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="llm-call-writer", daemon=True
                )
                self._thread.start()

    def close(self, timeout: float = 5.0) -> None:
        """Write the rest of the queue, then stop the writer thread."""
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is not None:
            self._queue.put(_STOP)
            thread.join(timeout)
        self._repo = None

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until the current queue is written (for tests & shutdown)."""
        if self._thread is None:
            return
        done = threading.Event()
        self._queue.put(done)
        done.wait(timeout)

    # ── Recording ───────────────────────────────────────────────────

    @contextmanager
    def track(self, purpose: str, model: str) -> Iterator[_CallHandle]:
        handle = _CallHandle()
        start = time.perf_counter()
        try:
            yield handle
        except BaseException as exc:
            # CancelledError (shutdown/chat timeout) is also recorded as a failure.
            self._emit(purpose, model, start, handle, "error", classify_llm_error(exc))
            raise
        else:
            self._emit(purpose, model, start, handle, "ok", None)

    def record(self, call: LLMCall) -> None:
        self._last[call.purpose] = LastCall(call.ts, call.status, call.error_code)
        sink = _sink.get()
        if sink is not None:
            sink.append(call)
        if self._repo is not None:
            self._queue.put(call)

    @contextmanager
    def collect(self) -> Iterator[list[LLMCall]]:
        """Collect every record made in this block (including child tasks & threads)."""
        calls: list[LLMCall] = []
        token = _sink.set(calls)
        try:
            yield calls
        finally:
            _sink.reset(token)

    def last_calls(self) -> dict[str, LastCall]:
        return dict(self._last)

    # ── Internal ────────────────────────────────────────────────────

    def _emit(
        self,
        purpose: str,
        model: str,
        start: float,
        handle: _CallHandle,
        status: str,
        error_code: str | None,
    ) -> None:
        try:
            message_id = log_context.get("message_id")
            self.record(
                LLMCall(
                    purpose=purpose,
                    model=model,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    status=status,  # type: ignore[arg-type]
                    error_code=error_code,
                    input_tokens=handle.input_tokens,
                    output_tokens=handle.output_tokens,
                    request_id=get_request_id(),
                    version_id=log_context.get("version_id"),
                    message_id=str(message_id) if message_id is not None else None,
                    ts=datetime.now(UTC),
                )
            )
        except Exception:
            logger.exception("Failed to record an AI call (%s).", purpose)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            batch: list[LLMCall] = []
            waiters: list[threading.Event] = []
            stop = False
            while True:
                if item is _STOP:
                    stop = True
                elif isinstance(item, threading.Event):
                    waiters.append(item)
                elif isinstance(item, LLMCall):
                    batch.append(item)
                if stop or len(batch) >= _BATCH_MAX:
                    break
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
            self._write(batch)
            for waiter in waiters:
                waiter.set()
            if stop:
                return

    def _write(self, batch: list[LLMCall]) -> None:
        repo = self._repo
        if not batch or repo is None:
            return
        try:
            repo.insert_many(batch)
        except Exception:
            logger.exception("Failed to write %d llm_calls records.", len(batch))


def usage_from_langchain(message: object) -> tuple[int | None, int | None]:
    """Tokens from LangChain's ``AIMessage.usage_metadata`` (None when absent)."""
    meta = getattr(message, "usage_metadata", None) or {}
    return meta.get("input_tokens"), meta.get("output_tokens")


recorder = LLMCallRecorder()
