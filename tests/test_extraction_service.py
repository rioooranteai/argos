"""Tests for ExtractionService.

Notably regression-tests the f.model_dump bug (method ref vs call) that
silently broke feature persistence before this PR.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.extraction.models import CompetitorFeature
from app.services.extraction.service import ExtractionService


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
    """Three valid chunks above the 80-char minimum."""
    base = "Scopely menerbitkan banyak game dengan revenue tinggi di 2023. " * 3
    return [base, base, base]


class TestExtractionService:

    @pytest.mark.asyncio
    async def test_persists_extracted_features_as_dicts(
        self, fake_features, long_chunks
    ):
        """Regression: previously `f.model_dump` (method ref, no parens) was
        passed to the DB layer, which then crashed on `.get()`. Verify dicts
        with the expected keys are persisted."""
        provider_mock = MagicMock()

        async def _extract(_text):
            return fake_features

        provider_mock.extract = _extract

        with patch(
            "app.services.extraction.service.ExtractionFactory.create",
            return_value=provider_mock,
        ), patch("app.services.extraction.service.db") as db_mock:
            service = ExtractionService(provider="pydantic_ai")
            result = await service.process_document_texts(
                document_id="doc-1",
                chunks_text=long_chunks,
            )

        assert result["status"] == "success"
        assert result["total_features_extracted"] == 2

        db_mock.insert_features_batch.assert_called_once()
        passed_features, passed_doc_id = db_mock.insert_features_batch.call_args.args
        assert passed_doc_id == "doc-1"
        assert len(passed_features) == 2
        # Critical: items must be dicts (post-bugfix), not bound-method objects
        for f in passed_features:
            assert isinstance(f, dict)
            assert "competitor_name" in f
            assert "feature_name" in f

    @pytest.mark.asyncio
    async def test_skips_short_chunks(self):
        provider_mock = MagicMock()

        async def _extract(_text):
            return []

        provider_mock.extract = _extract

        with patch(
            "app.services.extraction.service.ExtractionFactory.create",
            return_value=provider_mock,
        ), patch("app.services.extraction.service.db"):
            service = ExtractionService(provider="pydantic_ai")
            result = await service.process_document_texts(
                document_id="doc-2",
                chunks_text=["short", "  ", ""],  # all under 80 chars
            )

        assert result["status"] == "failed"
        assert result["total_features_extracted"] == 0

    @pytest.mark.asyncio
    async def test_filters_features_with_missing_required_fields(
        self, long_chunks
    ):
        provider_mock = MagicMock()

        async def _extract(_text):
            return [
                CompetitorFeature(competitor_name="Valid", feature_name="X"),
                CompetitorFeature(competitor_name="", feature_name="Y"),       # filtered
                CompetitorFeature(competitor_name="Z", feature_name=""),       # filtered
            ]

        provider_mock.extract = _extract

        with patch(
            "app.services.extraction.service.ExtractionFactory.create",
            return_value=provider_mock,
        ), patch("app.services.extraction.service.db") as db_mock:
            service = ExtractionService(provider="pydantic_ai")
            result = await service.process_document_texts(
                document_id="doc-3",
                chunks_text=long_chunks,
            )

        assert result["total_features_extracted"] == 1
        passed_features, _ = db_mock.insert_features_batch.call_args.args
        assert len(passed_features) == 1

    @pytest.mark.asyncio
    async def test_extraction_error_returns_failed(self, long_chunks):
        """Regression: previously returned status=success even on failure."""
        provider_mock = MagicMock()

        async def _boom(_text):
            raise RuntimeError("LLM exploded")

        provider_mock.extract = _boom

        with patch(
            "app.services.extraction.service.ExtractionFactory.create",
            return_value=provider_mock,
        ), patch("app.services.extraction.service.db") as db_mock:
            service = ExtractionService(provider="pydantic_ai")
            result = await service.process_document_texts(
                document_id="doc-4",
                chunks_text=long_chunks,
            )

        assert result["status"] == "failed"
        assert result["total_features_extracted"] == 0
        db_mock.insert_features_batch.assert_not_called()


