"""Tests for SQLiteConversationRepository.

These tests use a fresh tmp database per test so they're fully isolated.
The schema is initialized via the same `Database.init_db()` the app uses,
so we exercise the real DDL — not a mocked schema.
"""
from __future__ import annotations

import pytest

from app.core.database import Database
from app.services.conversation.sqlite_repository import SQLiteConversationRepository


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "test.db"
    Database(db_path=db_path).init_db()
    return SQLiteConversationRepository(db_path=db_path)


class TestConversationCRUD:
    def test_create_returns_entity_with_id(self, repo):
        conv = repo.create_conversation(user_id="u1", title="Hello")
        assert conv.id  # non-empty UUID
        assert conv.user_id == "u1"
        assert conv.title == "Hello"
        assert conv.created_at is not None
        assert conv.updated_at is not None

    def test_get_returns_none_for_missing_or_other_owner(self, repo):
        conv = repo.create_conversation(user_id="u1", title="t")
        assert repo.get_conversation(conv.id, user_id="u1") is not None
        assert repo.get_conversation(conv.id, user_id="u2") is None
        assert repo.get_conversation("does-not-exist", user_id="u1") is None

    def test_list_orders_by_updated_at_desc(self, repo):
        c1 = repo.create_conversation(user_id="u1", title="first")
        c2 = repo.create_conversation(user_id="u1", title="second")
        # Touch c1 so it becomes the most recent.
        repo.touch(c1.id)
        listed = repo.list_conversations(user_id="u1")
        assert [c.id for c in listed][0] == c1.id
        assert {c.id for c in listed} == {c1.id, c2.id}

    def test_list_isolates_users(self, repo):
        repo.create_conversation(user_id="u1", title="a")
        repo.create_conversation(user_id="u2", title="b")
        assert len(repo.list_conversations(user_id="u1")) == 1
        assert len(repo.list_conversations(user_id="u2")) == 1

    def test_update_title_owner_check(self, repo):
        conv = repo.create_conversation(user_id="u1", title="old")
        assert repo.update_title(conv.id, "u2", "hijack") is False
        assert repo.update_title(conv.id, "u1", "new") is True
        refetched = repo.get_conversation(conv.id, "u1")
        assert refetched.title == "new"

    def test_delete_owner_check_and_cascade(self, repo):
        conv = repo.create_conversation(user_id="u1", title="t")
        repo.add_message(conv.id, "user", "hi")
        repo.add_message(conv.id, "assistant", "hello")
        # Other user can't delete.
        assert repo.delete_conversation(conv.id, "u2") is False
        # Owner can.
        assert repo.delete_conversation(conv.id, "u1") is True
        # Cascade: messages gone too.
        assert repo.list_messages(conv.id) == []
        assert repo.get_conversation(conv.id, "u1") is None


class TestMessages:
    def test_add_and_list_chronological(self, repo):
        conv = repo.create_conversation(user_id="u1", title="t")
        repo.add_message(conv.id, "user", "first")
        repo.add_message(conv.id, "assistant", "second")
        repo.add_message(conv.id, "user", "third")
        msgs = repo.list_messages(conv.id)
        assert [m.content for m in msgs] == ["first", "second", "third"]
        assert [m.role for m in msgs] == ["user", "assistant", "user"]

    def test_invalid_role_rejected(self, repo):
        conv = repo.create_conversation(user_id="u1", title="t")
        with pytest.raises(ValueError):
            repo.add_message(conv.id, "system", "nope")

    def test_list_messages_limit(self, repo):
        conv = repo.create_conversation(user_id="u1", title="t")
        for i in range(5):
            repo.add_message(conv.id, "user", f"m{i}")
        msgs = repo.list_messages(conv.id, limit=2)
        assert len(msgs) == 2
        assert [m.content for m in msgs] == ["m0", "m1"]

    def test_messages_preserved_for_unrelated_conversation(self, repo):
        c1 = repo.create_conversation(user_id="u1", title="a")
        c2 = repo.create_conversation(user_id="u1", title="b")
        repo.add_message(c1.id, "user", "in-c1")
        repo.add_message(c2.id, "user", "in-c2")
        repo.delete_conversation(c1.id, "u1")
        assert [m.content for m in repo.list_messages(c2.id)] == ["in-c2"]
