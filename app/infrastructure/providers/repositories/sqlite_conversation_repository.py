"""SQLite adapter for the conversation persistence port.

Sits next to SQLiteFeatureRepository so all relational adapters live in one
place. The repository depends on the shared Database class for connection
management — it does not open SQLite connections directly.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from app.core.database import Database
from app.infrastructure.interface.conversation_repository import BaseConversationRepository
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


class SQLiteConversationRepository(BaseConversationRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    # ── Conversations ──────────────────────────────────────────────────

    def create_conversation(
        self, user_id: str, title: str, notebook_id: str | None = None
    ) -> Conversation:
        conv_id = str(uuid.uuid4())
        with self._db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, user_id, title, notebook_id)
                VALUES (?, ?, ?, ?)
                """,
                (conv_id, user_id, title, notebook_id),
            )
            row = conn.execute(
                "SELECT id, user_id, title, notebook_id, created_at, updated_at "
                "FROM conversations WHERE id = ?",
                (conv_id,),
            ).fetchone()
        return self._row_to_conversation(row)

    def list_conversations(
        self, user_id: str, limit: int = 100, notebook_id: str | None = None
    ) -> list[Conversation]:
        where = "user_id = ?"
        params: list = [user_id]
        if notebook_id is not None:
            where += " AND notebook_id = ?"
            params.append(notebook_id)
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id, user_id, title, notebook_id, created_at, updated_at "
                f"FROM conversations WHERE {where} ORDER BY updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._row_to_conversation(r) for r in rows]

    def get_conversation(
        self, conversation_id: str, user_id: str
    ) -> Conversation | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, title, notebook_id, created_at, updated_at
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
        self,
        conversation_id: str,
        role: str,
        content: str,
        source_snapshot: list[str] | None = None,
        citations: list[dict] | None = None,
        trace: dict | None = None,
    ) -> Message:
        if role not in ("user", "assistant"):
            raise ValueError(
                f"Invalid role: {role!r}. Must be 'user' or 'assistant'."
            )
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, source_snapshot, citations, trace)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content,
                    json.dumps(source_snapshot) if source_snapshot is not None else None,
                    json.dumps(citations, ensure_ascii=False, default=str) if citations else None,
                    json.dumps(trace, ensure_ascii=False, default=str) if trace else None,
                ),
            )
            msg_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?",
                (msg_id,),
            ).fetchone()
        return self._row_to_message(row)

    def get_message(self, message_id: int) -> Message | None:
        with self._db.get_connection() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return self._row_to_message(row) if row else None

    def set_message_status(
        self,
        message_id: int,
        status: str,
        error_code: str | None = None,
        source_snapshot: list[str] | None = None,
    ) -> None:
        with self._db.get_connection() as conn:
            if source_snapshot is None:
                conn.execute(
                    "UPDATE messages SET status = ?, error_code = ? WHERE id = ?",
                    (status, error_code, message_id),
                )
            else:
                conn.execute(
                    "UPDATE messages SET status = ?, error_code = ?, source_snapshot = ? WHERE id = ?",
                    (status, error_code, json.dumps(source_snapshot), message_id),
                )

    def list_messages(
        self, conversation_id: str, limit: int | None = None, status: str | None = None
    ) -> list[Message]:
        sql = "SELECT * FROM messages WHERE conversation_id = ?"
        params: list = [conversation_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at ASC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._db.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
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
            notebook_id=row["notebook_id"],
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            created_at=_parse_ts(row["created_at"]),
            source_snapshot=json.loads(row["source_snapshot"]) if row["source_snapshot"] else None,
            citations=json.loads(row["citations"]) if row["citations"] else [],
            status=row["status"],
            error_code=row["error_code"],
            trace=json.loads(row["trace"]) if row["trace"] else None,
        )
