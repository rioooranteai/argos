"""Chat saat sebagian / seluruh komponen gagal (DESIGN_GROUP_C.md §3)."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.core.errors import UpstreamError
from app.engines.chat_engine.engine import ChatEngine
from app.services.nl2sql.service import NL2SQLResult
from app.services.notebook.model import ActiveSource
from app.services.vector_store.model import SearchHit

SOURCES = [ActiveSource("v1", "d1", "Pricelist", 1, datetime(2026, 1, 1))]
SQL_OK = NL2SQLResult(
    status="ok",
    sql_query="SELECT product_name, price, version_id, page_number FROM features",
    raw_data=[{"product_name": "Avanza", "price": 230.0, "version_id": "v1", "page_number": 4}],
    row_count=1,
)


class LLM:
    def __init__(self, text="Avanza Rp 230 jt [1].", error: BaseException | None = None):
        self.text, self.error, self.prompts = text, error, []

    async def ainvoke(self, prompt, system=None):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.text

    def invoke(self, prompt, system=None):  # pragma: no cover
        raise NotImplementedError

    def with_structured_output(self, schema):  # pragma: no cover
        return self


class NL2SQL:
    def __init__(self, result: NL2SQLResult):
        self.result, self.called = result, False

    async def process_query(self, q, version_ids):
        self.called = True
        return self.result


class Vectors:
    def __init__(self, hits=None, error: BaseException | None = None):
        self.hits, self.error, self.called = hits or [], error, False

    def search(self, query, version_ids, limit=5):
        self.called = True
        if self.error is not None:
            raise self.error
        return self.hits


def engine(route="both", synth=None, sql=None, vectors=None, router=None):
    synth = synth or LLM()
    return ChatEngine(
        llm=synth,
        router_llm=router or LLM(f'{{"route": "{route}", "reasoning": "x"}}'),
        nl2sql_svc=sql or NL2SQL(SQL_OK),
        vector_svc=vectors or Vectors([SearchHit("c1", "Veloz", 0.2, {"version_id": "v1", "page_number": 2})]),
    ), synth


async def test_all_ok_is_not_degraded():
    eng, _ = engine()
    out = await eng.chat("harga?", sources=SOURCES)
    assert out.degraded is False and out.issues == []
    assert out.trace["issues"] == []


async def test_router_failure_falls_back_to_both_and_is_reported():
    sql, vectors = NL2SQL(SQL_OK), Vectors()
    eng, _ = engine(router=LLM(error=TimeoutError()), sql=sql, vectors=vectors)
    out = await eng.chat("harga?", sources=SOURCES)
    assert out.route == "both" and sql.called and vectors.called
    assert out.degraded is True
    assert [i.to_dict() for i in out.issues] == [{"component": "router", "code": "ROUTER_FAILED"}]


async def test_router_invalid_json_is_router_failure():
    eng, _ = engine(router=LLM("bukan json"))
    out = await eng.chat("harga?", sources=SOURCES)
    assert out.route == "both" and out.trace["router"]["code"] == "ROUTER_FAILED"


async def test_partial_failure_answers_with_explicit_note():
    eng, synth = engine(vectors=Vectors(error=TimeoutError()))
    out = await eng.chat("harga?", sources=SOURCES)
    assert out.answer == "Avanza Rp 230 jt [1]."
    assert out.degraded is True
    assert [i.to_dict() for i in out.issues] == [{"component": "vector", "code": "LLM_TIMEOUT"}]
    assert "FAILED to load because of a system problem: Document search" in synth.prompts[0]
    assert out.trace["vector"] == {"status": "error", "duration_ms": out.trace["vector"]["duration_ms"],
                                   "code": "LLM_TIMEOUT"}


async def test_vector_store_failure_code():
    eng, _ = engine(route="vector", vectors=Vectors(error=RuntimeError("chroma mati")))
    with pytest.raises(UpstreamError) as exc:
        await eng.chat("x", sources=SOURCES)
    assert exc.value.details["issues"] == [{"component": "vector", "code": "VECTOR_STORE_FAILED"}]


async def test_all_sources_failed_skips_synthesizer():
    sql = NL2SQL(NL2SQLResult(status="error", error_code="SQL_TIMEOUT"))
    eng, synth = engine(sql=sql, vectors=Vectors(error=TimeoutError()))
    with pytest.raises(UpstreamError) as exc:
        await eng.chat("harga?", sources=SOURCES)
    assert exc.value.code == "UPSTREAM_UNAVAILABLE" and exc.value.http_status == 503
    assert sorted(i["component"] for i in exc.value.details["issues"]) == ["sql", "vector"]
    assert synth.prompts == []


async def test_synthesizer_failure_raises_instead_of_fake_answer():
    eng, _ = engine(synth=LLM(error=TimeoutError()))
    with pytest.raises(UpstreamError) as exc:
        await eng.chat("harga?", sources=SOURCES)
    assert exc.value.details["issues"] == [{"component": "synthesizer", "code": "LLM_TIMEOUT"}]


async def test_all_empty_is_normal_not_degraded():
    sql = NL2SQL(NL2SQLResult(status="empty"))
    eng, synth = engine(sql=sql, vectors=Vectors([]))
    out = await eng.chat("harga?", sources=SOURCES)
    assert out.degraded is False
    assert "No data found." in synth.prompts[0]
    assert "GAGAL dibaca" not in synth.prompts[0]
    assert out.trace["sql"]["status"] == "empty" and out.trace["vector"]["status"] == "empty"


async def test_invalid_question_from_nl2sql_is_not_degraded():
    sql = NL2SQL(NL2SQLResult(status="empty", message="Pertanyaan tidak relevan"))
    eng, _ = engine(route="sql", sql=sql)
    out = await eng.chat("halo", sources=SOURCES)
    assert out.degraded is False


async def test_route_none_runs_no_retrieval_and_is_not_an_error():
    sql, vectors = NL2SQL(SQL_OK), Vectors()
    eng, _ = engine(route="none", sql=sql, vectors=vectors)
    out = await eng.chat("halo", sources=SOURCES)
    assert not sql.called and not vectors.called and out.degraded is False
    assert "sql" not in out.trace and "synthesizer" in out.trace
