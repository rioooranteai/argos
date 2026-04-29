"""Application composition root.

All wiring of services, adapters, and engines happens here. Routers and
domain code never instantiate concrete adapters — they receive collaborators
through dependency injection (FastAPI Depends + app.state).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import config
from app.core.database import DB_PATH, Database
from app.engines.chat_engine.engine import ChatEngine
from app.engines.document_engine import DocumentProcessingEngine
from app.infrastructure.factories.embedder_factory import get_embedder
from app.infrastructure.factories.llm_factory import get_llm
from app.infrastructure.providers.repositories.sqlite_feature_repository import (
    SQLiteFeatureRepository,
)
from app.services.conversation.service import ConversationService
from app.services.conversation.sqlite_repository import SQLiteConversationRepository
from app.services.extraction.service import ExtractionService
from app.services.ingestion.chunker import ContentAwareChunker
from app.services.ingestion.factories.loader_factory import LoaderFactory
from app.services.ingestion.factories.vision_factory import VisionFactory
from app.services.ingestion.service import IngestionService
from app.services.nl2sql.service import NL2SQLService
from app.services.vector_store.service import VectorStoreService
from app.services.voice.service import VoiceService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")

    # --- Persistence ---
    database = Database(db_path=DB_PATH)
    database.init_db()
    app.state.database = database

    feature_repo = SQLiteFeatureRepository(database=database)

    # Multi-conversation persistence (replaces the legacy single-row
    # conversation_history store).
    conversation_repo = SQLiteConversationRepository(db_path=DB_PATH)

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

    # ConversationService owns persistence + auto-titling. Title LLM is a
    # cheap small model (configurable via OPENAI_TITLE_MODEL).
    app.state.conversation_service = ConversationService(
        repository=conversation_repo,
        title_llm=get_llm(model_type="title", temperature=0.3),
    )

    # ChatEngine is now stateless — history flows in/out via the API router.
    app.state.chat_engine = ChatEngine(
        llm=get_llm(model_type="chat", temperature=0.3),
        nl2sql_svc=app.state.nl2sql_service,
        vector_svc=app.state.vector_store_svc,
    )

    logger.info("All services initialized.")
    yield
    logger.info("Shutting down...")
