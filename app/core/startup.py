from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from app.core.config import config
from app.core.database import DB_PATH, db
from app.core.migrations import run_migrations
from app.engines.chat_engine.engine import ChatEngine
from app.engines.document_engine.engine import DocumentProcessingEngine
from app.infrastructure.factories.embedder_factory import get_embedder
from app.infrastructure.factories.llm_factory import get_llm
from app.infrastructure.providers.repositories.sqlite_conversation_repository import (
    SQLiteConversationRepository,
)
from app.infrastructure.providers.repositories.sqlite_feature_repository import (
    SQLiteFeatureRepository,
)
from app.services.conversation.service import ConversationService
from app.services.extraction.service import ExtractionService
from app.services.ingestion.chunker import ContentAwareChunker
from app.services.ingestion.factories.loader_factory import LoaderFactory
from app.services.ingestion.factories.vision_factory import VisionFactory
from app.services.ingestion.service import IngestionService
from app.services.nl2sql.service import NL2SQLService
from app.services.vector_store.service import VectorStoreService
from app.services.voice.service import VoiceService
from fastapi import FastAPI

logger = logging.getLogger(__name__)

def init_db() -> None:
    """Run migrations on startup. Called once from lifespan."""
    logger.info("Running database migrations...")
    with db.get_connection() as conn:
        run_migrations(conn)
    logger.info("Database ready.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")

    # --- Persistence ---
    init_db()

    app.state.database = db

    feature_repo = SQLiteFeatureRepository(database=db)

    # Multi-conversation persistence (replaces the legacy single-row
    # conversation_history store).
    conversation_repo = SQLiteConversationRepository(database=db)

    # --- AI providers ---
    embedder = get_embedder()

    # --- Services ---
    app.state.vector_store_svc = VectorStoreService(
        embedder=embedder,
        provider="chroma",
        collection_name="competitor_knowledge",
    )

    app.state.document_engine = DocumentProcessingEngine(
        ingestion_svc=IngestionService(
            loader_factory=LoaderFactory(),
            vision_factory=VisionFactory(),
            chunker=ContentAwareChunker(),
        ),
        vector_store_svc=app.state.vector_store_svc,
        extraction_svc=ExtractionService(
            repository=feature_repo,
            provider="pydantic_ai",
            model=config.OPENAI_EXTRACTION_MODEL,
        ),
    )

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
        nl2sql_svc=app.state.nl2sql_service,
        vector_svc=app.state.vector_store_svc,
    )

    logger.info("All services initialized.")
    yield
    logger.info("Shutting down...")
