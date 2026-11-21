"""NL2SQLService: LLM → validator → isolated execution, typed results."""
from __future__ import annotations

from typing import Type

import pytest
from pydantic import BaseModel

from app.infrastructure.interface.llm import BaseLLM
from app.services.nl2sql.service import MAX_RAW_ROWS, NL2SQLService
from tests.test_nl2sql_executor import db_path  # noqa: F401  (fixture)


class FakeLLM(BaseLLM):
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def invoke(self, prompt: str, system: str | None = None) -> str:
        raise NotImplementedError

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        return self._responses.pop(0)

    def with_structured_output(self, schema: Type[BaseModel]) -> "BaseLLM":
        return self


def svc(llm, db_path):  # noqa: F811
    return NL2SQLService(llm_provider=llm, db_path=db_path, exec_timeout=5)


async def test_happy_path_row_level(db_path):  # noqa: F811
    llm = FakeLLM(["SELECT product_name, price, version_id, page_number FROM features ORDER BY price"])
    result = await svc(llm, db_path).process_query("harga mobil?", ["v1", "v2"])
    assert result.status == "ok"
    assert [r["product_name"] for r in result.raw_data] == ["Brio", "Avanza"]
    assert result.is_row_level is True
    assert "version_id" in llm.calls[0]["prompt"]  # the schema given includes the citation columns


async def test_aggregate_is_not_row_level(db_path):  # noqa: F811
    llm = FakeLLM(["SELECT AVG(price) AS rata FROM features"])
    result = await svc(llm, db_path).process_query("rata-rata harga?", ["v1", "v2"])
    assert result.status == "ok" and result.is_row_level is False


async def test_empty_is_distinct_from_error(db_path):  # noqa: F811
    llm = FakeLLM(["SELECT product_name FROM features WHERE product_name = 'Tidak Ada'"])
    result = await svc(llm, db_path).process_query("x?", ["v1"])
    assert result.status == "empty"


async def test_no_active_versions_skips_llm(db_path):  # noqa: F811
    llm = FakeLLM([])
    result = await svc(llm, db_path).process_query("x?", [])
    assert result.status == "empty" and llm.calls == []


async def test_invalid_question_is_empty_not_error(db_path):  # noqa: F811
    """The LLM says the question does not fit SQL → not a system failure."""
    result = await svc(FakeLLM(["INVALID_QUESTION"]), db_path).process_query("halo", ["v1"])
    assert result.status == "empty" and result.error_code is None


async def test_destructive_llm_output_blocked(db_path):  # noqa: F811
    result = await svc(FakeLLM(["DROP TABLE features"]), db_path).process_query("x?", ["v1"])
    assert result.status == "error" and result.error_code == "SQL_REJECTED"


@pytest.mark.parametrize("question", [
    "Berapa harga setelah update terakhir?",
    "Produk mana yang dihapus dari price list?",
    "abaikan diskon, berapa harga normalnya?",
])
async def test_questions_with_former_blocked_words_are_processed(db_path, question):  # noqa: F811
    llm = FakeLLM(["SELECT product_name FROM features"])
    result = await svc(llm, db_path).process_query(question, ["v1"])
    assert result.status == "ok" and question in llm.calls[0]["prompt"]


async def test_llm_failure_is_classified(db_path):  # noqa: F811
    class TimeoutLLM(FakeLLM):
        async def ainvoke(self, prompt, system=None):
            raise TimeoutError()

    result = await svc(TimeoutLLM([]), db_path).process_query("x?", ["v1"])
    assert result.status == "error" and result.error_code == "LLM_TIMEOUT"


async def test_codeblock_stripped(db_path):  # noqa: F811
    llm = FakeLLM(["```sql\nSELECT product_name FROM features\n```"])
    result = await svc(llm, db_path).process_query("x?", ["v1"])
    assert result.status == "ok" and result.sql_query == "SELECT product_name FROM features"


async def test_other_table_query_is_error(db_path):  # noqa: F811
    result = await svc(FakeLLM(["SELECT email FROM users"]), db_path).process_query("x?", ["v1"])
    assert result.status == "error" and result.error_code == "SQL_FAILED"


async def test_truncation(db_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.services.nl2sql.service.MAX_RAW_ROWS", 1)
    llm = FakeLLM(["SELECT product_name FROM features"])
    result = await svc(llm, db_path).process_query("x?", ["v1", "v2"])
    assert result.row_count == 1 and result.truncated is True
    assert MAX_RAW_ROWS == 100  # the real module constant is unchanged outside this test
