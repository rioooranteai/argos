from __future__ import annotations

import sqlite3
from datetime import datetime

from app.core.database import Database
from app.infrastructure.interface.user_repository import BaseUserRepository
from app.services.user.model import User


def _ts(value) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace(" ", "T"))


class SQLiteUserRepository(BaseUserRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def upsert_on_login(self, user_id: str, email: str, name: str | None, picture: str | None) -> User:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, email, name, picture, last_login_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    email = excluded.email,
                    name = excluded.name,
                    picture = excluded.picture,
                    last_login_at = CURRENT_TIMESTAMP
                """,
                (user_id, email.lower(), name, picture),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._to_user(row)

    def get(self, user_id: str) -> User | None:
        with self._db.get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._to_user(row) if row else None

    def list_all(self) -> list[User]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY COALESCE(name, email) COLLATE NOCASE"
            ).fetchall()
        return [self._to_user(r) for r in rows]

    def set_active(self, user_id: str, active: bool) -> bool:
        with self._db.get_connection() as conn:
            cur = conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(active), user_id))
            return cur.rowcount > 0

    @staticmethod
    def _to_user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            picture=row["picture"],
            is_active=bool(row["is_active"]),
            created_at=_ts(row["created_at"]),
            last_login_at=_ts(row["last_login_at"]),
        )
