import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import register_routers
from app.core.config import app_config
from app.core.errors import register_exception_handlers
from app.core.logging_setup import configure_logging
from app.core.middleware import register_middleware
from app.core.startup import lifespan

configure_logging(app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Argos - Competitive Intelligence API",
    description="API untuk RAG dan Agentic Extraction",
    version="1.0.0",
    lifespan=lifespan,
)

register_middleware(app)
register_exception_handlers(app)
register_routers(app)

app.mount("/css", StaticFiles(directory="web-app/css"), name="css")
app.mount("/js", StaticFiles(directory="web-app/js"), name="js")


@app.get("/", tags=["Frontend"])
@app.get("/home", tags=["Frontend"])
def index():
    return FileResponse("web-app/index.html")


@app.get("/login", tags=["Frontend"])
def login_page():
    return FileResponse("web-app/login.html")
