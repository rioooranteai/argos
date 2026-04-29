"""Tests for app config & CORS origin parsing."""
from __future__ import annotations

import pytest

from app.core.config import Config


class TestCORSOrigins:
    def test_default_localhost(self):
        c = Config()
        origins = c.cors_origins
        assert "http://localhost:8000" in origins
        assert "http://localhost:3000" in origins
        assert "*" not in origins

    def test_single_origin(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://argos.example.com")
        c = Config()
        assert c.cors_origins == ["https://argos.example.com"]

    def test_multiple_origins_with_whitespace(self, monkeypatch):
        monkeypatch.setenv(
            "ALLOWED_ORIGINS",
            "https://a.com, https://b.com ,  https://c.com",
        )
        c = Config()
        assert c.cors_origins == ["https://a.com", "https://b.com", "https://c.com"]

    def test_empty_strings_filtered(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.com,,,")
        c = Config()
        assert c.cors_origins == ["https://a.com"]
