"""SQLite adapter for the conversation persistence port.

Sits next to SQLiteFeatureRepository so all relational adapters live in one
place. The repository depends on the shared Database class for connection
management — it does not open SQLite connections directly.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from app.core.database import Database
from app.services.conversation.base.repository import (
    ConversationRepository,
)
from app.services.conversation.model import Conversation, Message


def _parse_ts(value) -> datetime:
    """SQLite stores TIMESTAMP as TEXT (ISO format). Coerce to datetime."""
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return datetime.utcnow()


class SQLiteConversationRepository(ConversationRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    # ── Conversations ──────────────────────────────────────────────────

    def create_conversation(self, user_id: str, title: str) -> Conversation:
        conv_id = str(uuid.uuid4())
        with self._db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, user_id, title)
                VALUES (?, ?, ?)
                """,
                (conv_id, user_id, title),
            )
            row = conn.execute(
                "SELECT id, user_id, title, created_at, updated_at "
                "FROM conversations WHERE id = ?",
                (conv_id,),
            ).fetchone()
        return self._row_to_conversation(row)

    def list_conversations(self, user_id: str, limit: int = 100) -> list[Conversation]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM conversations
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._row_to_conversation(r) for r in rows]

    def get_conversation(
        self, conversation_id: str, user_id: str
    ) -> Conversation | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM conversations
                WHERE id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self._row_to_conversation(row) if row else None

    def update_title(
        self, conversation_id: str, user_id: str, title: str
    ) -> bool:
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (title, conversation_id, user_id),
            )
            return cursor.rowcount > 0

    def touch(self, conversation_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,),
            )

    def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            return cursor.rowcount > 0

    # ── Messages ───────────────────────────────────────────────────────

    def add_message(
        self, conversation_id: str, role: str, content: str
    ) -> Message:
        if role not in ("user", "assistant"):
            raise ValueError(
                f"Invalid role: {role!r}. Must be 'user' or 'assistant'."
            )
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content)
                VALUES (?, ?, ?)
                """,
                (conversation_id, role, content),
            )
            msg_id = cursor.lastrowid
            row = conn.execute(
                "SELECT id, conversation_id, role, content, created_at "
                "FROM messages WHERE id = ?",
                (msg_id,),
            ).fetchone()
        return self._row_to_message(row)

    def list_messages(
        self, conversation_id: str, limit: int | None = None
    ) -> list[Message]:
        with self._db.get_connection() as conn:
            if limit is None:
                rows = conn.execute(
                    """
                    SELECT id, conversation_id, role, content, created_at
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (conversation_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, conversation_id, role, content, created_at
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY created_at ASC, id ASC
                    LIMIT ?
                    """,
                    (conversation_id, limit),
                ).fetchall()
        return [self._row_to_message(r) for r in rows]

    # ── Row mappers ────────────────────────────────────────────────────

    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> Conversation:
        return Conversation(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            created_at=_parse_ts(row["created_at"]),
            updated_at=_parse_ts(row["updated_at"]),
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            created_at=_parse_ts(row["created_at"]),
        )
