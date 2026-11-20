"""Pesan gagal & kirim ulang (DESIGN_GROUP_C.md §4)."""
from __future__ import annotations

import pytest

from app.core.dependencies import get_chat_engine
from app.core.errors import UpstreamError, UpstreamTimeout
from app.engines.chat_engine.outcome import ChatResult, NodeIssue
from tests.test_notebook_api import BOB, _publish, _setup_notebook, env  # noqa: F401 (fixture)


class ScriptedEngine:
    """Engine palsu: setiap panggilan mengambil satu langkah dari `script`."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def chat(self, user_input, history=None, sources=None):
        self.calls.append({"q": user_input, "history": [(m.role, m.content) for m in history or []]})
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def _ok(answer="Jawaban [1].", issues=()):
    return ChatResult(
        answer=answer, route="both", router_reasoning="x", citations=[],
        issues=list(issues), trace={"route": "both", "issues": [i.to_dict() for i in issues]},
    )


@pytest.fixture
def chat(env):  # noqa: F811
    client, db, _, state = env
    nb, up = _setup_notebook(client)
    _publish(db, up["results"][0]["version_id"])
    engine = ScriptedEngine([])
    client.app.dependency_overrides[get_chat_engine] = lambda: engine
    return client, db, engine, nb["id"], state


def _send(client, nb_id, question, conversation_id=None):
    body = {"question": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return client.post(f"/api/v1/notebooks/{nb_id}/messages", json=body)


def _messages(client, nb_id, conv_id):
    return client.get(f"/api/v1/notebooks/{nb_id}/conversations/{conv_id}").json()["messages"]


def test_failure_marks_user_message_and_returns_ids(chat):
    client, _, engine, nb_id, _ = chat
    engine.script = [UpstreamError(details={"issues": [{"component": "sql", "code": "SQL_TIMEOUT"}]})]

    r = _send(client, nb_id, "harga avanza?")
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "UPSTREAM_UNAVAILABLE" and err["retryable"] is True
    conv_id, msg_id = err["details"]["conversation_id"], err["details"]["message_id"]
    assert err["details"]["issues"] == [{"component": "sql", "code": "SQL_TIMEOUT"}]

    msgs = _messages(client, nb_id, conv_id)
    assert [(m["id"], m["role"], m["status"], m["error_code"]) for m in msgs] == [
        (msg_id, "user", "failed", "UPSTREAM_UNAVAILABLE")
    ]


def test_timeout_and_unexpected_errors_are_marked_too(chat):
    client, _, engine, nb_id, _ = chat
    engine.script = [UpstreamTimeout(code="CHAT_TIMEOUT"), RuntimeError("bug")]

    r1 = _send(client, nb_id, "a")
    assert r1.status_code == 504
    conv_id = r1.json()["error"]["details"]["conversation_id"]
    r2 = _send(client, nb_id, "b", conv_id)
    assert r2.status_code == 500
    assert "bug" not in r2.text  # detail teknis hanya di log
    assert r2.json()["error"]["details"]["conversation_id"] == conv_id

    codes = [m["error_code"] for m in _messages(client, nb_id, conv_id)]
    assert codes == ["CHAT_TIMEOUT", "INTERNAL_ERROR"]


def test_failed_messages_are_not_sent_to_the_llm(chat):
    client, _, engine, nb_id, _ = chat
    engine.script = [UpstreamError(), _ok()]
    conv_id = _send(client, nb_id, "pertanyaan gagal").json()["error"]["details"]["conversation_id"]

    assert _send(client, nb_id, "pertanyaan baru", conv_id).status_code == 200
    assert engine.calls[1]["history"] == [("user", "pertanyaan baru")]


def test_success_stores_trace_and_degraded_flag(chat):
    client, _, engine, nb_id, _ = chat
    engine.script = [_ok(issues=[NodeIssue("vector", "LLM_TIMEOUT")])]
    body = _send(client, nb_id, "harga?").json()
    meta = body["metadata"]
    assert meta["degraded"] is True and meta["issues"] == [{"component": "vector", "code": "LLM_TIMEOUT"}]
    assert isinstance(meta["user_message_id"], int) and isinstance(meta["assistant_message_id"], int)

    bot = _messages(client, nb_id, body["conversation_id"])[1]
    assert bot["status"] == "ok" and bot["degraded"] is True
    assert bot["trace"]["route"] == "both"
