from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from app.core.config import infra

DB_PATH = infra.sqlite_path

# Worker & request bisa menulis bersamaan; tunggu lock alih-alih langsung gagal.
BUSY_TIMEOUT_SECONDS = 10


class Database:
    """Manages SQLite connection lifecycle only.

    Business logic (insert, query) belongs in service-layer repositories,
    not here. This class is responsible for one thing: providing connections.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # better concurrent read perf
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_SECONDS * 1000}")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_db(self) -> Generator[sqlite3.Connection, None, None]:
        """FastAPI-compatible dependency. Use with Depends(db.get_db)."""
        with self.get_connection() as conn:
            yield conn


db = Database()
