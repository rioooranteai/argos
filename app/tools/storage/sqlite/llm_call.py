"""SQLite adapter for AI call records (the ``llm_calls`` table)."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.core.database import Database
from app.core.observability.ports import BaseLLMCallRepository
from app.core.observability.model import LLMCall

# Same format as SQLite's CURRENT_TIMESTAMP (UTC), so it can be compared
# directly with datetime('now', ...).
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
            # Take the write lock first, so MAX(seq) and the INSERT are in the same transaction.
            conn.execute("BEGIN IMMEDIATE")
            next_seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM llm_calls").fetchone()[0]
            conn.executemany(
                """INSERT INTO llm_calls
                   (id, seq, ts, purpose, model, input_tokens, output_tokens, latency_ms,
                    status, error_code, request_id, version_id, message_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        str(uuid.uuid4()), next_seq + i, _ts_out(c.ts), c.purpose, c.model,
                        c.input_tokens, c.output_tokens, c.latency_ms, c.status, c.error_code,
                        c.request_id, c.version_id, c.message_id,
                    )
                    for i, c in enumerate(calls)
                ],
            )

    def purge_older_than(self, days: int) -> int:
        with self._db.get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM llm_calls WHERE ts < datetime('now', ?)", (f"-{int(days)} days",)
            )
            return cur.rowcount

    def list_for_message(self, message_id: str) -> list[LLMCall]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM llm_calls WHERE message_id = ? ORDER BY seq", (message_id,)
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
