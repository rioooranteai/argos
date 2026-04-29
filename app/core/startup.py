import logging
from contextlib import asynccontextmanager

from app.core.config import config
from app.core.database import db
from app.engines.chat_engine.engine import ChatEngine
from app.engines.document_engine import DocumentProcessingEngine
from app.infrastructure.factories.embedder_factory import get_embedder
from app.infrastructure.factories.llm_factory import get_llm
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")

    db.init_db()

    embedder = get_embedder()

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
            provider="pydantic_ai",
            model=config.OPENAI_EXTRACTION_MODEL,
        ),
    )

    app.state.nl2sql_service = NL2SQLService(
        llm_provider=get_llm(model_type="extraction", temperature=0.0)
    )

    app.state.voice_service = VoiceService()

    app.state.chat_engine = ChatEngine(
        llm=get_llm(model_type="chat", temperature=0.3),
        nl2sql_svc=app.state.nl2sql_service,
        vector_svc=app.state.vector_store_svc,
    )

    logger.info("All services initialized.")
    yield
    logger.info("Shutting down...")
