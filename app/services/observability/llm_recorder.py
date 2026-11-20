"""Pencatat panggilan AI (DESIGN_GROUP_C.md §7.3).

Setiap provider OpenAI membungkus panggilannya dengan ``recorder.track(...)``::

    with recorder.track("router", model) as call:
        response = await client.ainvoke(...)
        call.usage(input_tokens=..., output_tokens=...)

Aturan:
- Pencatatan **tidak pernah** menggagalkan atau memperlambat panggilan AI.
  ``track`` hanya mengukur waktu dan menaruh catatan di antrean; satu thread
  latar menulisnya ke SQLite secara batch.
- ``request_id``, ``version_id``, dan ``message_id`` diambil dari konteks
  (``request_context`` / ``log_context``), jadi provider tidak perlu tahu.
- Prompt dan isi dokumen tidak pernah dicatat.
- Status panggilan terakhir per ``purpose`` disimpan di memori untuk
  ``/health/ready`` (yang tidak boleh memanggil OpenAI).
- ``collect()`` mengumpulkan catatan selama satu blok (dipakai ChatEngine untuk
  ringkasan token di trace pesan).
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
from app.infrastructure.interface.llm_call_repository import BaseLLMCallRepository
from app.services.observability.model import LLMCall

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
    """Dikembalikan oleh ``track``; provider mengisi pemakaian token bila tersedia."""

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
        """Mulai menulis ke ``repository``. Tanpa ini, catatan hanya ke memori."""
        with self._lock:
            self._repo = repository
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="llm-call-writer", daemon=True
                )
                self._thread.start()

    def close(self, timeout: float = 5.0) -> None:
        """Tulis sisa antrean lalu hentikan thread penulis."""
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is not None:
            self._queue.put(_STOP)
            thread.join(timeout)
        self._repo = None

    def flush(self, timeout: float = 5.0) -> None:
        """Tunggu sampai antrean saat ini tertulis (untuk test & shutdown)."""
        if self._thread is None:
            return
        done = threading.Event()
        self._queue.put(done)
        done.wait(timeout)

    # ── Pencatatan ──────────────────────────────────────────────────

    @contextmanager
    def track(self, purpose: str, model: str) -> Iterator[_CallHandle]:
        handle = _CallHandle()
        start = time.perf_counter()
        try:
            yield handle
        except BaseException as exc:
            # CancelledError (shutdown/timeout chat) juga dicatat sebagai gagal.
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
        """Kumpulkan semua catatan di blok ini (termasuk task & thread turunan)."""
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
            logger.exception("Gagal mencatat panggilan AI (%s).", purpose)

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
            logger.exception("Gagal menulis %d catatan llm_calls.", len(batch))


def usage_from_langchain(message: object) -> tuple[int | None, int | None]:
    """Token dari ``AIMessage.usage_metadata`` LangChain (None bila tidak ada)."""
    meta = getattr(message, "usage_metadata", None) or {}
    return meta.get("input_tokens"), meta.get("output_tokens")


recorder = LLMCallRecorder()
