"""SQLite adapter untuk catatan panggilan AI (tabel ``llm_calls``)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.core.database import Database
from app.infrastructure.interface.llm_call_repository import BaseLLMCallRepository
from app.services.observability.model import LLMCall

# Format yang sama dengan CURRENT_TIMESTAMP SQLite (UTC), agar bisa dibandingkan
# langsung dengan datetime('now', ...).
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ts_out(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime(_TS_FORMAT)


class SQLiteLLMCallRepository(BaseLLMCallRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def insert_many(self, calls: Sequence[LLMCall]) -> None:
        if not calls:
            return
        with self._db.get_connection() as conn:
            conn.executemany(
                """INSERT INTO llm_calls
                   (ts, purpose, model, input_tokens, output_tokens, latency_ms,
                    status, error_code, request_id, version_id, message_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        _ts_out(c.ts), c.purpose, c.model, c.input_tokens, c.output_tokens,
                        c.latency_ms, c.status, c.error_code, c.request_id, c.version_id,
                        c.message_id,
                    )
                    for c in calls
                ],
            )

    def purge_older_than(self, days: int) -> int:
        with self._db.get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM llm_calls WHERE ts < datetime('now', ?)", (f"-{int(days)} days",)
            )
            return cur.rowcount

    def list_for_message(self, message_id: int) -> list[LLMCall]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM llm_calls WHERE message_id = ? ORDER BY id", (message_id,)
            ).fetchall()
        return [
            LLMCall(
                purpose=r["purpose"],
                model=r["model"],
                latency_ms=r["latency_ms"],
                status=r["status"],
                error_code=r["error_code"],
                input_tokens=r["input_tokens"],
                output_tokens=r["output_tokens"],
                request_id=r["request_id"],
                version_id=r["version_id"],
                message_id=r["message_id"],
                ts=datetime.strptime(r["ts"], _TS_FORMAT).replace(tzinfo=UTC),
            )
            for r in rows
        ]
