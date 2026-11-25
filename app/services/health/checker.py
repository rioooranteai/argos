"""System readiness checks for ``/health/ready``.

Status per check: ``ok`` / ``degraded`` / ``fail`` (``unknown`` for OpenAI when it has
not been called yet). The overall status is ``fail`` (HTTP 503) only when some check is
``fail``. No check calls OpenAI: the OpenAI status comes from the latest real
call (``LLMCallRecorder``). Exception messages only go to the log.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.database import Database
from app.core.observability.ai_calls.recorder import LLMCallRecorder

logger = logging.getLogger(__name__)

# Failed OpenAI calls older than this no longer make the status degraded.
OPENAI_FAILURE_WINDOW_SECONDS = 300


class _Worker(Protocol):
    is_running: bool
    active_jobs: int

    def seconds_since_tick(self) -> float | None: ...


class _Docling(Protocol):
    is_alive: bool


class _VectorStore(Protocol):
    def heartbeat(self) -> None: ...


@dataclass
class HealthChecker:
    database: Database
    vector_store: _VectorStore
    worker: _Worker
    docling: _Docling
    recorder: LLMCallRecorder
    missing_config: Callable[[], list[str]]
    worker_poll_seconds: float
    # "enabled (otlp → …)" / "disabled (…)" from core/observability/telemetry/setup.status(). Informational:
    # telemetry being off never makes the app unready.
    telemetry: Callable[[], str] = lambda: "disabled (not configured)"

    def ready(self) -> dict[str, Any]:
        checks = {
            "database": self._guard("database", self._database),
            "vector_store": self._guard("vector_store", self._vector_store),
            "worker": self._guard("worker", self._worker),
            "docling": self._guard("docling", self._docling),
            "config": self._guard("config", self._config),
            "openai": self._guard("openai", self._openai),
            "telemetry": self._guard("telemetry", self._telemetry),
        }
        statuses = {c["status"] for c in checks.values()}
        overall = "fail" if "fail" in statuses else "degraded" if "degraded" in statuses else "ok"
        return {
            "status": overall,
            "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "checks": checks,
        }

    # ── Cek ────────────────────────────────────────────────────────

    def _guard(self, name: str, check: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return check()
        except Exception:
            logger.exception("Health check '%s' failed.", name)
            return {"status": "fail"}

    def _database(self) -> dict[str, Any]:
        with self.database.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    def _vector_store(self) -> dict[str, Any]:
        self.vector_store.heartbeat()
        return {"status": "ok"}

    def _worker(self) -> dict[str, Any]:
        if not self.worker.is_running:
            return {"status": "fail", "reason": "not_running"}
        since = self.worker.seconds_since_tick()
        active = self.worker.active_jobs
        # While every slot is processing a job, the loop does not spin.
        stalled = active == 0 and (since is None or since > 3 * self.worker_poll_seconds + 5)
        out: dict[str, Any] = {"status": "fail" if stalled else "ok", "active_jobs": active}
        if since is not None:
            out["seconds_since_tick"] = round(since, 1)
        if stalled:
            out["reason"] = "stalled"
        return out

    def _docling(self) -> dict[str, Any]:
        # The subprocess is recreated when needed, so dead ≠ failed.
        if self.docling.is_alive:
            return {"status": "ok"}
        return {"status": "degraded", "reason": "not_started"}

    def _config(self) -> dict[str, Any]:
        missing = self.missing_config()
        if missing:
            return {"status": "fail", "missing": missing}  # field names only, no values
        return {"status": "ok"}

    def _telemetry(self) -> dict[str, Any]:
        # Never calls Langfuse: only reports how telemetry was configured at startup.
        return {"status": "ok", "detail": self.telemetry()}

    def _openai(self) -> dict[str, Any]:
        last = self.recorder.last_calls()
        if not last:
            return {"status": "unknown", "reason": "no_calls_yet"}
        now = datetime.now(UTC)
        purposes: dict[str, Any] = {}
        recent_failure = False
        for purpose, call in sorted(last.items()):
            age = (now - call.ts).total_seconds()
            purposes[purpose] = {"status": call.status, "age_s": int(age)}
            if call.error_code:
                purposes[purpose]["error_code"] = call.error_code
            if call.status == "error" and age <= OPENAI_FAILURE_WINDOW_SECONDS:
                recent_failure = True
        return {"status": "degraded" if recent_failure else "ok", "purposes": purposes}
