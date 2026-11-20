from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import app_config, secrets
from app.core.fetch_metadata import FetchMetadataMiddleware
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
    # API tidak bisa dibuka dari address bar / situs lain (DESIGN_GROUP_D.md D2).
    # Dicek sebelum CORS & autentikasi.
    app.add_middleware(
        FetchMetadataMiddleware,
        allowed_origins=secrets.cors_origins,
        cookie_name=app_config.SESSION_COOKIE_NAME,
    )
    # Ditambahkan terakhir = lapisan terluar, sehingga request ID sudah ada
    # untuk semua middleware & handler di dalamnya.
    app.add_middleware(RequestIDMiddleware)
