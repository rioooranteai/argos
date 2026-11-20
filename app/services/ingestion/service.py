"""Deskripsi gambar dengan Vision: dibatasi, di-cache, dan kegagalan tercatat.

(DESIGN_GROUP_B.md §6, audit poin 10.)
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.infrastructure.interface.cache_repository import BaseCacheRepository
from app.services.ingestion.base.vision import BaseVisionProcessor
from app.services.ingestion.model import DocumentElement, ElementType, Section

logger = logging.getLogger(__name__)

FAILED_IMAGE_TEXT = "[GAMBAR TIDAK TERBACA]"
DESCRIPTION_PREFIX = "[DESKRIPSI VISUAL GRAFIK/GAMBAR]: "


@dataclass(frozen=True)
class VisionOutcome:
    total: int
    described: int
    from_cache: int
    failed: int


def figures_in(sections: list[Section]) -> list[DocumentElement]:
    return [
        el
        for s in sections
        for el in s.elements
        if el.element_type == ElementType.FIGURE and el.image_bytes
    ]


class FigureDescriber:
    def __init__(
        self,
        processor: BaseVisionProcessor,
        cache: BaseCacheRepository,
        model_name: str,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._processor = processor
        self._cache = cache
        self._model = model_name
        self._semaphore = semaphore

    async def describe_all(
        self,
        sections: list[Section],
        on_progress: Callable[[int], Awaitable[None]] | None = None,
    ) -> VisionOutcome:
        """Isi `content` setiap gambar dengan deskripsi. Gambar yang gagal setelah
        retry diberi penanda dan dihitung, tidak menggagalkan dokumen."""
        figures = figures_in(sections)
        done = 0
        stats = {"cache": 0, "ok": 0, "failed": 0}
        lock = asyncio.Lock()

        async def one(el: DocumentElement) -> None:
            nonlocal done
            kind = await self._describe(el)
            async with lock:
                stats[kind] += 1
                done += 1
                if on_progress is not None:
                    await on_progress(done)

        await asyncio.gather(*(one(el) for el in figures))
        return VisionOutcome(
            total=len(figures),
            described=stats["ok"],
            from_cache=stats["cache"],
            failed=stats["failed"],
        )

    async def _describe(self, el: DocumentElement) -> str:
        key = el.metadata.get("image_hash", "")
        cached = await asyncio.to_thread(self._cache.get_vision, key, self._model) if key else None
        if cached is not None:
            el.content = DESCRIPTION_PREFIX + cached
            el.image_bytes = None
            return "cache"

        try:
            async with self._semaphore:
                description = await self._processor.describe_image(el)
        except Exception:
            # Gambar gagal tidak menggagalkan dokumen; dihitung di `vision_failed`.
            logger.warning(
                "Vision gagal untuk gambar hal. %s (%s).", el.page_number, key[:12], exc_info=True
            )
            el.content = FAILED_IMAGE_TEXT
            el.image_bytes = None
            return "failed"

        if key:
            await asyncio.to_thread(self._cache.put_vision, key, self._model, description)
        el.content = DESCRIPTION_PREFIX + description
        el.image_bytes = None
        return "ok"
