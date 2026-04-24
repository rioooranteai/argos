from app.api.routers.auth import router as auth_router
from app.api.routers.chat import router as chat_router
from app.api.routers.document import router as document_router
from app.api.routers.users import router as user_router
from app.api.routers.voice import router as voice_router
from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    app.include_router(auth_router)
    app.include_router(user_router)
    app.include_router(document_router)
    app.include_router(chat_router)
    app.include_router(voice_router)
