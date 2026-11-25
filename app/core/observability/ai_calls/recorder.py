"""AI call recorder.

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

import asyncio
import json
import logging
import queue
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.llm_errors import classify_llm_error
from app.core.observability.ai_calls.model import LLMCall
from app.core.observability.ai_calls.ports import BaseLLMCallRepository
from app.core.observability.logs import context as log_context
from app.core.observability.logs.request_id import get_request_id
from app.core.observability.telemetry import pricing, spans

logger = logging.getLogger(__name__)

_BATCH_MAX = 200
_STOP = object()

_sink: ContextVar[list[LLMCall] | None] = ContextVar("llm_call_sink", default=None)


def _report_usage(span: spans.Span, purpose: str, model: str, handle: _CallHandle) -> None:
    """Token usage and cost on the generation span (Langfuse usage_details / cost_details)."""
    usage: dict[str, int] = {}
    if handle.input_tokens is not None:
        usage["input"] = handle.input_tokens
        span.set_attribute("gen_ai.usage.input_tokens", handle.input_tokens)
    if handle.output_tokens is not None:
        usage["output"] = handle.output_tokens
        span.set_attribute("gen_ai.usage.output_tokens", handle.output_tokens)
    if usage:
        usage["total"] = sum(usage.values())
        span.set_attribute("langfuse.observation.usage_details", json.dumps(usage))
    if purpose == "stt":
        cost = pricing.audio_cost(model, handle.audio_seconds)
    elif purpose == "tts":
        cost = pricing.character_cost(model, handle.characters)
    else:
        cost = pricing.token_cost(model, handle.input_tokens, handle.output_tokens)
    if cost is not None:
        span.set_attribute("langfuse.observation.cost_details", json.dumps(cost))
        span.set_attribute("gen_ai.usage.cost", cost["total"])


@dataclass
class LastCall:
    ts: datetime
    status: str
    error_code: str | None


class _CallHandle:
    """Returned by ``track``. The provider reports what it knows about the call:
    token usage, the content sent/received (for the trace), audio length or characters."""

    def __init__(self, span: spans.Span) -> None:
        self._span = span
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.audio_seconds: float | None = None
        self.characters: int | None = None

    def usage(self, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def content(self, input: object = None, output: object = None) -> None:
        """What went in and came out (prompt, answer…). Shown in the trace when content
        capture is on; never stored in llm_calls."""
        spans.set_input(self._span, input)
        spans.set_output(self._span, output)

    def units(self, audio_seconds: float | None = None, characters: int | None = None) -> None:
        """Non-token usage, for speech pricing."""
        self.audio_seconds = audio_seconds
        self.characters = characters


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

    # ── Recording ───────────────────────────────────────────────────

    @contextmanager
    def track(self, purpose: str, model: str) -> Iterator[_CallHandle]:
        """Record one AI call in llm_calls and as a trace span."""
        kind = spans.EMBEDDING if purpose == "embedding" else spans.GENERATION
        with spans.span(
            purpose, kind,
            **{"langfuse.observation.model.name": model, "gen_ai.request.model": model,
               "gen_ai.operation.name": "embeddings" if purpose == "embedding" else "chat"},
        ) as span:
            handle = _CallHandle(span)
            start = time.perf_counter()
            try:
                yield handle
            except BaseException as exc:
                # CancelledError (shutdown/chat timeout) is also recorded as a failure.
                code = classify_llm_error(exc)
                self._emit(purpose, model, start, handle, "error", code)
                if not isinstance(exc, asyncio.CancelledError):
                    spans.set_error(span, code, exc=exc)
                raise
            else:
                self._emit(purpose, model, start, handle, "ok", None)
            finally:
                _report_usage(span, purpose, model, handle)

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
