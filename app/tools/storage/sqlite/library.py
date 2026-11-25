from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from app.core.database import Database
from app.services.library.model import (
    STAGE_QUEUED,
    DocumentListItem,
    DocumentVersion,
    LibraryDocument,
    NewVersion,
    PendingUpload,
)
from app.services.library.ports import BaseLibraryRepository


def _ts(value) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace(" ", "T"))


_INSERT_VERSION = """
    INSERT INTO document_versions (
        id, document_id, version_no, content_hash, original_filename, file_ext,
        size_bytes, page_count, uploaded_by, pipeline_version, stage, fingerprint
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_LIST_SQL = """
    SELECT d.*, u.name AS owner_name,
           (SELECT COUNT(*) FROM document_versions v WHERE v.document_id = d.id) AS version_count,
           -- the version shown: the latest ready version, or the latest version when none is ready yet
           COALESCE(d.latest_version_id,
                    (SELECT v.id FROM document_versions v WHERE v.document_id = d.id
                     ORDER BY v.version_no DESC LIMIT 1)) AS shown_version_id
    FROM library_documents d
    LEFT JOIN users u ON u.id = d.owner_id
"""


def _version_params(document_id: str, version_no: int, v: NewVersion) -> tuple:
    return (
        v.id, document_id, version_no, v.content_hash, v.original_filename, v.file_ext,
        v.size_bytes, v.page_count, v.uploaded_by, v.pipeline_version, STAGE_QUEUED,
        v.fingerprint,
    )


def _is_hash_conflict(err: sqlite3.IntegrityError) -> bool:
    return "content_hash" in str(err)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SQLiteLibraryRepository(BaseLibraryRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    # ── Versions ───────────────────────────────────────────────────────

    def find_version_by_hash(self, content_hash: str) -> DocumentVersion | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM document_versions WHERE content_hash = ?", (content_hash,)
            ).fetchone()
        return self._to_version(row) if row else None

    def create_document_with_version(
        self, document_id: str, display_name: str, owner_id: str, version: NewVersion
    ) -> DocumentVersion | None:
        try:
            with self._db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO library_documents (id, display_name, owner_id) VALUES (?, ?, ?)",
                    (document_id, display_name, owner_id),
                )
                conn.execute(_INSERT_VERSION, _version_params(document_id, 1, version))
                row = conn.execute(
                    "SELECT * FROM document_versions WHERE id = ?", (version.id,)
                ).fetchone()
        except sqlite3.IntegrityError as err:
            if _is_hash_conflict(err):
                return None  # the transaction is rolled back: the document is not created either
            raise
        return self._to_version(row)

    def create_next_version(self, document_id: str, version: NewVersion) -> DocumentVersion | None:
        try:
            with self._db.get_connection() as conn:
                # BEGIN IMMEDIATE: take the write lock before reading MAX so two concurrent
                # new-version uploads cannot get the same version_no.
                conn.execute("BEGIN IMMEDIATE")
                next_no = conn.execute(
                    """
                    SELECT MAX(d.version_counter,
                               COALESCE((SELECT MAX(version_no) FROM document_versions
                                         WHERE document_id = d.id), 0)) + 1
                    FROM library_documents d WHERE d.id = ?
                    """,
                    (document_id,),
                ).fetchone()[0]
                conn.execute(_INSERT_VERSION, _version_params(document_id, next_no, version))
                conn.execute(
                    "UPDATE library_documents SET version_counter = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (next_no, document_id),
                )
                row = conn.execute(
                    "SELECT * FROM document_versions WHERE id = ?", (version.id,)
                ).fetchone()
        except sqlite3.IntegrityError as err:
            if _is_hash_conflict(err):
                return None
            raise
        return self._to_version(row)

    def requeue_version(self, version_id: str, uploaded_by: str) -> DocumentVersion:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                UPDATE document_versions SET
                    stage = ?, attempts = 0, error = NULL, next_retry_at = NULL,
                    locked_until = NULL, cancel_requested = 0, vision_failed = 0,
                    progress_done = 0, progress_total = 0, reuse_stats = NULL,
                    started_at = NULL, finished_at = NULL, uploaded_by = ?
                WHERE id = ?
                """,
                (STAGE_QUEUED, uploaded_by, version_id),
            )
            row = conn.execute(
                "SELECT * FROM document_versions WHERE id = ?", (version_id,)
            ).fetchone()
        return self._to_version(row)

    def get_version(self, version_id: str) -> DocumentVersion | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM document_versions WHERE id = ?", (version_id,)
            ).fetchone()
        return self._to_version(row) if row else None

    def save_profile(self, version_id: str, profile_json: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "INSERT INTO document_profiles (version_id, profile) VALUES (?, ?) "
                "ON CONFLICT(version_id) DO UPDATE SET profile = excluded.profile, created_at = CURRENT_TIMESTAMP",
                (version_id, profile_json),
            )

    def list_versions(self, document_id: str) -> list[DocumentVersion]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM document_versions WHERE document_id = ? ORDER BY version_no DESC",
                (document_id,),
            ).fetchall()
        return [self._to_version(r) for r in rows]

    # ── Documents ──────────────────────────────────────────────────────

    def get_document(self, document_id: str) -> LibraryDocument | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM library_documents WHERE id = ?", (document_id,)
            ).fetchone()
        return self._to_document(row) if row else None

    def list_documents(
        self, query: str | None, uploaded_by: str | None, limit: int, offset: int
    ) -> list[DocumentListItem]:
        where = ["d.status = 'active'"]
        params: list = []
        if query:
            where.append("d.display_name LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(query)}%")
        if uploaded_by:
            where.append("d.owner_id = ?")
            params.append(uploaded_by)
        sql = (
            f"{_LIST_SQL} WHERE {' AND '.join(where)} "
            "ORDER BY d.updated_at DESC, d.id LIMIT ? OFFSET ?"
        )
        params += [limit, offset]
        with self._db.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._to_item(conn, r) for r in rows]

    def get_document_item(self, document_id: str) -> DocumentListItem | None:
        with self._db.get_connection() as conn:
            row = conn.execute(f"{_LIST_SQL} WHERE d.id = ?", (document_id,)).fetchone()
            return self._to_item(conn, row) if row else None

    def rename_document(self, document_id: str, display_name: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE library_documents SET display_name = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (display_name, document_id),
            )

    # ── Delete / archive ───────────────────────────────────────────────

    def detach_from_owner_notebooks(self, document_id: str, owner_id: str) -> int:
        with self._db.get_connection() as conn:
            cur = conn.execute(
                """
                DELETE FROM notebook_sources
                WHERE document_id = ?
                  AND notebook_id IN (SELECT id FROM notebooks WHERE owner_id = ?)
                """,
                (document_id, owner_id),
            )
            return cur.rowcount

    def count_notebook_uses(self, document_id: str) -> int:
        with self._db.get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM notebook_sources WHERE document_id = ?", (document_id,)
            ).fetchone()[0]

    def count_version_pins(self, version_id: str) -> int:
        with self._db.get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM notebook_sources WHERE version_id = ?", (version_id,)
            ).fetchone()[0]

    def archive_document(self, document_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE library_documents SET status = 'archived', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (document_id,),
            )

    def delete_document(self, document_id: str) -> None:
        with self._db.get_connection() as conn:
            # The notebook_sources FK has no CASCADE: a document still used by a notebook
            # cannot be deleted (IntegrityError) — a safety net if a service rule is missed.
            conn.execute("DELETE FROM document_versions WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM library_documents WHERE id = ?", (document_id,))

    def delete_version(self, document_id: str, version_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "DELETE FROM document_versions WHERE id = ? AND document_id = ?",
                (version_id, document_id),
            )
            conn.execute(
                """
                UPDATE library_documents SET
                    latest_version_id = (
                        SELECT id FROM document_versions
                        WHERE document_id = ? AND stage = 'ready'
                        ORDER BY version_no DESC LIMIT 1
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (document_id, document_id),
            )

    def transfer_ownership(self, from_user_id: str, to_user_id: str) -> int:
        with self._db.get_connection() as conn:
            cur = conn.execute(
                "UPDATE library_documents SET owner_id = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE owner_id = ?",
                (to_user_id, from_user_id),
            )
            return cur.rowcount

    # ── Mapper ─────────────────────────────────────────────────────────

    # ── Similarity suggestions ─────────────────────────────────────────

    def list_fingerprints(self) -> list[tuple[str, str, bytes]]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.display_name, v.fingerprint
                FROM library_documents d
                JOIN document_versions v ON v.id = (
                    SELECT id FROM document_versions
                    WHERE document_id = d.id AND fingerprint IS NOT NULL
                      AND stage NOT IN ('failed', 'cancelled')
                    ORDER BY version_no DESC LIMIT 1
                )
                WHERE d.status = 'active'
                """
            ).fetchall()
        return [(r[0], r[1], bytes(r[2])) for r in rows]

    def create_pending(self, pending: PendingUpload) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO pending_uploads (
                    id, user_id, original_filename, file_ext, size_bytes, content_hash,
                    page_count, fingerprint, candidate_document_id, score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pending.id, pending.user_id, pending.original_filename, pending.file_ext,
                    pending.size_bytes, pending.content_hash, pending.page_count,
                    pending.fingerprint, pending.candidate_document_id, pending.score,
                ),
            )

    def get_pending(self, pending_id: str) -> PendingUpload | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pending_uploads WHERE id = ?", (pending_id,)
            ).fetchone()
        return self._to_pending(row) if row else None

    def delete_pending(self, pending_id: str) -> bool:
        with self._db.get_connection() as conn:
            cur = conn.execute("DELETE FROM pending_uploads WHERE id = ?", (pending_id,))
            return cur.rowcount > 0

    def list_expired_pending(self, older_than_minutes: int) -> list[PendingUpload]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_uploads WHERE created_at <= datetime('now', ?)",
                (f"-{int(older_than_minutes)} minutes",),
            ).fetchall()
        return [self._to_pending(r) for r in rows]

    @staticmethod
    def _to_pending(row: sqlite3.Row) -> PendingUpload:
        return PendingUpload(
            id=row["id"],
            user_id=row["user_id"],
            original_filename=row["original_filename"],
            file_ext=row["file_ext"],
            size_bytes=row["size_bytes"],
            content_hash=row["content_hash"],
            page_count=row["page_count"],
            fingerprint=bytes(row["fingerprint"]) if row["fingerprint"] is not None else None,
            candidate_document_id=row["candidate_document_id"],
            score=row["score"],
            created_at=_ts(row["created_at"]),
        )

    def _to_item(self, conn: sqlite3.Connection, row: sqlite3.Row) -> DocumentListItem:
        version = None
        if row["shown_version_id"]:
            vrow = conn.execute(
                "SELECT * FROM document_versions WHERE id = ?", (row["shown_version_id"],)
            ).fetchone()
            version = self._to_version(vrow) if vrow else None
        return DocumentListItem(
            document=self._to_document(row),
            latest_version=version,
            owner_name=row["owner_name"],
            version_count=row["version_count"],
        )

    @staticmethod
    def _to_document(row: sqlite3.Row) -> LibraryDocument:
        return LibraryDocument(
            id=row["id"],
            display_name=row["display_name"],
            owner_id=row["owner_id"],
            latest_version_id=row["latest_version_id"],
            status=row["status"],
            created_at=_ts(row["created_at"]),
            updated_at=_ts(row["updated_at"]),
        )

    @staticmethod
    def _to_version(row: sqlite3.Row) -> DocumentVersion:
        return DocumentVersion(
            id=row["id"],
            document_id=row["document_id"],
            version_no=row["version_no"],
            content_hash=row["content_hash"],
            original_filename=row["original_filename"],
            file_ext=row["file_ext"],
            size_bytes=row["size_bytes"],
            page_count=row["page_count"],
            uploaded_by=row["uploaded_by"],
            uploaded_at=_ts(row["uploaded_at"]),
            stage=row["stage"],
            progress_done=row["progress_done"],
            progress_total=row["progress_total"],
            attempts=row["attempts"],
            vision_failed=row["vision_failed"],
            pipeline_version=row["pipeline_version"],
            error=row["error"],
            finished_at=_ts(row["finished_at"]),
            reuse_stats=json.loads(row["reuse_stats"]) if row["reuse_stats"] else None,
        )
