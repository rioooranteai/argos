from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from app.core.config import app_config, infra, validate_required_config
from app.core.database import DB_PATH, db
from app.core.migrations import run_migrations
from app.engines.chat_engine.engine import ChatEngine
from app.infrastructure.factories.embedder_factory import get_embedder
from app.infrastructure.factories.llm_factory import get_llm
from app.infrastructure.providers.repositories.sqlite_conversation_repository import (
    SQLiteConversationRepository,
)
from app.infrastructure.providers.repositories.sqlite_library_repository import (
    SQLiteLibraryRepository,
)
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository
from app.services.conversation.service import ConversationService
from app.services.library.service import LibraryService
from app.services.nl2sql.service import NL2SQLService
from app.services.vector_store.service import VectorStoreService
from app.services.voice.service import VoiceService
from fastapi import FastAPI

logger = logging.getLogger(__name__)

def init_db() -> None:
    """Run migrations on startup. Called once from lifespan."""
    with db.get_connection() as conn:
        run_migrations(conn)


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

    app.state.library_service = LibraryService(
        repository=SQLiteLibraryRepository(database=db),
        queue_dir=infra.upload_queue_dir,
        config=app_config,
    )

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

    # Pemrosesan dokumen (worker) ditambahkan di langkah 3 (IMPLEMENTATION_PLAN_AB.md).

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

    yield
