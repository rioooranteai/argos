"""ExtractionService: per unit, section_ref → section, cache, timeout, concurrency."""
from __future__ import annotations

import asyncio

import pytest

from app.core.database import Database
from app.core.migrations import run_migrations
from app.tools.storage.sqlite.cache import SQLiteCacheRepository
from app.tools.extraction.base import ExtractedFeature
from app.services.extraction.service import ExtractionService
from app.services.ingestion.chunker import build_sections, build_units
from app.tools.document_parser.base import DocumentElement, ElementType


class FakeProvider:
    def __init__(self, fn):
        self.fn = fn
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def extract(self, text: str):
        self.calls.append(text)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            return await self.fn(text)
        finally:
            self.active -= 1


def _units(n: int = 1):
    elements = [
        DocumentElement(
            element_type=ElementType.TEXT, content=f"isi bagian {i} " * 200, page_number=i + 1,
            section_heading=f"H{i}", metadata={"headings": [f"Root{i}", f"H{i}"]},
        )
        for i in range(n)
    ]
    sections = build_sections(elements)
    return sections, build_units(sections, lambda t: len(t.split()), 10, 4000)


@pytest.fixture
def cache(tmp_path):
    db = Database(db_path=tmp_path / "t.db")
    with db.get_connection() as conn:
        run_migrations(conn)
    return SQLiteCacheRepository(db)


def _svc(provider, cache, timeout=5.0, limit=3):
    return ExtractionService(provider, cache, asyncio.Semaphore(limit), "p1", timeout)


async def test_section_ref_maps_to_section(cache):
    sections, units = _units(1)

    async def extract(_):
        return [ExtractedFeature(brand_name="Toyota", product_name=" Avanza ", price=230.0, section_ref="S1")]

    [row] = await _svc(FakeProvider(extract), cache).extract_units(units)
    assert row.section_hash == sections[0].section_hash
    assert row.section_heading == "H0"
    assert row.page_number == 1
    assert row.product_name == "Avanza"


async def test_invalid_ref_falls_back_and_empty_product_dropped(cache):
    sections, units = _units(1)

    async def extract(_):
        return [
            ExtractedFeature(product_name="X", section_ref="S9"),
            ExtractedFeature(product_name="Y", section_ref="[S1]"),
            ExtractedFeature(product_name="  ", section_ref="S1"),
        ]

    rows = await _svc(FakeProvider(extract), cache).extract_units(units)
    assert [r.product_name for r in rows] == ["X", "Y"]
    assert all(r.section_hash == sections[0].section_hash for r in rows)


async def test_no_truncation_every_unit_extracted(cache):
    _, units = _units(5)

    async def extract(_):
        return []

    provider = FakeProvider(extract)
    await _svc(provider, cache).extract_units(units)
    assert len(provider.calls) == len(units) == 5


async def test_cache_skips_llm_on_second_run(cache):
    _, units = _units(2)

    async def extract(_):
        return [ExtractedFeature(product_name="Z", section_ref="S1")]

    provider = FakeProvider(extract)
    first = await _svc(provider, cache).extract_units(units)
    second = await _svc(provider, cache).extract_units(units)
    assert len(provider.calls) == 2
    assert first == second


async def test_timeout_raises(cache):
    _, units = _units(1)

    async def slow(_):
        await asyncio.sleep(2)
        return []

    with pytest.raises(TimeoutError):
        await _svc(FakeProvider(slow), cache, timeout=0.05).extract_units(units)


async def test_error_propagates_and_completed_units_cached(cache):
    _, units = _units(2)
    target = units[1].prompt_text()

    async def flaky(text):
        if text == target:
            raise RuntimeError("LLM down")
        return []

    provider = FakeProvider(flaky)
    with pytest.raises(RuntimeError):
        await _svc(provider, cache, limit=1).extract_units(units)

    async def ok(_):
        return []

    provider2 = FakeProvider(ok)
    await _svc(provider2, cache).extract_units(units)
    assert provider2.calls == [target]  # the first unit comes from the cache


async def test_concurrency_limited(cache):
    _, units = _units(6)

    async def extract(_):
        await asyncio.sleep(0.02)
        return []

    provider = FakeProvider(extract)
    await _svc(provider, cache, limit=2).extract_units(units)
    assert provider.max_active <= 2
