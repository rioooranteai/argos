from __future__ import annotations

import sqlite3
from datetime import datetime

from app.core.database import Database
from app.services.notebook.ports import (
    BaseNotebookRepository,
    SourceLimitReached,
)
from app.services.notebook.model import ActiveSource, Notebook, NotebookSource


def _ts(value) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace(" ", "T"))


_SOURCES_SQL = """
    SELECT ns.notebook_id, ns.document_id, ns.version_id, ns.enabled, ns.added_at,
           d.display_name, d.status AS document_status, d.latest_version_id,
           v.version_no, v.stage, v.uploaded_at, v.page_count,
           v.progress_done, v.progress_total, v.error AS version_error, v.vision_failed,
           lv.version_no AS latest_version_no
    FROM notebook_sources ns
    JOIN library_documents d ON d.id = ns.document_id
    JOIN document_versions v ON v.id = ns.version_id
    LEFT JOIN document_versions lv ON lv.id = d.latest_version_id
    WHERE ns.notebook_id = ?
    ORDER BY ns.added_at, ns.rowid
"""


class SQLiteNotebookRepository(BaseNotebookRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    # ── Notebook ───────────────────────────────────────────────────────

    def create(self, notebook_id: str, owner_id: str, title: str) -> Notebook:
        with self._db.get_connection() as conn:
            conn.execute(
                "INSERT INTO notebooks (id, owner_id, title) VALUES (?, ?, ?)",
                (notebook_id, owner_id, title),
            )
            row = conn.execute("SELECT * FROM notebooks WHERE id = ?", (notebook_id,)).fetchone()
        return self._to_notebook(row)

    def get(self, notebook_id: str, owner_id: str) -> Notebook | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM notebooks WHERE id = ? AND owner_id = ?", (notebook_id, owner_id)
            ).fetchone()
        return self._to_notebook(row) if row else None

    def list_for_owner(self, owner_id: str) -> list[tuple[Notebook, int]]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT n.*, (SELECT COUNT(*) FROM notebook_sources s WHERE s.notebook_id = n.id)
                       AS source_count
                FROM notebooks n WHERE n.owner_id = ?
                ORDER BY n.updated_at DESC, n.id
                """,
                (owner_id,),
            ).fetchall()
        return [(self._to_notebook(r), r["source_count"]) for r in rows]

    def rename(self, notebook_id: str, title: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE notebooks SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, notebook_id),
            )

    def delete(self, notebook_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute("DELETE FROM notebooks WHERE id = ?", (notebook_id,))

    def touch(self, notebook_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE notebooks SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (notebook_id,)
            )

    def mark_opened(self, notebook_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                # Millisecond precision: opening two notebooks in the same second still keeps the order.
                "UPDATE notebooks SET last_opened_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
                (notebook_id,),
            )

    # ── Sources ────────────────────────────────────────────────────────

    def list_sources(self, notebook_id: str) -> list[NotebookSource]:
        with self._db.get_connection() as conn:
            rows = conn.execute(_SOURCES_SQL, (notebook_id,)).fetchall()
        return [self._to_source(r) for r in rows]

    def add_source(self, notebook_id: str, document_id: str, version_id: str, max_sources: int) -> bool:
        with self._db.get_connection() as conn:
            # Take the write lock first: two concurrent adds cannot both get past the limit.
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM notebook_sources WHERE notebook_id = ? AND document_id = ?",
                (notebook_id, document_id),
            ).fetchone()
            if exists:
                return False
            count = conn.execute(
                "SELECT COUNT(*) FROM notebook_sources WHERE notebook_id = ?", (notebook_id,)
            ).fetchone()[0]
            if count >= max_sources:
                raise SourceLimitReached()
            conn.execute(
                "INSERT INTO notebook_sources (notebook_id, document_id, version_id) VALUES (?, ?, ?)",
                (notebook_id, document_id, version_id),
            )
            conn.execute(
                "UPDATE notebooks SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (notebook_id,)
            )
        return True

    def set_enabled(self, notebook_id: str, document_id: str, enabled: bool) -> bool:
        with self._db.get_connection() as conn:
            cur = conn.execute(
                "UPDATE notebook_sources SET enabled = ? WHERE notebook_id = ? AND document_id = ?",
                (int(enabled), notebook_id, document_id),
            )
            return cur.rowcount > 0

    def set_version(self, notebook_id: str, document_id: str, version_id: str) -> bool:
        with self._db.get_connection() as conn:
            cur = conn.execute(
                "UPDATE notebook_sources SET version_id = ? WHERE notebook_id = ? AND document_id = ?",
                (version_id, notebook_id, document_id),
            )
            return cur.rowcount > 0

    def remove_source(self, notebook_id: str, document_id: str) -> bool:
        with self._db.get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM notebook_sources WHERE notebook_id = ? AND document_id = ?",
                (notebook_id, document_id),
            )
            return cur.rowcount > 0

    def count_version_pins(self, version_id: str) -> int:
        with self._db.get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM notebook_sources WHERE version_id = ?", (version_id,)
            ).fetchone()[0]

    def active_sources(self, notebook_id: str) -> list[ActiveSource]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT v.id AS version_id, d.id AS document_id, d.display_name,
                       v.version_no, v.uploaded_at
                FROM notebook_sources ns
                JOIN document_versions v ON v.id = ns.version_id
                JOIN library_documents d ON d.id = ns.document_id
                WHERE ns.notebook_id = ? AND ns.enabled = 1 AND v.stage = 'ready'
                ORDER BY ns.added_at, ns.rowid
                """,
                (notebook_id,),
            ).fetchall()
        return [
            ActiveSource(
                version_id=r["version_id"],
                document_id=r["document_id"],
                display_name=r["display_name"],
                version_no=r["version_no"],
                uploaded_at=_ts(r["uploaded_at"]),
            )
            for r in rows
        ]

    # ── Mapper ─────────────────────────────────────────────────────────

    @staticmethod
    def _to_notebook(row: sqlite3.Row) -> Notebook:
        return Notebook(
            id=row["id"],
            owner_id=row["owner_id"],
            title=row["title"],
            created_at=_ts(row["created_at"]),
            updated_at=_ts(row["updated_at"]),
            last_opened_at=_ts(row["last_opened_at"]),
        )

    @staticmethod
    def _to_source(row: sqlite3.Row) -> NotebookSource:
        return NotebookSource(
            notebook_id=row["notebook_id"],
            document_id=row["document_id"],
            display_name=row["display_name"],
            document_status=row["document_status"],
            version_id=row["version_id"],
            version_no=row["version_no"],
            stage=row["stage"],
            uploaded_at=_ts(row["uploaded_at"]),
            page_count=row["page_count"],
            latest_version_id=row["latest_version_id"],
            latest_version_no=row["latest_version_no"],
            enabled=bool(row["enabled"]),
            added_at=_ts(row["added_at"]),
            progress_done=row["progress_done"],
            progress_total=row["progress_total"],
            error=row["version_error"],
            vision_failed=row["vision_failed"],
        )
