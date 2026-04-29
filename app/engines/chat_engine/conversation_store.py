"""Port and adapters for conversation history persistence.

The previous implementation kept history in a Python dict on the ChatEngine
instance, which lost all conversations on container restart. This module
provides:

  - ConversationStore (port): contract for read/write/clear per session
  - InMemoryConversationStore: legacy behavior, useful for tests
  - SQLiteConversationStore: durable storage using the same SQLite file
"""
from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path


class ConversationStore(ABC):
    @abstractmethod
    def get(self, session_id: str) -> list[dict]: ...

    @abstractmethod
    def append(self, session_id: str, messages: list[dict]) -> None: ...

    @abstractmethod
    def clear(self, session_id: str) -> None: ...


class InMemoryConversationStore(ConversationStore):
    """Process-local store. Lost on restart. Use for tests or single-shot demos."""

    def __init__(self):
        self._store: dict[str, list[dict]] = {}

    def get(self, session_id: str) -> list[dict]:
        return list(self._store.get(session_id, []))

    def append(self, session_id: str, messages: list[dict]) -> None:
        self._store[session_id] = list(messages)

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)


class SQLiteConversationStore(ConversationStore):
    """Durable conversation store backed by SQLite.

    Schema: a single row per session, holding the JSON-serialized message list.
    Suitable for prototyping. For high-write multi-user scenarios, swap to
    Postgres or Redis without touching ChatEngine.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_history (
                    session_id TEXT PRIMARY KEY,
                    messages_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT messages_json FROM conversation_history WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return []
        try:
            return json.loads(row["messages_json"])
        except (TypeError, json.JSONDecodeError):
            return []

    def append(self, session_id: str, messages: list[dict]) -> None:
        payload = json.dumps(messages, ensure_ascii=False, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_history (session_id, messages_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    messages_json = excluded.messages_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, payload),
            )

    def clear(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM conversation_history WHERE session_id = ?",
                (session_id,),
            )
