from fastapi import FastAPI

from app.api.routers.admin import router as admin_router
from app.api.routers.auth import router as auth_router
from app.api.routers.health import router as health_router
from app.api.routers.library import router as library_router
from app.api.routers.notebooks import router as notebook_router
from app.api.routers.pages import router as pages_router
from app.api.routers.users import router as user_router
from app.api.routers.voice import router as voice_router


def register_routers(app: FastAPI) -> None:
    app.include_router(auth_router)
    app.include_router(user_router)
    app.include_router(library_router)
    app.include_router(notebook_router)
    app.include_router(voice_router)
    app.include_router(admin_router)
    app.include_router(health_router)
    app.include_router(pages_router)
