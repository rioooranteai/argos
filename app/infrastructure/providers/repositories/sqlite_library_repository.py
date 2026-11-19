from __future__ import annotations

import sqlite3
from datetime import datetime

from app.core.database import Database
from app.infrastructure.interface.library_repository import BaseLibraryRepository
from app.services.library.model import (
    STAGE_QUEUED,
    DocumentListItem,
    DocumentVersion,
    LibraryDocument,
    NewVersion,
)


def _ts(value) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace(" ", "T"))


_INSERT_VERSION = """
    INSERT INTO document_versions (
        id, document_id, version_no, content_hash, original_filename, file_ext,
        size_bytes, page_count, uploaded_by, pipeline_version, stage
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_LIST_SQL = """
    SELECT d.*, u.name AS owner_name,
           (SELECT COUNT(*) FROM document_versions v WHERE v.document_id = d.id) AS version_count,
           -- versi yang ditampilkan: versi ready terbaru, atau versi terbaru bila belum ada yang ready
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
    )


def _is_hash_conflict(err: sqlite3.IntegrityError) -> bool:
    return "content_hash" in str(err)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SQLiteLibraryRepository(BaseLibraryRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    # ── Versi ──────────────────────────────────────────────────────────

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
                return None  # transaksi di-rollback: dokumen juga tidak dibuat
            raise
        return self._to_version(row)

    def create_next_version(self, document_id: str, version: NewVersion) -> DocumentVersion | None:
        try:
            with self._db.get_connection() as conn:
                # BEGIN IMMEDIATE: kunci tulis sebelum membaca MAX agar dua upload
                # versi baru bersamaan tidak mendapat version_no yang sama.
                conn.execute("BEGIN IMMEDIATE")
                next_no = conn.execute(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 FROM document_versions "
                    "WHERE document_id = ?",
                    (document_id,),
                ).fetchone()[0]
                conn.execute(_INSERT_VERSION, _version_params(document_id, next_no, version))
                conn.execute(
                    "UPDATE library_documents SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (document_id,),
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
                    progress_done = 0, progress_total = 0,
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

    def list_versions(self, document_id: str) -> list[DocumentVersion]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM document_versions WHERE document_id = ? ORDER BY version_no DESC",
                (document_id,),
            ).fetchall()
        return [self._to_version(r) for r in rows]

    # ── Dokumen ────────────────────────────────────────────────────────

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

    # ── Mapper ─────────────────────────────────────────────────────────

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
        )
