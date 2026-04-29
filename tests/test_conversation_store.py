"""Tests for ConversationStore implementations."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.engines.chat_engine.conversation_store import (
    InMemoryConversationStore,
    SQLiteConversationStore,
)


class TestInMemoryConversationStore:
    def test_returns_empty_list_for_unknown_session(self):
        store = InMemoryConversationStore()
        assert store.get("nope") == []

    def test_append_then_get(self):
        store = InMemoryConversationStore()
        msgs = [{"role": "user", "content": "hi"}]
        store.append("s1", msgs)
        assert store.get("s1") == msgs

    def test_append_overwrites(self):
        store = InMemoryConversationStore()
        store.append("s1", [{"role": "user", "content": "first"}])
        store.append("s1", [{"role": "user", "content": "second"}])
        assert store.get("s1") == [{"role": "user", "content": "second"}]

    def test_clear(self):
        store = InMemoryConversationStore()
        store.append("s1", [{"role": "user", "content": "hi"}])
        store.clear("s1")
        assert store.get("s1") == []

    def test_isolation_between_sessions(self):
        store = InMemoryConversationStore()
        store.append("alice", [{"role": "user", "content": "a"}])
        store.append("bob", [{"role": "user", "content": "b"}])
        assert store.get("alice") == [{"role": "user", "content": "a"}]
        assert store.get("bob") == [{"role": "user", "content": "b"}]


class TestSQLiteConversationStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> SQLiteConversationStore:
        return SQLiteConversationStore(db_path=tmp_path / "history.db")

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "history.db"
        store1 = SQLiteConversationStore(db_path=path)
        store1.append("s1", [{"role": "user", "content": "hi"}])

        # Simulate process restart
        store2 = SQLiteConversationStore(db_path=path)
        assert store2.get("s1") == [{"role": "user", "content": "hi"}]

    def test_returns_empty_for_unknown_session(self, store):
        assert store.get("missing") == []

    def test_append_overwrites(self, store):
        store.append("s1", [{"role": "user", "content": "v1"}])
        store.append("s1", [{"role": "user", "content": "v2"}])
        assert store.get("s1") == [{"role": "user", "content": "v2"}]

    def test_clear(self, store):
        store.append("s1", [{"role": "user", "content": "hi"}])
        store.clear("s1")
        assert store.get("s1") == []

    def test_isolation_between_sessions(self, store):
        store.append("alice", [{"role": "user", "content": "a"}])
        store.append("bob", [{"role": "user", "content": "b"}])
        assert store.get("alice") == [{"role": "user", "content": "a"}]
        assert store.get("bob") == [{"role": "user", "content": "b"}]

    def test_handles_unicode(self, store):
        store.append("s1", [{"role": "user", "content": "halo \u2014 saya \u0939\u093f\u0928\u094d\u0926\u0940 dan emoji \U0001f680"}])
        result = store.get("s1")
        assert "\U0001f680" in result[0]["content"]
