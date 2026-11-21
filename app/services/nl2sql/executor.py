"""Run LLM-generated SQL in an isolated database (DESIGN_GROUP_A.md §9).

Each question runs in an **in-memory** database that only holds the `features`
table with rows from the sources checked in the notebook. Other tables
(users, conversations, other documents) physically do not exist there, so
LLM-generated SQL cannot read them — not even through `COUNT(*)`, which got past
the authorizer in the TEMP VIEW approach (found during the spike, step 7.0).

Layers of defence:
1. Validator: a single SELECT statement only (security.py).
2. An in-memory database holding only the allowed data.
3. Authorizer: SELECT/READ/functions only; internal `sqlite_*` tables are rejected.
4. An execution time limit (progress handler) & a row limit.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Columns visible to the LLM. version_id & page_number are used for citations.
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
    """The query went over the execution time limit."""


class SQLRejected(ValueError):
    """The database rejected the query (authorizer / not an allowed SELECT)."""


class SQLExecutionFailed(ValueError):
    """The query is well-formed but failed to run (e.g. a missing column/table)."""


def _authorizer(action: int, arg1: str | None, arg2: str | None, db: str | None, src: str | None) -> int:
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ and arg1 and arg1.lower().startswith("sqlite_"):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def build_scoped_db(db_path: Path, version_ids: list[str]) -> sqlite3.Connection:
    """Copy the `features` rows of `version_ids` into a new in-memory database."""
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
    """Run SQL on the allowed source data only.

    Returns:
        (rows, truncated) — at most `max_rows` rows.

    Raises:
        SQLRejected: the database authorizer rejected the query.
        SQLExecutionFailed: the query failed to run.
        SQLExecutionTimeout: went over `timeout_s`.
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
            raise SQLExecutionTimeout(f"The query went over the {timeout_s:.0f}-second limit.") from None
        if "not authorized" in str(e).lower():
            raise SQLRejected(f"Query rejected: {e}") from None
        raise SQLExecutionFailed(f"The database failed to run the query: {e}") from None
    except sqlite3.DatabaseError as e:
        raise SQLRejected(f"Query rejected: {e}") from None
    finally:
        conn.close()
