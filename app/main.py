import logging
from contextlib import asynccontextmanager

from app.api.routers.chat import router as chat_router
from app.api.routers.document import router as document_router
from app.core.database import init_db
from app.engines.document_engine import DocumentProcessingEngine
from app.services.chroma_service import ChromaService
from app.services.extraction.service import ExtractionService
from app.services.ingestion.chunker import ContentAwareChunker

from app.services.ingestion.factories.loader_factory import LoaderFactory
from app.services.ingestion.factories.vision_factory import VisionFactory
from app.services.ingestion.service import IngestionService
from app.services.shared.factories.embedder_factory import get_embedder
from app.services.shared.factories.llm_factory import get_llm
from app.services.nl2sql.service import NL2SQLService

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    
    # --- 1. SETUP DOCUMENT ENGINE (Ingestion & Extraction) ---
    logger.info("Memuat model dan menghubungkan ke ChromaDB...")
    chroma_svc = ChromaService(embedder=get_embedder())

    logger.info("Merakit Ingestion & Extraction Services...")
    ingestion_svc = IngestionService(
        loader_factory=LoaderFactory(),
        vision_factory=VisionFactory(),
        chunker=ContentAwareChunker()
    )
    extraction_svc = ExtractionService()

    app.state.document_engine = DocumentProcessingEngine(
        ingestion_svc=ingestion_svc,
        chroma_svc=chroma_svc,
        extraction_svc=extraction_svc
    )

    # --- 2. SETUP NL2SQL CHAT ENGINE ---
    logger.info("Memesan mesin AI dari Factory untuk NL2SQL...")
    # Kita minta LLM provider dari Factory
    nl2sql_llm_provider = get_llm(model_type="extraction", temperature=0.0)
    
    logger.info("Merakit NL2SQL Service...")
    # Kita suntikkan provider tersebut ke dalam Service
    app.state.nl2sql_service = NL2SQLService(llm_provider=nl2sql_llm_provider)

    logger.info("Semua engine siap melayani!")
    yield


app = FastAPI(
    title="Argos - Competitive Intelligence API",
    description="API untuk RAG dan Agentic Extraction",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(document_router, prefix="/api/v1/document", tags=['Document Processing'])
app.include_router(chat_router, prefix="/api/v1/chat", tags=['Chat & NL2SQL'])

app.mount("/css", StaticFiles(directory="web-app/css"), name="css")
app.mount("/js", StaticFiles(directory="web-app/js"), name="js")


@app.get("/", tags=["Frontend"])
@app.get("/home", tags=["Frontend"])
def index():
    return FileResponse("web-app/index.html")


@app.get('/health', tags=['Health Check'])
def health_check():
    return {"status": "healthy", "message": "System is running fast and smoothly!"}