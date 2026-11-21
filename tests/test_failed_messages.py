"""Failed messages & resend (DESIGN_GROUP_C.md §4).

The ChatEngine is real; failures come from its fake tools, the way they happen in
production: every source failing → 503, a slow answer → 504, a storage failure → 500.
"""
from __future__ import annotations

import pytest

from tests.test_notebook_api import (  # noqa: F401 (fixture)
    BOB,
    CHAT_TIMEOUT_SECONDS,
    _publish,
    _setup_notebook,
    env,
)


@pytest.fixture
def chat(env):  # noqa: F811
    client, db, tools, state = env
    nb, up = _setup_notebook(client)
    _publish(db, up["results"][0]["version_id"])
    return client, db, tools, nb["id"], state


def _send(client, nb_id, question, conversation_id=None):
    body = {"question": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return client.post(f"/api/v1/notebooks/{nb_id}/messages", json=body)


def _messages(client, nb_id, conv_id):
    return client.get(f"/api/v1/notebooks/{nb_id}/conversations/{conv_id}").json()["messages"]


def _history_lines(prompt: str) -> list[str]:
    """The conversation lines the synthesizer received (one per message)."""
    history = prompt.split("Conversation history:\n", 1)[1].split("\n\n", 1)[0]
    return [line for line in history.splitlines() if line]


def test_failure_marks_user_message_and_returns_ids(chat):
    client, _, tools, nb_id, _ = chat
    tools.router.response = '{"route": "both", "reasoning": "x"}'
    tools.fail_retrieval()

    r = _send(client, nb_id, "harga avanza?")
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "UPSTREAM_UNAVAILABLE" and err["retryable"] is True
    conv_id, msg_id = err["details"]["conversation_id"], err["details"]["message_id"]
    assert sorted(i["component"] for i in err["details"]["issues"]) == ["sql", "vector"]
    assert {i["code"] for i in err["details"]["issues"]} == {"LLM_TIMEOUT"}

    msgs = _messages(client, nb_id, conv_id)
    assert [(m["id"], m["role"], m["status"], m["error_code"]) for m in msgs] == [
        (msg_id, "user", "failed", "UPSTREAM_UNAVAILABLE")
    ]


def test_timeout_and_unexpected_errors_are_marked_too(chat, monkeypatch):
    client, _, tools, nb_id, _ = chat
    tools.synth.delay = CHAT_TIMEOUT_SECONDS + 0.5
    r1 = _send(client, nb_id, "a")
    assert r1.status_code == 504
    conv_id = r1.json()["error"]["details"]["conversation_id"]

    tools.heal()

    def broken_storage(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(tools.conversations, "append_assistant_message", broken_storage)
    r2 = _send(client, nb_id, "b", conv_id)
    assert r2.status_code == 500
    assert "bug" not in r2.text  # technical details only go to the log
    assert r2.json()["error"]["details"]["conversation_id"] == conv_id

    codes = [m["error_code"] for m in _messages(client, nb_id, conv_id)]
    assert codes == ["CHAT_TIMEOUT", "INTERNAL_ERROR"]


def test_failed_messages_are_not_sent_to_the_llm(chat):
    client, _, tools, nb_id, _ = chat
    tools.fail_retrieval()
    conv_id = _send(client, nb_id, "pertanyaan gagal").json()["error"]["details"]["conversation_id"]

    tools.heal()
    assert _send(client, nb_id, "pertanyaan baru", conv_id).status_code == 200
    assert _history_lines(tools.synth.last_prompt) == ["HUMAN: pertanyaan baru"]


def test_success_stores_trace_and_degraded_flag(chat):
    client, _, tools, nb_id, _ = chat
    tools.router.response = '{"route": "both", "reasoning": "x"}'
    tools.vectors.error = TimeoutError()  # SQL still works → a degraded answer, not a failure
    body = _send(client, nb_id, "harga?").json()
    meta = body["metadata"]
    assert meta["degraded"] is True and meta["issues"] == [{"component": "vector", "code": "LLM_TIMEOUT"}]
    assert len(meta["user_message_id"]) == 36 and len(meta["assistant_message_id"]) == 36  # UUID

    bot = _messages(client, nb_id, body["conversation_id"])[1]
    assert bot["status"] == "ok" and bot["degraded"] is True
    assert bot["trace"]["route"] == "both"


def _retry(client, nb_id, conv_id, msg_id):
    return client.post(f"/api/v1/notebooks/{nb_id}/conversations/{conv_id}/messages/{msg_id}/retry")


def test_retry_reuses_the_failed_row(chat):
    client, _, tools, nb_id, _ = chat
    tools.fail_retrieval()
    err = _send(client, nb_id, "harga?").json()["error"]["details"]
    conv_id, msg_id = err["conversation_id"], err["message_id"]

    tools.heal()
    tools.synth.response = "Akhirnya [1]."
    r = _retry(client, nb_id, conv_id, msg_id)
    assert r.status_code == 200
    assert r.json()["answer"] == "Akhirnya [1]." and r.json()["metadata"]["user_message_id"] == msg_id
    msgs = _messages(client, nb_id, conv_id)
    assert [(m["id"] == msg_id, m["role"], m["status"]) for m in msgs] == [
        (True, "user", "ok"), (False, "assistant", "ok"),
    ]
    # The resent question is in the engine history exactly once.
    assert _history_lines(tools.synth.last_prompt) == ["HUMAN: harga?"]


def test_retry_that_fails_again_stays_failed(chat):
    client, _, tools, nb_id, _ = chat
    tools.fail_retrieval()
    err = _send(client, nb_id, "x").json()["error"]["details"]

    tools.heal()
    tools.synth.delay = CHAT_TIMEOUT_SECONDS + 0.5
    r = _retry(client, nb_id, err["conversation_id"], err["message_id"])
    assert r.status_code == 504
    assert _messages(client, nb_id, err["conversation_id"])[0]["error_code"] == "CHAT_TIMEOUT"


def test_retry_rules(chat):
    client, _, tools, nb_id, state = chat
    tools.fail_retrieval()
    err = _send(client, nb_id, "gagal").json()["error"]["details"]
    conv_id, failed_id = err["conversation_id"], err["message_id"]
    tools.heal()
    ok = _send(client, nb_id, "berhasil", conv_id).json()

    # Not the last message
    r = _retry(client, nb_id, conv_id, failed_id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "MESSAGE_NOT_LATEST"
    # A message that did not fail
    r = _retry(client, nb_id, conv_id, ok["metadata"]["user_message_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "MESSAGE_NOT_FAILED"
    # An assistant message / missing
    r = _retry(client, nb_id, conv_id, ok["metadata"]["assistant_message_id"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert _retry(client, nb_id, conv_id, "00000000-0000-4000-8000-000000000000").status_code == 404
    # Owned by another user
    state["user"] = BOB
    assert _retry(client, nb_id, conv_id, failed_id).status_code == 404
