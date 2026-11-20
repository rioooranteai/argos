"""Eksekusi SQL buatan LLM di database terisolasi (DESIGN_GROUP_A.md §9).

Setiap pertanyaan dijalankan di database **in-memory** yang hanya berisi tabel
`features` dengan baris milik sumber yang dicentang di notebook. Tabel lain
(users, conversations, dokumen lain) secara fisik tidak ada di sana, sehingga
SQL buatan LLM tidak bisa membacanya — termasuk lewat `COUNT(*)`, yang lolos
dari authorizer pada pendekatan TEMP VIEW (ditemukan saat spike, langkah 7.0).

Lapisan pertahanan:
1. Validator: hanya satu pernyataan SELECT (security.py).
2. Database in-memory berisi data yang diizinkan saja.
3. Authorizer: hanya SELECT/READ/fungsi; tabel internal `sqlite_*` ditolak.
4. Batas waktu eksekusi (progress handler) & batas jumlah baris.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Kolom yang terlihat oleh LLM. version_id & page_number dipakai untuk sitasi.
FEATURE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("version_id", "TEXT"),
    ("page_number", "INTEGER"),
    ("section_heading", "TEXT"),
    ("brand_name", "TEXT"),
    ("product_name", "TEXT"),
    ("price", "REAL"),
    ("price_currency", "TEXT"),
    ("advantages", "TEXT"),
    ("disadvantages", "TEXT"),
)

_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),  # CTE rekursif
}


class SQLExecutionTimeout(Exception):
    """Query melewati batas waktu eksekusi."""


class SQLRejected(ValueError):
    """Database menolak query (authorizer / bukan SELECT yang diizinkan)."""


class SQLExecutionFailed(ValueError):
    """Query valid secara bentuk tetapi gagal dijalankan (mis. kolom/tabel tidak ada)."""


def _authorizer(action: int, arg1: str | None, arg2: str | None, db: str | None, src: str | None) -> int:
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ and arg1 and arg1.lower().startswith("sqlite_"):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def build_scoped_db(db_path: Path, version_ids: list[str]) -> sqlite3.Connection:
    """Salin baris `features` milik `version_ids` ke database in-memory baru."""
    columns = ", ".join(name for name, _ in FEATURE_COLUMNS)
    rows: list[tuple] = []
    if version_ids:
        placeholders = ", ".join("?" for _ in version_ids)
        src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            rows = src.execute(
                f"SELECT {columns} FROM features WHERE version_id IN ({placeholders})",
                list(version_ids),
            ).fetchall()
        finally:
            src.close()

    mem = sqlite3.connect(":memory:")
    ddl = ", ".join(f"{name} {kind}" for name, kind in FEATURE_COLUMNS)
    mem.execute(f"CREATE TABLE features ({ddl})")
    mem.executemany(
        f"INSERT INTO features ({columns}) VALUES ({', '.join('?' for _ in FEATURE_COLUMNS)})", rows
    )
    mem.commit()
    mem.execute("PRAGMA query_only = ON")
    mem.row_factory = sqlite3.Row
    mem.set_authorizer(_authorizer)
    return mem


def features_schema_ddl() -> str:
    body = ",\n".join(f"    {name} {kind}" for name, kind in FEATURE_COLUMNS)
    return f"CREATE TABLE features (\n{body}\n);"


def execute_scoped_sql(
    sql_query: str,
    db_path: Path,
    version_ids: list[str],
    timeout_s: float,
    max_rows: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Jalankan SQL pada data sumber yang diizinkan saja.

    Returns:
        (baris, terpotong) — maksimal `max_rows` baris.

    Raises:
        SQLRejected: query ditolak authorizer database.
        SQLExecutionFailed: query gagal dijalankan.
        SQLExecutionTimeout: melewati `timeout_s`.
    """
    conn = build_scoped_db(db_path, version_ids)
    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        cursor = conn.execute(sql_query)
        fetched = cursor.fetchmany(max_rows + 1)
        rows = [dict(r) for r in fetched[:max_rows]]
        return rows, len(fetched) > max_rows
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            raise SQLExecutionTimeout(f"Query melewati batas {timeout_s:.0f} detik.") from None
        if "not authorized" in str(e).lower():
            raise SQLRejected(f"Query ditolak: {e}") from None
        raise SQLExecutionFailed(f"Query gagal dieksekusi oleh database: {e}") from None
    except sqlite3.DatabaseError as e:
        raise SQLRejected(f"Query ditolak: {e}") from None
    finally:
        conn.close()
