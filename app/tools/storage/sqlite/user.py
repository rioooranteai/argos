from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from app.core.database import Database
from app.services.user.model import User
from app.services.user.ports import BaseUserRepository


def _ts(value) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace(" ", "T"))


class SQLiteUserRepository(BaseUserRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def upsert_on_login(
        self,
        google_sub: str,
        email: str,
        name: str | None,
        picture: str | None,
        new_user_id: str | None = None,
    ) -> User:
        with self._db.get_connection() as conn:
            row = conn.execute("SELECT id FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
            if row is None:
                user_id = new_user_id or str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO users (id, google_sub, email, name, picture, last_login_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, google_sub, email.lower(), name, picture),
                )
            else:
                user_id = row["id"]
                conn.execute(
                    """
                    UPDATE users SET email = ?, name = ?, picture = ?, last_login_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (email.lower(), name, picture, user_id),
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
