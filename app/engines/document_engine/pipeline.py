"""The processing pipeline for one document version (DESIGN_GROUP_A.md §7, DESIGN_GROUP_B.md §3).

    parsing → vision → indexing → extracting → publish (one SQL transaction)

Safe write order (Chroma and SQLite cannot share a transaction):
  1. this version's vectors are written to Chroma — not visible yet, because chat
     only reads versions with status `ready`;
  2. sections + features + status `ready` are written in ONE SQL transaction.
A failure anywhere → the worker calls `cleanup()`; no half-finished data
is ever visible.

Reuse for new versions (stage 3, A §6.3): images through the Vision cache,
extraction units through the extraction cache, and vectors of chunks with identical
text are copied from the same document's latest `ready` version (no re-embedding).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from app.core.concurrency import AILimits
from app.core.config import AppConfig
from app.engines.document_engine.jobs import JobCancelled, JobContext, PermanentJobError
from app.infrastructure.interface.feature_repository import BaseFeatureRepository
from app.infrastructure.interface.library_repository import BaseLibraryRepository
from app.services.extraction.service import ExtractionService, ExtractionStats
from app.services.ingestion.chunker import build_index_chunks, build_sections, build_units
from app.services.ingestion.service import FigureDescriber, figures_in
from app.services.library.model import STAGE_READY, DocumentVersion, LibraryDocument
from app.services.library.service import queued_file_path
from app.tools.document_parser.base import BaseDocumentParser, ElementType
from app.tools.vector_store.base import BaseVectorStore

logger = logging.getLogger(__name__)


class DocumentPipeline:
    def __init__(
        self,
        parser: BaseDocumentParser,
        describer: FigureDescriber,
        vector_store: BaseVectorStore,
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
            raise PermanentJobError("The source file was not found. Upload this document again.")
        document = await asyncio.to_thread(self._library.get_document, version.document_id)
        if document is None:
            raise JobCancelled()

        # Leftovers from a previous attempt (e.g. a crash midway) are cleaned up first.
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
            raise PermanentJobError("The document contains no readable text.")
        await ctx.check_cancelled()

        # ── 2. Vision ──────────────────────────────────────────────────
        await ctx.stage("vision", total=len(figures_in(sections)))
        outcome = await self._describer.describe_all(sections, on_progress=ctx.progress)
        if outcome.failed:
            await ctx.add_vision_failed(outcome.failed)
        await ctx.check_cancelled()

        # ── 3. Indexing (embedding + Chroma) ───────────────────────────
        chunks = build_index_chunks(sections, version.document_id, version.id, document.display_name)
        reuse = await asyncio.to_thread(self._reusable_vectors, document, version)
        size = self._cfg.EMBED_BATCH_SIZE
        batches = [chunks[i : i + size] for i in range(0, len(chunks), size)]
        await ctx.stage("indexing", total=len(batches))
        chunks_reused = 0
        for i, batch in enumerate(batches, start=1):
            async with self._limits.embedding:
                added = await asyncio.to_thread(self._vectors.add_chunks, batch, reuse)
            chunks_reused += added.reused
            await ctx.progress(i)
            await ctx.check_cancelled()

        # ── 4. Extraction ──────────────────────────────────────────────
        units = build_units(
            sections,
            self._count_tokens,
            self._cfg.EXTRACTION_MIN_SECTION_TOKENS,
            self._cfg.EXTRACTION_MAX_UNIT_TOKENS,
        )
        await ctx.stage("extracting", total=len(units))
        extraction_stats = ExtractionStats()
        rows = await self._extraction.extract_units(
            units, on_progress=ctx.progress, stats=extraction_stats
        )
        await ctx.check_cancelled()

        # ── 5. Atomic publish ──────────────────────────────────────────
        reuse_stats = {
            "chunks": len(chunks),
            "chunks_reused": chunks_reused,
            "units": extraction_stats.units,
            "units_cached": extraction_stats.cached,
            "images": outcome.total,
            "images_cached": outcome.from_cache,
        }
        published = await asyncio.to_thread(
            self._features.publish_version,
            version.document_id, version.id, sections, rows, reuse_stats,
        )
        if not published:
            raise JobCancelled()
        logger.info(
            "Version %s ready: %d sections, %d features, %d Vision failures | reused: "
            "chunks %d/%d, units %d/%d, images %d/%d",
            version.id, len(sections), len(rows), outcome.failed,
            chunks_reused, len(chunks), extraction_stats.cached, extraction_stats.units,
            outcome.from_cache, outcome.total,
        )

    def _reusable_vectors(self, document: LibraryDocument, version: DocumentVersion) -> dict[str, str]:
        """Text → chunk ID from this document's latest `ready` version, when its vectors are compatible.

        Only an optimisation: if it cannot be read, this version is processed in full.
        """
        previous_id = document.latest_version_id
        if not previous_id or previous_id == version.id:
            return {}
        previous = self._library.get_version(previous_id)
        # The embedding model is covered by PIPELINE_VERSION: vectors from different models are never mixed.
        if (
            previous is None
            or previous.stage != STAGE_READY
            or previous.pipeline_version != version.pipeline_version
        ):
            return {}
        try:
            return self._vectors.version_texts(previous_id)
        except Exception:
            # Reuse is only a saving: on failure → every chunk is embedded as usual.
            logger.warning(
                "Could not read the vectors of version %s for reuse.", previous_id, exc_info=True
            )
            return {}

    async def cleanup(self, version_id: str) -> None:
        """Delete all data of a version that was not (or will not be) published."""
        await asyncio.to_thread(self._features.delete_version_content, version_id)
        await asyncio.to_thread(self._vectors.delete_version, version_id)
