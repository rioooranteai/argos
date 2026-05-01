"""Tests for NL2SQLService — verifies orchestration of LLM, validator, executor."""
from __future__ import annotations

from pathlib import Path
from typing import Type
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from app.infrastructure.interface.llm import BaseLLM
from app.services.nl2sql.service import NL2SQLService

_FAKE_DB_PATH = Path("/tmp/argos_test_unused.db")


@pytest.fixture(autouse=True)
def _stub_schema_introspection():
    """Avoid touching the filesystem for the schema PRAGMA introspection;
    the actual DDL is irrelevant for these orchestration tests."""
    with patch(
        "app.services.nl2sql.service._introspect_features_schema",
        return_value="CREATE TABLE features (id INTEGER);",
    ):
        yield


class FakeLLM(BaseLLM):
    """In-memory LLM stub for deterministic testing."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def invoke(self, prompt: str, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system, "mode": "sync"})
        return self._responses.pop(0)

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system, "mode": "async"})
        return self._responses.pop(0)

    def with_structured_output(self, schema: Type[BaseModel]) -> "BaseLLM":
        return self


@pytest.fixture
def fake_rows():
    return [
        {"brand_name": "Scopely", "product_name": "MONOPOLY GO!", "price": None,
         "price_currency": None,
         "advantages": "Top revenue 2023", "disadvantages": None}
    ]


class TestNL2SQLServiceProcessQuery:
    @pytest.mark.asyncio
    async def test_happy_path(self, fake_rows):
        llm = FakeLLM(responses=[
            "SELECT * FROM features WHERE brand_name = 'Scopely'",  # SQL gen
            "Scopely unggul di MONOPOLY GO!",                            # final answer
        ])
        service = NL2SQLService(llm_provider=llm, db_path=_FAKE_DB_PATH)

        with patch(
            "app.services.nl2sql.service.execute_readonly_sql",
            return_value=fake_rows,
        ):
            result = await service.process_query("Apa kelebihan Scopely?")

        assert result["status"] == "success"
        assert "Scopely" in result["answer"]
        assert result["sql_query"].startswith("SELECT")
        assert result["row_count"] == 1
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_invalid_question_returns_friendly_message(self):
        llm = FakeLLM(responses=["INVALID_QUESTION"])
        service = NL2SQLService(llm_provider=llm, db_path=_FAKE_DB_PATH)

        result = await service.process_query("What's the weather today?")

        assert result["status"] == "success"
        assert result["sql_query"] is None
        assert "tidak relevan" in result["answer"].lower()

    @pytest.mark.asyncio
    async def test_destructive_user_input_blocked(self):
        llm = FakeLLM(responses=[])  # LLM should never be called
        service = NL2SQLService(llm_provider=llm, db_path=_FAKE_DB_PATH)

        result = await service.process_query("drop table features")

        assert result["status"] == "error"
        assert len(llm.calls) == 0  # blocked before reaching LLM

    @pytest.mark.asyncio
    async def test_destructive_llm_output_blocked(self):
        # LLM goes rogue and returns DROP — validator must catch it
        llm = FakeLLM(responses=["DROP TABLE features"])
        service = NL2SQLService(llm_provider=llm, db_path=_FAKE_DB_PATH)

        with patch(
            "app.services.nl2sql.service.execute_readonly_sql"
        ) as mock_exec:
            result = await service.process_query("Show me competitors")
            mock_exec.assert_not_called()  # never reached executor

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_sql_codeblock_stripped(self, fake_rows):
        llm = FakeLLM(responses=[
            "```sql\nSELECT * FROM features\n```",
            "Hasil ditemukan.",
        ])
        service = NL2SQLService(llm_provider=llm, db_path=_FAKE_DB_PATH)

        with patch(
            "app.services.nl2sql.service.execute_readonly_sql",
            return_value=fake_rows,
        ):
            result = await service.process_query("Tampilkan semua")

        assert result["status"] == "success"
        assert "```" not in result["sql_query"]

    @pytest.mark.asyncio
    async def test_truncation_at_max_rows(self):
        llm = FakeLLM(responses=[
            "SELECT * FROM features",
            "Banyak data ditemukan.",
        ])
        service = NL2SQLService(llm_provider=llm, db_path=_FAKE_DB_PATH)
        many_rows = [{"brand_name": f"X{i}"} for i in range(150)]

        with patch(
            "app.services.nl2sql.service.execute_readonly_sql",
            return_value=many_rows,
        ):
            result = await service.process_query("Tampilkan semua")

        assert result["truncated"] is True
        assert result["row_count"] == 150
        assert len(result["raw_data"]) == 100  # MAX_RAW_ROWS

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_generic_message(self):
        llm = FakeLLM(responses=[
            "SELECT * FROM features",
            "...",
        ])
        service = NL2SQLService(llm_provider=llm, db_path=_FAKE_DB_PATH)

        with patch(
            "app.services.nl2sql.service.execute_readonly_sql",
            side_effect=RuntimeError("DB connection lost"),
        ):
            result = await service.process_query("Tampilkan semua")

        assert result["status"] == "error"
        # Message should not leak internal details
        assert "DB connection" not in result["message"]
