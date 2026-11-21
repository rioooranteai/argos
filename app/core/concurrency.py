"""Global concurrency limits for AI calls (DESIGN_GROUP_B.md §6).

The limits apply to ALL documents being processed, not per document.
Chat deliberately does not use these limits so a large upload cannot hold it up.
Docling is limited by its own single subprocess (docling_process.py).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.config import AppConfig


@dataclass
class AILimits:
    vision: asyncio.Semaphore
    extraction: asyncio.Semaphore
    embedding: asyncio.Semaphore

    @classmethod
    def from_config(cls, cfg: AppConfig) -> AILimits:
        return cls(
            vision=asyncio.Semaphore(cfg.VISION_CONCURRENCY),
            extraction=asyncio.Semaphore(cfg.EXTRACTION_CONCURRENCY),
            embedding=asyncio.Semaphore(cfg.EMBED_CONCURRENCY),
        )
