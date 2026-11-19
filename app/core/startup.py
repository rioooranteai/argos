from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import tiktoken
from fastapi import FastAPI

from app.core.concurrency import AILimits
from app.core.config import app_config, infra, validate_required_config
from app.core.database import DB_PATH, db
from app.core.migrations import run_migrations
from app.engines.chat_engine.engine import ChatEngine
from app.engines.document_engine.pipeline import DocumentPipeline
from app.engines.document_engine.worker import DocumentWorker
from app.infrastructure.factories.embedder_factory import get_embedder
from app.infrastructure.factories.llm_factory import get_llm
from app.infrastructure.providers.repositories.sqlite_cache_repository import SQLiteCacheRepository
from app.infrastructure.providers.repositories.sqlite_conversation_repository import (
    SQLiteConversationRepository,
)
from app.infrastructure.providers.repositories.sqlite_feature_repository import (
    SQLiteFeatureRepository,
)
from app.infrastructure.providers.repositories.sqlite_job_repository import SQLiteJobRepository
from app.infrastructure.providers.repositories.sqlite_library_repository import (
    SQLiteLibraryRepository,
)
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository
from app.services.conversation.service import ConversationService
from app.services.extraction.providers.pydantic_ai_provider import PydanticAIExtractionProvider
from app.services.extraction.service import ExtractionService
from app.services.ingestion.factories.vision_factory import VisionFactory
from app.services.ingestion.providers.loaders.docling_process import DoclingProcess
from app.services.ingestion.service import FigureDescriber
from app.services.library.service import LibraryService
from app.services.nl2sql.service import NL2SQLService
from app.services.vector_store.service import VectorStoreService
from app.services.voice.service import VoiceService

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Run migrations on startup. Called once from lifespan."""
    with db.get_connection() as conn:
        run_migrations(conn)


def _token_counter():
    encoding = tiktoken.get_encoding("cl100k_base")
    return lambda text: len(encoding.encode(text, disallowed_special=()))


async def _warm_up_docling(docling: DoclingProcess) -> None:
    """Muat model Docling di background agar upload pertama tidak menunggu."""
    try:
        await docling.start()
    except Exception:
        logger.exception("Subprocess Docling gagal dimulai; akan dicoba lagi saat dibutuhkan.")


@asynccontextmanager
async def lifespan(app: FastAPI):

    # --- Fail-fast: konfigurasi wajib & folder data ---
    validate_required_config()
    infra.DATA_DIR.mkdir(parents=True, exist_ok=True)
    infra.upload_queue_dir.mkdir(parents=True, exist_ok=True)

    # --- Persistence ---
    init_db()

    app.state.database = db
    app.state.user_repo = SQLiteUserRepository(database=db)
    library_repo = SQLiteLibraryRepository(database=db)
    cache_repo = SQLiteCacheRepository(database=db)

    app.state.library_service = LibraryService(
        repository=library_repo,
        queue_dir=infra.upload_queue_dir,
        config=app_config,
    )

    conversation_repo = SQLiteConversationRepository(database=db)

    # --- AI providers ---
    embedder = get_embedder()
    limits = AILimits.from_config(app_config)

    # --- Services ---
    app.state.vector_store_svc = VectorStoreService(embedder=embedder, provider="chroma")

    # --- Pipeline dokumen & worker (DESIGN_GROUP_B.md) ---
    docling = DoclingProcess()
    pipeline = DocumentPipeline(
        parser=docling,
        describer=FigureDescriber(
            processor=VisionFactory().get_processor(),
            cache=cache_repo,
            model_name=app_config.OPENAI_VLM_MODEL,
            semaphore=limits.vision,
        ),
        vector_store=app.state.vector_store_svc,
        extraction=ExtractionService(
            provider=PydanticAIExtractionProvider(model=app_config.OPENAI_EXTRACTION_MODEL),
            cache=cache_repo,
            semaphore=limits.extraction,
            pipeline_version=app_config.PIPELINE_VERSION,
            timeout=app_config.EXTRACTION_TIMEOUT,
        ),
        features=SQLiteFeatureRepository(database=db),
        library=library_repo,
        queue_dir=infra.upload_queue_dir,
        config=app_config,
        limits=limits,
        count_tokens=_token_counter(),
    )
    worker = DocumentWorker(
        jobs=SQLiteJobRepository(database=db),
        process=pipeline.process,
        cleanup=pipeline.cleanup,
        source_path=pipeline.source_path,
        config=app_config,
    )
    app.state.docling = docling
    app.state.document_pipeline = pipeline  # dipakai eval/run_eval.py untuk instrumentasi
    app.state.document_worker = worker

    app.state.nl2sql_service = NL2SQLService(
        llm_provider=get_llm(model_type="extraction", temperature=0.0),
        db_path=DB_PATH,
    )

    app.state.voice_service = VoiceService()

    app.state.conversation_service = ConversationService(
        repository=conversation_repo,
        title_llm=get_llm(model_type="title", temperature=0.3),
    )

    app.state.chat_engine = ChatEngine(
        llm=get_llm(model_type="chat", temperature=0.3),
        router_llm=get_llm(model_type="router", temperature=0.0),
        nl2sql_svc=app.state.nl2sql_service,
        vector_svc=app.state.vector_store_svc,
    )

    warm_up = asyncio.create_task(_warm_up_docling(docling))
    await worker.start()

    yield

    # --- Shutdown: hentikan worker dulu, baru subprocess Docling ---
    await worker.stop()
    warm_up.cancel()
    await asyncio.gather(warm_up, return_exceptions=True)
    await docling.stop()
