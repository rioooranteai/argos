"""STT: audio dibaca bertahap dan ditolak bila melebihi batas."""
from __future__ import annotations

import dataclasses

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import voice
from app.core.config import AppConfig
from app.core.dependencies import get_voice_service
from app.core.errors import register_exception_handlers


class FakeVoice:
    async def speech_to_text(self, audio_bytes, request):
        return {"text": f"{len(audio_bytes)} bytes"}


def _client(monkeypatch, mb: int) -> TestClient:
    monkeypatch.setattr(voice, "app_config", dataclasses.replace(AppConfig(), STT_MAX_MB=mb))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(voice.router)
    app.dependency_overrides[get_voice_service] = lambda: FakeVoice()
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
