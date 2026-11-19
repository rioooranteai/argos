from app.core.config import secrets
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(SessionMiddleware, secret_key=secrets.SECRET_KEY)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=secrets.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )
