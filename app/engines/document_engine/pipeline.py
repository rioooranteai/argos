"""Pipeline pemrosesan satu versi dokumen (DESIGN_GROUP_A.md §7, DESIGN_GROUP_B.md §3).

    parsing → vision → indexing → extracting → publikasi (satu transaksi SQL)

Urutan tulis aman (Chroma dan SQLite tidak bisa satu transaksi):
  1. vektor versi ini ditulis ke Chroma — belum terlihat, karena chat hanya
     membaca versi berstatus `ready`;
  2. bagian + features + status `ready` ditulis dalam SATU transaksi SQL.
Gagal di mana pun → worker memanggil `cleanup()`; tidak ada data setengah jadi
yang terlihat.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.core.concurrency import AILimits
from app.core.config import AppConfig
from app.engines.document_engine.jobs import JobCancelled, JobContext, PermanentJobError
from app.infrastructure.interface.feature_repository import BaseFeatureRepository
from app.infrastructure.interface.library_repository import BaseLibraryRepository
from app.services.extraction.service import ExtractionService
from app.services.ingestion.chunker import build_index_chunks, build_sections, build_units
from app.services.ingestion.model import DocumentElement, ElementType
from app.services.ingestion.service import FigureDescriber, figures_in
from app.services.library.model import DocumentVersion
from app.services.library.service import queued_file_path
from app.services.vector_store.service import VectorStoreService

logger = logging.getLogger(__name__)


class DocumentParser(Protocol):
    async def parse(self, path: str, timeout: float) -> list[DocumentElement]: ...


class DocumentPipeline:
    def __init__(
        self,
        parser: DocumentParser,
        describer: FigureDescriber,
        vector_store: VectorStoreService,
        extraction: ExtractionService,
        features: BaseFeatureRepository,
        library: BaseLibraryRepository,
        queue_dir: Path,
        config: AppConfig,
        limits: AILimits,
        count_tokens: Callable[[str], int],
    ) -> None:
        self._parser = parser
        self._describer = describer
        self._vectors = vector_store
        self._extraction = extraction
        self._features = features
        self._library = library
        self._queue_dir = queue_dir
        self._cfg = config
        self._limits = limits
        self._count_tokens = count_tokens

    def source_path(self, version: DocumentVersion) -> Path:
        return queued_file_path(self._queue_dir, version.id, version.file_ext)

    async def process(self, version: DocumentVersion, ctx: JobContext) -> None:
        path = self.source_path(version)
        if not path.exists():
            raise PermanentJobError("File sumber tidak ditemukan. Upload ulang dokumen ini.")
        document = await asyncio.to_thread(self._library.get_document, version.document_id)
        if document is None:
            raise JobCancelled()

        # Sisa percobaan sebelumnya (mis. crash di tengah) dibersihkan dulu.
        await self.cleanup(version.id)

        # ── 1. Parsing ─────────────────────────────────────────────────
        await ctx.stage("parsing")
        pages = version.page_count or 10
        timeout = self._cfg.DOCLING_TIMEOUT_BASE + self._cfg.DOCLING_TIMEOUT_PER_PAGE * pages
        elements = await self._parser.parse(str(path), timeout)
        sections = build_sections(elements)
        if not any(s.text.strip() for s in sections) and not any(
            e.element_type == ElementType.FIGURE for e in elements
        ):
            raise PermanentJobError("Dokumen tidak berisi teks yang bisa dibaca.")
        await ctx.check_cancelled()

        # ── 2. Vision ──────────────────────────────────────────────────
        await ctx.stage("vision", total=len(figures_in(sections)))
        outcome = await self._describer.describe_all(sections, on_progress=ctx.progress)
        if outcome.failed:
            await ctx.add_vision_failed(outcome.failed)
        await ctx.check_cancelled()

        # ── 3. Indexing (embedding + Chroma) ───────────────────────────
        chunks = build_index_chunks(sections, version.document_id, version.id, document.display_name)
        size = self._cfg.EMBED_BATCH_SIZE
        batches = [chunks[i : i + size] for i in range(0, len(chunks), size)]
        await ctx.stage("indexing", total=len(batches))
        for i, batch in enumerate(batches, start=1):
            async with self._limits.embedding:
                await asyncio.to_thread(self._vectors.add_chunks, batch)
            await ctx.progress(i)
            await ctx.check_cancelled()

        # ── 4. Ekstraksi ───────────────────────────────────────────────
        units = build_units(
            sections,
            self._count_tokens,
            self._cfg.EXTRACTION_MIN_SECTION_TOKENS,
            self._cfg.EXTRACTION_MAX_UNIT_TOKENS,
        )
        await ctx.stage("extracting", total=len(units))
        rows = await self._extraction.extract_units(units, on_progress=ctx.progress)
        await ctx.check_cancelled()

        # ── 5. Publikasi atomik ────────────────────────────────────────
        published = await asyncio.to_thread(
            self._features.publish_version, version.document_id, version.id, sections, rows
        )
        if not published:
            raise JobCancelled()
        logger.info(
            "Versi %s ready: %d bagian, %d chunk, %d feature, %d gambar (%d dari cache, %d gagal)",
            version.id, len(sections), len(chunks), len(rows),
            outcome.total, outcome.from_cache, outcome.failed,
        )

    async def cleanup(self, version_id: str) -> None:
        """Hapus semua data milik versi yang belum/tidak jadi dipublikasikan."""
        await asyncio.to_thread(self._features.delete_version_content, version_id)
        await asyncio.to_thread(self._vectors.delete_version, version_id)
