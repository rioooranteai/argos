"""Tests for ExtractionService.

Notably regression-tests the f.model_dump bug (method ref vs call) that
silently broke feature persistence before this refactor.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.extraction.base.repository import BaseFeatureRepository
from app.services.extraction.models import CompetitorFeature
from app.services.extraction.service import ExtractionService


class FakeFeatureRepository(BaseFeatureRepository):
    """In-memory repository for deterministic tests."""

    def __init__(self):
        self.calls: list[tuple[list[dict], str]] = []

    def insert_batch(self, features: list[dict], document_id: str) -> None:
        self.calls.append((features, document_id))


@pytest.fixture
def fake_features() -> list[CompetitorFeature]:
    return [
        CompetitorFeature(
            competitor_name="Scopely",
            feature_name="MONOPOLY GO!",
            price=None,
            advantages="$1.2B revenue 2023",
            disadvantages=None,
        ),
        CompetitorFeature(
            competitor_name="King",
            feature_name="Candy Crush",
            price=0.99,
            advantages="Massive DAU",
            disadvantages="Ageing IP",
        ),
    ]


@pytest.fixture
def long_chunks():
    base = "Scopely menerbitkan banyak game dengan revenue tinggi di 2023. " * 3
    return [base, base, base]


def _build_service(extract_fn) -> tuple[ExtractionService, FakeFeatureRepository]:
    provider_mock = MagicMock()
    provider_mock.extract = extract_fn
    repo = FakeFeatureRepository()
    with patch(
        "app.services.extraction.service.ExtractionFactory.create",
        return_value=provider_mock,
    ):
        service = ExtractionService(repository=repo, provider="pydantic_ai")
    return service, repo


class TestExtractionService:

    @pytest.mark.asyncio
    async def test_persists_extracted_features_as_dicts(
        self, fake_features, long_chunks
    ):
        """Regression: previously `f.model_dump` (method ref, no parens) was
        passed to the persistence layer. Verify dicts are passed instead."""
        async def _extract(_text):
            return fake_features

        service, repo = _build_service(_extract)
        result = await service.process_document_texts(
            document_id="doc-1",
            chunks_text=long_chunks,
        )

        assert result["status"] == "success"
        assert result["total_features_extracted"] == 2
        assert len(repo.calls) == 1
        passed_features, doc_id = repo.calls[0]
        assert doc_id == "doc-1"
        for f in passed_features:
            assert isinstance(f, dict)
            assert "competitor_name" in f
            assert "feature_name" in f

    @pytest.mark.asyncio
    async def test_skips_short_chunks(self):
        async def _extract(_text):
            return []

        service, repo = _build_service(_extract)
        result = await service.process_document_texts(
            document_id="doc-2",
            chunks_text=["short", "  ", ""],
        )

        assert result["status"] == "failed"
        assert result["total_features_extracted"] == 0
        assert repo.calls == []

    @pytest.mark.asyncio
    async def test_filters_features_with_missing_required_fields(
        self, long_chunks
    ):
        async def _extract(_text):
            return [
                CompetitorFeature(competitor_name="Valid", feature_name="X"),
                CompetitorFeature(competitor_name="", feature_name="Y"),  # filtered
                CompetitorFeature(competitor_name="Z", feature_name=""),  # filtered
            ]

        service, repo = _build_service(_extract)
        result = await service.process_document_texts(
            document_id="doc-3",
            chunks_text=long_chunks,
        )

        assert result["total_features_extracted"] == 1
        passed_features, _ = repo.calls[0]
        assert len(passed_features) == 1
        assert passed_features[0]["competitor_name"] == "Valid"

    @pytest.mark.asyncio
    async def test_extraction_error_returns_failed(self, long_chunks):
        """Regression: previously returned status=success even on failure."""
        async def _boom(_text):
            raise RuntimeError("LLM exploded")

        service, repo = _build_service(_boom)
        result = await service.process_document_texts(
            document_id="doc-4",
            chunks_text=long_chunks,
        )

        assert result["status"] == "failed"
        assert result["total_features_extracted"] == 0
        assert repo.calls == []
