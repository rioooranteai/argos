"""Tests for the Secrets / Infra / AppConfig split."""
from __future__ import annotations

import dataclasses

import pytest

from app.core.config import AppConfig, Infra, Secrets


def _secrets(**env) -> Secrets:
    # _env_file=None: do not read the developer's real .env during tests.
    return Secrets(_env_file=None, **env)


class TestCORSOrigins:
    def test_default_is_localhost_only(self):
        assert _secrets().cors_origins == ["http://localhost:8000"]

    def test_single_origin(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://argos.example.com")
        assert _secrets().cors_origins == ["https://argos.example.com"]

    def test_multiple_origins_with_whitespace(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.com, https://b.com ,  https://c.com")
        assert _secrets().cors_origins == ["https://a.com", "https://b.com", "https://c.com"]

    def test_empty_strings_filtered(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.com,,,")
        assert _secrets().cors_origins == ["https://a.com"]


class TestSecretsRequired:
    def test_missing_reported(self):
        missing = _secrets().missing_required()
        assert "OPENAI_API_KEY" in missing
        assert "SECRET_KEY" in missing
        assert "ALLOWED_GOOGLE_DOMAIN" in missing
        assert "ADMIN_EMAIL" in missing

    def test_all_filled(self):
        s = _secrets(
            OPENAI_API_KEY="k", GOOGLE_CLIENT_ID="i", GOOGLE_CLIENT_SECRET="s",
            SECRET_KEY="x", ALLOWED_GOOGLE_DOMAIN="corp.com", ADMIN_EMAIL="a@corp.com",
        )
        assert s.missing_required() == []

    def test_domain_and_admin_normalized(self):
        s = _secrets(ALLOWED_GOOGLE_DOMAIN=" Corp.COM ", ADMIN_EMAIL=" Boss@Corp.com ")
        assert s.allowed_domain == "corp.com"
        assert s.admin_email == "boss@corp.com"


class TestInfra:
    def test_paths_derived_from_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        infra = Infra()
        assert infra.sqlite_path == tmp_path / "argos.db"
        assert infra.chroma_path == tmp_path / "chroma"
        assert infra.upload_queue_dir == tmp_path / "queue"

    def test_docling_device_default_auto(self, monkeypatch):
        monkeypatch.delenv("DOCLING_DEVICE", raising=False)
        assert Infra().DOCLING_DEVICE == "auto"


class TestAppConfig:
    def test_not_overridable_by_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_CHAT_MODEL", "should-be-ignored")
        assert AppConfig().OPENAI_CHAT_MODEL != "should-be-ignored"

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            AppConfig().NOTEBOOK_MAX_SOURCES = 99  # type: ignore[misc]
