from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import app_config, secrets
from app.core.fetch_metadata import FetchMetadataMiddleware
from app.core.observability.logs.request_id import REQUEST_ID_HEADER, RequestIDMiddleware


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(SessionMiddleware, secret_key=secrets.SECRET_KEY)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=secrets.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    # The API cannot be opened from the address bar / other sites.
    # Checked before CORS & authentication.
    app.add_middleware(
        FetchMetadataMiddleware,
        allowed_origins=secrets.cors_origins,
        cookie_name=app_config.SESSION_COOKIE_NAME,
    )
    # Added last = outermost layer, so the request ID already exists
    # for every middleware & handler inside it.
    app.add_middleware(RequestIDMiddleware)
