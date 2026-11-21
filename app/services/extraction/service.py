"""Feature extraction per section unit, with concurrency limits, timeouts and a cache.

(DESIGN_GROUP_B.md §7; audit point 11 — no more 100,000-character truncation.)

Errors propagate to the worker: finished units are stored in the cache,
so a retry only pays for the units that did not finish.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from app.infrastructure.interface.cache_repository import BaseCacheRepository
from app.services.extraction.base.extraction_base import BaseExtractionProvider
from app.services.extraction.model import ExtractedFeature, FeatureRow
from app.services.ingestion.model import ExtractionUnit

logger = logging.getLogger(__name__)


@dataclass
class ExtractionStats:
    """Set by ``extract_units``: how many units came from the cache."""

    units: int = 0
    cached: int = 0


class ExtractionService:
    def __init__(
        self,
        provider: BaseExtractionProvider,
        cache: BaseCacheRepository,
        semaphore: asyncio.Semaphore,
        pipeline_version: str,
        timeout: float,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._semaphore = semaphore
        self._pipeline_version = pipeline_version
        self._timeout = timeout

    async def extract_units(
        self,
        units: list[ExtractionUnit],
        on_progress: Callable[[int], Awaitable[None]] | None = None,
        stats: ExtractionStats | None = None,
    ) -> list[FeatureRow]:
        stats = stats if stats is not None else ExtractionStats()
        stats.units += len(units)
        done = 0
        lock = asyncio.Lock()
        results: list[list[FeatureRow]] = [[] for _ in units]

        async def one(i: int, unit: ExtractionUnit) -> None:
            nonlocal done
            results[i], from_cache = await self._extract_unit(unit)
            async with lock:
                done += 1
                stats.cached += from_cache
                if on_progress is not None:
                    await on_progress(done)

        # Wait for every unit to finish (success or failure) before raising,
        # so the successful units make it into the cache for the next attempt.
        outcomes = await asyncio.gather(
            *(one(i, u) for i, u in enumerate(units)), return_exceptions=True
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                raise outcome
        return [row for rows in results for row in rows]

    async def _extract_unit(self, unit: ExtractionUnit) -> tuple[list[FeatureRow], bool]:
        """Return (feature rows, taken from the cache?)."""
        cached = await asyncio.to_thread(
            self._cache.get_extraction, unit.unit_hash, self._pipeline_version
        )
        if cached is not None:
            return [FeatureRow(**row) for row in json.loads(cached)], True

        async with self._semaphore:
            features = await asyncio.wait_for(
                self._provider.extract(unit.prompt_text()), timeout=self._timeout
            )

        rows = self._to_rows(unit, features)
        await asyncio.to_thread(
            self._cache.put_extraction,
            unit.unit_hash,
            self._pipeline_version,
            json.dumps([asdict(r) for r in rows], ensure_ascii=False),
        )
        return rows, False

    @staticmethod
    def _to_rows(unit: ExtractionUnit, features: list[ExtractedFeature]) -> list[FeatureRow]:
        by_hash = {s.section_hash: s for s in unit.sections}
        first_label = next(iter(unit.labels))
        rows: list[FeatureRow] = []
        for f in features:
            # `product_name` is required (Rule 3); `brand_name` may be null (Rule 20).
            if not (f.product_name and f.product_name.strip()):
                continue
            label = (f.section_ref or "").strip().strip("[]")
            if label not in unit.labels:
                logger.info(
                    "section_ref %r is not valid for unit %s; using %s.",
                    f.section_ref, unit.unit_hash[:12], first_label,
                )
                label = first_label
            section = by_hash[unit.labels[label]]
            rows.append(
                FeatureRow(
                    section_hash=section.section_hash,
                    section_heading=section.heading,
                    page_number=section.page_start,
                    brand_name=f.brand_name,
                    product_name=f.product_name.strip(),
                    price=f.price,
                    price_currency=f.price_currency,
                    advantages=f.advantages,
                    disadvantages=f.disadvantages,
                )
            )
        return rows
