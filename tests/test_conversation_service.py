"""Tests for ConversationService — orchestration on top of the repository.

These use the real SQLite repository (with a tmp DB) plus a fake LLM that
records the prompt and returns canned text. We don't mock the repository
because the service is thin — most behavior IS the integration.
"""
from __future__ import annotations

import asyncio
from typing import Type

import pytest

from app.core.database import Database
from app.infrastructure.interface.llm import BaseLLM
from app.services.conversation.service import (
    ConversationService,
    _normalize_title,
    _placeholder_title_from_message,
)
from app.services.conversation.sqlite_repository import SQLiteConversationRepository


# ── Helpers ────────────────────────────────────────────────────────────────


class _FakeLLM(BaseLLM):
    def __init__(self, response: str = "Judul Otomatis"):
        self.response = response
        self.last_prompt: str | None = None
        self.last_system: str | None = None
        self.calls = 0

    def invoke(self, prompt: str, system: str | None = None) -> str:
        self.last_prompt = prompt
        self.last_system = system
        self.calls += 1
        return self.response

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        return self.invoke(prompt, system)

    def with_structured_output(self, schema: Type) -> "BaseLLM":  # noqa: D401
        return self


class _RaisingLLM(BaseLLM):
    def invoke(self, prompt: str, system: str | None = None) -> str:
        raise RuntimeError("LLM blew up")

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        raise RuntimeError("LLM blew up")

    def with_structured_output(self, schema: Type) -> "BaseLLM":
        return self


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "svc.db"
    Database(db_path=db_path).init_db()
    return SQLiteConversationRepository(db_path=db_path)


@pytest.fixture
def fake_llm():
    return _FakeLLM()


@pytest.fixture
def service(repo, fake_llm):
    return ConversationService(repository=repo, title_llm=fake_llm)


# ── Pure helpers ───────────────────────────────────────────────────────────


class TestTitleHelpers:
    def test_placeholder_truncation(self):
        long_text = "a" * 200
        result = _placeholder_title_from_message(long_text)
        assert len(result) <= 60
        assert result.endswith("…")

    def test_placeholder_short_kept_as_is(self):
        assert _placeholder_title_from_message("Halo") == "Halo"

    def test_placeholder_empty_falls_back(self):
        assert _placeholder_title_from_message("   ") == "New chat"

    def test_normalize_strips_quotes_and_punct(self):
        assert _normalize_title('"Tentang harga"') == "Tentang harga"
        assert _normalize_title("Pertanyaan harga.") == "Pertanyaan harga"
        assert _normalize_title("  banyak    spasi  ") == "banyak spasi"


# ── Service behavior ───────────────────────────────────────────────────────


class TestServiceLifecycle:
    def test_create_uses_first_message_as_placeholder(self, service):
        conv = service.create_for_user("u1", first_message="Bagaimana harga produk X?")
        assert conv.title == "Bagaimana harga produk X?"

    def test_create_without_message_uses_fallback(self, service):
        conv = service.create_for_user("u1")
        assert conv.title == "New chat"

    def test_list_for_user(self, service):
        service.create_for_user("u1", first_message="a")
        service.create_for_user("u1", first_message="b")
        service.create_for_user("u2", first_message="c")
        assert len(service.list_for_user("u1")) == 2
        assert len(service.list_for_user("u2")) == 1

    def test_get_with_messages_owner_check(self, service):
        conv = service.create_for_user("u1", first_message="hi")
        assert service.get_with_messages(conv.id, "u1") is not None
        assert service.get_with_messages(conv.id, "u2") is None

    def test_rename_normalizes_and_owner_checks(self, service):
        conv = service.create_for_user("u1", first_message="x")
        assert service.rename(conv.id, "u2", "hijack") is False
        assert service.rename(conv.id, "u1", '"clean me"') is True
        bundle = service.get_with_messages(conv.id, "u1")
        assert bundle.conversation.title == "clean me"

    def test_delete_owner_check(self, service):
        conv = service.create_for_user("u1", first_message="x")
        assert service.delete(conv.id, "u2") is False
        assert service.delete(conv.id, "u1") is True


class TestMessagePersistence:
    def test_append_user_message_returns_none_for_other_owner(self, service):
        conv = service.create_for_user("u1", first_message="x")
        assert service.append_user_message(conv.id, "u2", "hack") is None

    def test_append_user_then_assistant_persists_in_order(self, service):
        conv = service.create_for_user("u1", first_message="x")
        service.append_user_message(conv.id, "u1", "hi")
        service.append_assistant_message(conv.id, "hello")
        bundle = service.get_with_messages(conv.id, "u1")
        contents = [m.content for m in bundle.messages]
        roles = [m.role for m in bundle.messages]
        assert contents == ["hi", "hello"]
        assert roles == ["user", "assistant"]

    def test_get_messages_for_engine_owner_check(self, service):
        conv = service.create_for_user("u1", first_message="x")
        service.append_user_message(conv.id, "u1", "hi")
        assert service.get_messages_for_engine(conv.id, "u1") is not None
        assert service.get_messages_for_engine(conv.id, "u2") is None


class TestAutoTitle:
    def test_generate_title_updates_repo(self, service, fake_llm, repo):
        fake_llm.response = "Harga produk kompetitor"
        conv = service.create_for_user("u1", first_message="harga produk X di pasar?")
        asyncio.get_event_loop().run_until_complete(
            service.generate_title_async(conv.id, "u1", "harga produk X di pasar?")
        )
        refetched = repo.get_conversation(conv.id, "u1")
        assert refetched.title == "Harga produk kompetitor"
        assert fake_llm.calls == 1

    def test_generate_title_swallows_llm_errors(self, repo):
        svc = ConversationService(repository=repo, title_llm=_RaisingLLM())
        conv = svc.create_for_user("u1", first_message="hi")
        original_title = conv.title
        # Should not raise.
        asyncio.get_event_loop().run_until_complete(
            svc.generate_title_async(conv.id, "u1", "hi")
        )
        # Title untouched.
        refetched = repo.get_conversation(conv.id, "u1")
        assert refetched.title == original_title

    def test_generate_title_skipped_without_llm(self, repo):
        svc = ConversationService(repository=repo, title_llm=None)
        conv = svc.create_for_user("u1", first_message="hi")
        asyncio.get_event_loop().run_until_complete(
            svc.generate_title_async(conv.id, "u1", "hi")
        )
        refetched = repo.get_conversation(conv.id, "u1")
        assert refetched.title == conv.title  # unchanged
