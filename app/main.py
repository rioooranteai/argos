import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import register_routers
from app.core.config import app_config
from app.core.errors import register_exception_handlers
from app.core.logging_setup import configure_logging
from app.core.middleware import register_middleware
from app.core.startup import lifespan

configure_logging(app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)

_docs = app_config.API_DOCS_ENABLED  # D5: public for the portfolio; turn off in config.py
app = FastAPI(
    title="Argos - Competitive Intelligence API",
    description="API for RAG and Agentic Extraction",
    version="1.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

register_middleware(app)
register_exception_handlers(app)
register_routers(app)

# Public CSS (used by the login page). Pages & /js are served by the `pages` router (session required).
app.mount("/css", StaticFiles(directory="web-app/css"), name="css")
