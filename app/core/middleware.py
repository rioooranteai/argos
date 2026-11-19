from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import secrets
from app.core.request_context import REQUEST_ID_HEADER, RequestIDMiddleware


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(SessionMiddleware, secret_key=secrets.SECRET_KEY)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=secrets.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    # Ditambahkan terakhir = lapisan terluar, sehingga request ID sudah ada
    # untuk semua middleware & handler di dalamnya.
    app.add_middleware(RequestIDMiddleware)
