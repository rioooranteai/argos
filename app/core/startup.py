# app/core/startup.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.database import init_db
from app.engines.document_engine import DocumentProcessingEngine
from app.services.chroma_service import ChromaService
from app.services.extraction.service import ExtractionService
from app.services.ingestion.chunker import ContentAwareChunker
from app.services.ingestion.factories.loader_factory import LoaderFactory
from app.services.ingestion.factories.vision_factory import VisionFactory
from app.services.ingestion.service import IngestionService
from app.services.nl2sql.service import NL2SQLService
from app.services.voice.service import VoiceService
from app.services.shared.factories.embedder_factory import get_embedder
from app.services.shared.factories.llm_factory import get_llm
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    init_db()

    app.state.document_engine = DocumentProcessingEngine(
        ingestion_svc=IngestionService(
            loader_factory=LoaderFactory(),
            vision_factory=VisionFactory(),
            chunker=ContentAwareChunker(),
        ),
        chroma_svc=ChromaService(embedder=get_embedder()),
        extraction_svc=ExtractionService(),
    )

    app.state.nl2sql_service = NL2SQLService(
        llm_provider=get_llm(model_type="extraction", temperature=0.0)
    )

    app.state.voice_service = VoiceService()

    logger.info("All services initialized.")
    yield
    logger.info("Shutting down...")