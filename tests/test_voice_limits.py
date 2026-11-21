"""STT: audio is read in chunks and rejected when over the limit."""
from __future__ import annotations

import dataclasses

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import voice
from app.core.config import AppConfig
from app.core.dependencies import get_current_user, get_voice_service
from app.core.errors import AuthenticationError, register_exception_handlers
from app.services.user.model import CurrentUser

USER = CurrentUser(id="u1", email="a@corp.com", name="A", given_name="", picture="", is_admin=False)


class FakeVoice:
    def __init__(self, error: BaseException | None = None):
        self.error = error
        self.requests = []

    async def speech_to_text(self, audio_bytes, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return {"text": f"{len(audio_bytes)} bytes"}


def _client(monkeypatch, mb: int, service: FakeVoice | None = None, user=USER) -> TestClient:
    monkeypatch.setattr(voice, "app_config", dataclasses.replace(AppConfig(), STT_MAX_MB=mb))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(voice.router)
    app.dependency_overrides[get_voice_service] = lambda: service or FakeVoice()

    def current_user():
        if user is None:
            raise AuthenticationError()
        return user

    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app)


def test_audio_within_limit(monkeypatch):
    r = _client(monkeypatch, 1).post(
        "/api/v1/voice/stt", files={"audio": ("a.webm", b"x" * 1000, "audio/webm")}
    )
    assert r.status_code == 200 and r.json()["text"] == "1000 bytes"


def test_audio_too_large(monkeypatch):
    r = _client(monkeypatch, 1).post(
        "/api/v1/voice/stt", files={"audio": ("a.webm", b"x" * (1024 * 1024 + 1), "audio/webm")}
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "AUDIO_TOO_LARGE"


def _post(client, data=b"x", ctype="audio/webm"):
    return client.post("/api/v1/voice/stt", files={"audio": ("a.webm", data, ctype)})


def test_unsupported_and_empty_audio_use_error_contract(monkeypatch):
    client = _client(monkeypatch, 1)
    r = _post(client, ctype="text/plain")
    assert r.status_code == 415 and r.json()["error"]["code"] == "AUDIO_UNSUPPORTED"
    r = _post(client, data=b"")
    assert r.status_code == 400 and r.json()["error"]["code"] == "AUDIO_EMPTY"


def test_provider_failure_is_503_without_details(monkeypatch):
    from app.services.voice.exceptions import STTError, UnsupportedLanguageError

    r = _post(_client(monkeypatch, 1, FakeVoice(STTError("OpenAI STT failed: sk-secret"))))
    assert r.status_code == 503 and r.json()["error"]["code"] == "VOICE_UNAVAILABLE"
    assert "sk-secret" not in r.text

    r = _post(_client(monkeypatch, 1, FakeVoice(UnsupportedLanguageError("xx", "openai", ["id"]))))
    assert r.status_code == 400 and r.json()["error"]["code"] == "VOICE_UNSUPPORTED"


def test_language_is_detected_automatically_unless_given(monkeypatch):
    service = FakeVoice()
    client = _client(monkeypatch, 1, service)
    _post(client)
    client.post("/api/v1/voice/stt?language=en", files={"audio": ("a.webm", b"x", "audio/webm")})
    assert [r.language for r in service.requests] == [None, "en"]


class _FakeTranscriptions:
    def __init__(self):
        self.kwargs = []

    async def create(self, **kwargs):
        self.kwargs.append(kwargs)
        return type("R", (), {"text": "halo", "language": "indonesian", "segments": []})()


async def test_openai_stt_omits_language_when_auto():
    from types import SimpleNamespace

    from app.services.voice.model import STTRequest
    from app.services.voice.providers.openai_stt import OpenAISTTProvider

    calls = _FakeTranscriptions()
    provider = object.__new__(OpenAISTTProvider)
    provider._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=calls))

    result = await provider.transcribe(b"x", STTRequest())
    assert "language" not in calls.kwargs[0] and "prompt" not in calls.kwargs[0]
    assert result.language == "indonesian"

    await provider.transcribe(b"x", STTRequest(language="en"))
    assert calls.kwargs[1]["language"] == "en"


def test_voice_requires_login(monkeypatch):
    service = FakeVoice()
    client = _client(monkeypatch, 1, service, user=None)
    r = _post(client)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    r = client.post("/api/v1/voice/tts", json={"text": "halo"})
    assert r.status_code == 401
