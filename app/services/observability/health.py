"""Pemeriksaan kesiapan sistem untuk ``/health/ready`` (DESIGN_GROUP_C.md §6).

Status per cek: ``ok`` / ``degraded`` / ``fail`` (``unknown`` untuk OpenAI yang
belum pernah dipanggil). Keseluruhan ``fail`` (HTTP 503) hanya bila ada cek yang
``fail``. Tidak ada cek yang memanggil OpenAI: status OpenAI diambil dari
panggilan nyata terakhir (``LLMCallRecorder``). Pesan exception hanya ke log.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.database import Database
from app.services.observability.llm_recorder import LLMCallRecorder

logger = logging.getLogger(__name__)

# Panggilan OpenAI gagal yang lebih tua dari ini tidak lagi membuat status degraded.
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

    def ready(self) -> dict[str, Any]:
        checks = {
            "database": self._guard("database", self._database),
            "vector_store": self._guard("vector_store", self._vector_store),
            "worker": self._guard("worker", self._worker),
            "docling": self._guard("docling", self._docling),
            "config": self._guard("config", self._config),
            "openai": self._guard("openai", self._openai),
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
            logger.exception("Health check '%s' gagal.", name)
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
        # Saat semua slot memproses job, loop memang tidak berputar.
        stalled = active == 0 and (since is None or since > 3 * self.worker_poll_seconds + 5)
        out: dict[str, Any] = {"status": "fail" if stalled else "ok", "active_jobs": active}
        if since is not None:
            out["seconds_since_tick"] = round(since, 1)
        if stalled:
            out["reason"] = "stalled"
        return out

    def _docling(self) -> dict[str, Any]:
        # Subprocess dibuat ulang saat dibutuhkan, jadi mati ≠ gagal.
        if self.docling.is_alive:
            return {"status": "ok"}
        return {"status": "degraded", "reason": "not_started"}

    def _config(self) -> dict[str, Any]:
        missing = self.missing_config()
        if missing:
            return {"status": "fail", "missing": missing}  # nama field saja, tanpa nilai
        return {"status": "ok"}

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
