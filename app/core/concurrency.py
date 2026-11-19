"""Batas concurrency global untuk panggilan AI (DESIGN_GROUP_B.md §6).

Batas berlaku untuk SEMUA dokumen yang sedang diproses, bukan per dokumen.
Chat sengaja tidak memakai batas ini agar tidak tertahan oleh upload besar.
Docling dibatasi oleh subprocess tunggalnya sendiri (docling_process.py).
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
