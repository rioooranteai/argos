"""Recording AI calls in llm_calls (DESIGN_GROUP_C.md §7.3)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import openai
import pytest

from app.core import log_context
from app.core.database import Database
from app.core.llm_errors import classify_llm_error
from app.core.migrations import run_migrations
from app.core.request_context import _request_id_var
from app.infrastructure.providers.llms.openai_llm import OpenAILLM
from app.infrastructure.providers.repositories.sqlite_llm_call_repository import (
    SQLiteLLMCallRepository,
)
from app.core.observability.recorder import LLMCallRecorder, recorder
from app.core.observability.model import LLMCall


@pytest.fixture
def repo(tmp_path):
    database = Database(db_path=tmp_path / "t.db")
    with database.get_connection() as conn:
        run_migrations(conn)
    return SQLiteLLMCallRepository(database)


@pytest.fixture
def rec(repo):
    r = LLMCallRecorder()
    r.attach(repo)
    yield r
    r.close()


def _rows(repo) -> list[dict]:
    with repo._db.get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM llm_calls ORDER BY seq")]


def _request():
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _status_error(cls, code: int):
    return cls("x", response=httpx.Response(code, request=_request()), body=None)


# ── classify_llm_error ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "exc, code",
    [
        (openai.APITimeoutError(request=_request()), "LLM_TIMEOUT"),
        (TimeoutError(), "LLM_TIMEOUT"),
        (httpx.ReadTimeout("t"), "LLM_TIMEOUT"),
        (_status_error(openai.RateLimitError, 429), "LLM_RATE_LIMITED"),
        (_status_error(openai.InternalServerError, 500), "LLM_UNAVAILABLE"),
        (openai.APIConnectionError(request=_request()), "LLM_UNAVAILABLE"),
        (_status_error(openai.AuthenticationError, 401), "LLM_AUTH"),
        (_status_error(openai.BadRequestError, 400), "LLM_REJECTED"),
        (json.JSONDecodeError("x", "", 0), "LLM_BAD_RESPONSE"),
        (ValueError("lain"), "LLM_ERROR"),
    ],
)
def test_classify_llm_error(exc, code):
    assert classify_llm_error(exc) == code


def test_classify_follows_cause_chain():
    try:
        try:
            raise _status_error(openai.RateLimitError, 429)
        except openai.RateLimitError as inner:
            raise RuntimeError("dibungkus") from inner
    except RuntimeError as outer:
        assert classify_llm_error(outer) == "LLM_RATE_LIMITED"


# ── Recorder ──────────────────────────────────────────────────────────

def test_success_and_failure_are_written_with_context(rec, repo):
    token = _request_id_var.set("req-7")
    try:
        with log_context.scoped(message_id="m-42", version_id="v1"):
            with rec.track("router", "gpt-x") as call:
                call.usage(input_tokens=10, output_tokens=3)
            with pytest.raises(TimeoutError):
                with rec.track("nl2sql", "gpt-y"):
                    raise TimeoutError()
    finally:
        _request_id_var.reset(token)
    rec.flush()

    ok, failed = _rows(repo)
    assert (ok["purpose"], ok["model"], ok["status"], ok["input_tokens"], ok["output_tokens"]) == (
        "router", "gpt-x", "ok", 10, 3,
    )
    assert (ok["request_id"], ok["message_id"], ok["version_id"]) == ("req-7", "m-42", "v1")
    assert (failed["status"], failed["error_code"], failed["input_tokens"]) == (
        "error", "LLM_TIMEOUT", None,
    )
    assert ok["latency_ms"] >= 0


def test_repository_failure_never_breaks_the_ai_call(rec, repo, caplog):
    def boom(calls):
        raise RuntimeError("disk penuh")

    repo.insert_many = boom
    with rec.track("router", "m"):
        result = "jawaban"
    rec.flush()
    assert result == "jawaban"
    assert "Failed to write" in caplog.text


def test_context_survives_to_thread_and_collect_sees_child_tasks(rec, repo):
    def sync_embed():
        with rec.track("embedding", "emb"):
            return [0.1]

    async def router_call():
        with rec.track("router", "r"):
            await asyncio.sleep(0)

    async def main():
        with log_context.scoped(message_id="m-5"), rec.collect() as calls:
            await asyncio.gather(asyncio.to_thread(sync_embed), router_call())
        return calls

    calls = asyncio.run(main())
    rec.flush()
    assert sorted(c.purpose for c in calls) == ["embedding", "router"]
    assert {r["message_id"] for r in _rows(repo)} == {"m-5"}


def test_last_calls_tracks_latest_status_per_purpose(rec):
    with rec.track("synthesizer", "m"):
        pass
    with pytest.raises(ValueError):
        with rec.track("synthesizer", "m"):
            raise ValueError()
    last = rec.last_calls()["synthesizer"]
    assert (last.status, last.error_code) == ("error", "LLM_ERROR")


def test_without_repository_only_memory_is_updated():
    r = LLMCallRecorder()
    with r.track("title", "m"):
        pass
    assert r.last_calls()["title"].status == "ok"
    r.close()


def test_purge_older_than(repo):
    old = datetime.now(UTC) - timedelta(days=91)
    recent = datetime.now(UTC) - timedelta(days=1)
    repo.insert_many([
        LLMCall(purpose="router", model="m", latency_ms=1, status="ok", ts=old),
        LLMCall(purpose="router", model="m", latency_ms=1, status="ok", ts=recent),
    ])
    assert repo.purge_older_than(90) == 1
    assert len(_rows(repo)) == 1


def test_list_for_message(repo):
    repo.insert_many([
        LLMCall(purpose="router", model="m", latency_ms=1, status="ok", message_id="m-1", input_tokens=4),
        LLMCall(purpose="router", model="m", latency_ms=1, status="ok", message_id="m-2"),
    ])
    calls = repo.list_for_message("m-1")
    assert [c.input_tokens for c in calls] == [4]


# ── OpenAILLM carries purpose & tokens ───────────────────────────────

class _FakeResponse:
    content = "halo"
    usage_metadata = {"input_tokens": 7, "output_tokens": 2}


class _FakeChat:
    async def ainvoke(self, messages):
        return _FakeResponse()


def test_openai_llm_records_purpose_and_usage(monkeypatch):
    llm = OpenAILLM(api_key="sk-test", model="gpt-test", purpose="router")
    llm._client = _FakeChat()

    async def main():
        with recorder.collect() as calls:
            assert await llm.ainvoke("p") == "halo"
        return calls

    (call,) = asyncio.run(main())
    assert (call.purpose, call.model, call.input_tokens, call.output_tokens) == (
        "router", "gpt-test", 7, 2,
    )
