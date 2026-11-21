from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import tiktoken
from fastapi import FastAPI

from app.core.concurrency import AILimits
from app.core.config import app_config, infra, secrets, validate_required_config
from app.core.database import DB_PATH, db
from app.core.migrations import run_migrations
from app.engines.chat_engine.engine import ChatEngine
from app.engines.document_engine.pipeline import DocumentPipeline
from app.engines.document_engine.worker import DocumentWorker
from app.tools.document_parser.base import BaseDocumentParser
from app.tools.factory import (
    build_document_parser,
    build_embedder,
    build_extractor,
    build_llm,
    build_stt,
    build_tts,
    build_vector_store,
    build_vision,
)
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
from app.infrastructure.providers.repositories.sqlite_llm_call_repository import (
    SQLiteLLMCallRepository,
)
from app.infrastructure.providers.repositories.sqlite_notebook_repository import (
    SQLiteNotebookRepository,
)
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository
from app.services.conversation.service import ConversationService
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import FigureDescriber
from app.services.library.service import LibraryService
from app.services.nl2sql.service import NL2SQLService
from app.services.notebook.service import NotebookService
from app.services.observability.health import HealthChecker
from app.core.observability.recorder import recorder as llm_recorder
from app.services.user.admin import AdminService
from app.services.voice.service import VoiceService

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Run migrations on startup. Called once from lifespan."""
    with db.get_connection() as conn:
        run_migrations(conn)


def _token_counter():
    encoding = tiktoken.get_encoding("cl100k_base")
    return lambda text: len(encoding.encode(text, disallowed_special=()))


async def _warm_up_docling(docling: BaseDocumentParser) -> None:
    """Load the Docling models in the background so the first upload does not wait."""
    try:
        await docling.start()
    except Exception:
        logger.exception("The Docling subprocess failed to start; it will be retried when needed.")


@asynccontextmanager
async def lifespan(app: FastAPI):

    # --- Fail fast: required config & data folders ---
    validate_required_config()
    infra.DATA_DIR.mkdir(parents=True, exist_ok=True)
    infra.upload_queue_dir.mkdir(parents=True, exist_ok=True)

    # --- Persistence ---
    init_db()

    app.state.database = db
    app.state.user_repo = SQLiteUserRepository(database=db)
    library_repo = SQLiteLibraryRepository(database=db)
    cache_repo = SQLiteCacheRepository(database=db)
    job_repo = SQLiteJobRepository(database=db)
    app.state.admin_service = AdminService(users=app.state.user_repo, library=library_repo)

    conversation_repo = SQLiteConversationRepository(database=db)

    # --- AI call records (DESIGN_GROUP_C.md §7.3) ---
    llm_call_repo = SQLiteLLMCallRepository(database=db)
    purged = llm_call_repo.purge_older_than(app_config.LLM_CALLS_RETENTION_DAYS)
    if purged:
        logger.info("Deleted %d llm_calls records older than %d days.",
                    purged, app_config.LLM_CALLS_RETENTION_DAYS)
    llm_recorder.attach(llm_call_repo)
    app.state.llm_recorder = llm_recorder

    # --- AI providers ---
    embedder = build_embedder()
    limits = AILimits.from_config(app_config)

    # --- Services ---
    app.state.vector_store = build_vector_store(embedder)

    app.state.library_service = LibraryService(
        repository=library_repo,
        queue_dir=infra.upload_queue_dir,
        config=app_config,
        vector_store=app.state.vector_store,
        jobs=job_repo,
        users=app.state.user_repo,
    )
    app.state.library_service.purge_expired_pending()

    # --- Document pipeline & worker (DESIGN_GROUP_B.md) ---
    docling = build_document_parser()
    pipeline = DocumentPipeline(
        parser=docling,
        describer=FigureDescriber(
            processor=build_vision(),
            cache=cache_repo,
            model_name=app_config.OPENAI_VLM_MODEL,
            semaphore=limits.vision,
        ),
        vector_store=app.state.vector_store,
        extraction=ExtractionService(
            provider=build_extractor(),
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
    app.state.notebook_service = NotebookService(
        repository=SQLiteNotebookRepository(database=db),
        library_repo=library_repo,
        library_service=app.state.library_service,
        jobs=job_repo,
        config=app_config,
    )
    worker = DocumentWorker(
        jobs=job_repo,
        process=pipeline.process,
        cleanup=pipeline.cleanup,
        source_path=pipeline.source_path,
        config=app_config,
    )
    app.state.docling = docling
    app.state.document_pipeline = pipeline  # used by eval/run_eval.py for instrumentation
    app.state.document_worker = worker

    app.state.nl2sql_service = NL2SQLService(
        llm_provider=build_llm("nl2sql", temperature=0.0),
        db_path=DB_PATH,
        exec_timeout=app_config.SQL_EXEC_TIMEOUT,
    )

    app.state.voice_service = VoiceService(stt=build_stt(), tts=build_tts())

    app.state.conversation_service = ConversationService(
        repository=conversation_repo,
        title_llm=build_llm("title", temperature=0.3),
    )

    app.state.chat_engine = ChatEngine(
        llm=build_llm("chat", temperature=0.3),
        router_llm=build_llm("router", temperature=0.0),
        nl2sql_svc=app.state.nl2sql_service,
        vector_store=app.state.vector_store,
        total_timeout=app_config.CHAT_TOTAL_TIMEOUT,
    )

    app.state.health_checker = HealthChecker(
        database=db,
        vector_store=app.state.vector_store,
        worker=worker,
        docling=docling,
        recorder=llm_recorder,
        missing_config=secrets.missing_required,
        worker_poll_seconds=app_config.WORKER_POLL_SECONDS,
    )

    warm_up = asyncio.create_task(_warm_up_docling(docling))
    await worker.start()

    yield

    # --- Shutdown: stop the worker first, then the Docling subprocess ---
    await worker.stop()
    warm_up.cancel()
    await asyncio.gather(warm_up, return_exceptions=True)
    await docling.stop()
    llm_recorder.close()  # write the remaining llm_calls records
