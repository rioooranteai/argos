"""Read-only SQL executor.

Defense-in-depth: even if the validator misses a destructive query, the
SQLite driver is opened with mode=ro, so writes fail at the driver level.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def execute_readonly_sql(sql_query: str, db_path: Path) -> list[dict[str, Any]]:
    """Execute SQL in strict read-only mode.

    Args:
        sql_query: The SQL string to execute (validator should run first).
        db_path: Filesystem path to the SQLite database.

    Returns:
        List of row dicts.

    Raises:
        ValueError: When the database rejects the query.
    """
    db_uri = f"file:{db_path.as_posix()}?mode=ro"

    conn = sqlite3.connect(db_uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        raise ValueError(f"Query gagal dieksekusi oleh database: {str(e)}")
    finally:
        conn.close()
