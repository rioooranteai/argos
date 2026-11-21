from __future__ import annotations

from app.core.database import Database
from app.services.library.model import DocumentVersion
from app.services.library.ports import BaseJobRepository
from app.tools.storage.sqlite.library import (
    SQLiteLibraryRepository,
)

# Every timestamp uses SQLite's CURRENT_TIMESTAMP format (UTC, 'YYYY-MM-DD HH:MM:SS'),
# so comparing strings = comparing times.
_RUNNING = "('parsing', 'vision', 'indexing', 'extracting')"


class SQLiteJobRepository(BaseJobRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def claim_next(self, lease_minutes: int) -> DocumentVersion | None:
        claimable = f"""
            (stage = 'queued' AND (next_retry_at IS NULL OR next_retry_at <= CURRENT_TIMESTAMP))
            OR (stage IN {_RUNNING} AND locked_until < CURRENT_TIMESTAMP)
        """
        with self._db.get_connection() as conn:
            row = conn.execute(
                f"""
                UPDATE document_versions SET
                    stage = 'parsing',
                    attempts = attempts + 1,
                    locked_until = datetime('now', ?),
                    started_at = CURRENT_TIMESTAMP,
                    progress_done = 0, progress_total = 0
                WHERE id = (
                    SELECT id FROM document_versions
                    WHERE {claimable}
                    ORDER BY uploaded_at, id
                    LIMIT 1
                ) AND ({claimable})
                RETURNING *
                """,
                (f"+{lease_minutes} minutes",),
            ).fetchone()
        return SQLiteLibraryRepository._to_version(row) if row else None

    def recover_orphans(self) -> int:
        with self._db.get_connection() as conn:
            cur = conn.execute(
                f"""
                UPDATE document_versions
                SET stage = 'queued', locked_until = NULL, attempts = MAX(attempts - 1, 0)
                WHERE stage IN {_RUNNING}
                """
            )
            return cur.rowcount

    def heartbeat(
        self, version_id: str, stage: str, done: int, total: int, lease_minutes: int
    ) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                UPDATE document_versions SET
                    stage = ?, progress_done = ?, progress_total = ?,
                    locked_until = datetime('now', ?)
                WHERE id = ?
                """,
                (stage, done, total, f"+{lease_minutes} minutes", version_id),
            )

    def is_cancel_requested(self, version_id: str) -> bool:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM document_versions WHERE id = ?", (version_id,)
            ).fetchone()
        # A version that was already deleted also counts as cancelled.
        return row is None or bool(row[0])

    def request_cancel(self, version_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE document_versions SET cancel_requested = 1 "
                "WHERE id = ? AND stage NOT IN ('ready', 'failed', 'cancelled')",
                (version_id,),
            )
            # A job that has not started can be cancelled right away.
            conn.execute(
                "UPDATE document_versions SET stage = 'cancelled', finished_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND stage = 'queued'",
                (version_id,),
            )

    def add_vision_failed(self, version_id: str, count: int) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE document_versions SET vision_failed = vision_failed + ? WHERE id = ?",
                (count, version_id),
            )

    def schedule_retry(self, version_id: str, delay_minutes: int, error: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                UPDATE document_versions SET
                    stage = 'queued', locked_until = NULL, error = ?,
                    next_retry_at = datetime('now', ?)
                WHERE id = ?
                """,
                (error, f"+{delay_minutes} minutes", version_id),
            )

    def release(self, version_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                UPDATE document_versions SET
                    stage = 'queued', locked_until = NULL, attempts = MAX(attempts - 1, 0)
                WHERE id = ? AND stage IN """ + _RUNNING,
                (version_id,),
            )

    def mark_failed(self, version_id: str, error: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                UPDATE document_versions SET
                    stage = 'failed', error = ?, locked_until = NULL,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error, version_id),
            )

    def mark_cancelled(self, version_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                UPDATE document_versions SET
                    stage = 'cancelled', locked_until = NULL, finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (version_id,),
            )
