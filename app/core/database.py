from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DB_PATH = Path(__file__).resolve().parents[2] / "competitor_data.db"


class Database:
    """Manages SQLite connection lifecycle only.

    Business logic (insert, query) belongs in service-layer repositories,
    not here. This class is responsible for one thing: providing connections.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # better concurrent read perf
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
