"""Tests for the uniform error contract and request ID propagation."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import (
    ConflictError,
    NotFoundError,
    UpstreamError,
    register_exception_handlers,
)
from app.core.request_context import REQUEST_ID_HEADER, RequestIDMiddleware


class Body(BaseModel):
    n: int


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestIDMiddleware)

    @app.get("/not-found")
    def not_found():
        raise NotFoundError("Dokumen tidak ditemukan.")

    @app.get("/conflict")
    def conflict():
        raise ConflictError(code="VERSION_PINNED", details={"notebooks": 2})

    @app.get("/upstream")
    def upstream():
        raise UpstreamError()

    @app.get("/http")
    def http():
        raise HTTPException(status_code=401, detail="Invalid token")

    @app.get("/boom")
    def boom():
        raise ValueError("secret internal detail /etc/passwd")

    @app.post("/validate")
    def validate(body: Body):
        return body

    @app.get("/ok")
    def ok():
        return {"ok": True}

    return app


client = TestClient(_app(), raise_server_exceptions=False)


def test_argos_error_shape():
    r = client.get("/not-found")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND"
    assert err["message"] == "Dokumen tidak ditemukan."
    assert err["retryable"] is False
    assert err["request_id"] == r.headers[REQUEST_ID_HEADER]


def test_custom_code_and_details():
    err = client.get("/conflict").json()["error"]
    assert err["code"] == "VERSION_PINNED"
    assert err["details"] == {"notebooks": 2}


def test_upstream_is_retryable():
    r = client.get("/upstream")
    assert r.status_code == 503
    assert r.json()["error"]["retryable"] is True


def test_http_exception_mapped():
    r = client.get("/http")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "HTTP_401"


def test_unhandled_error_does_not_leak_details():
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.text
    assert "passwd" not in body
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert r.json()["error"]["request_id"]


def test_validation_error_shape():
    r = client.post("/validate", json={"n": "abc"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"]["fields"]


def test_request_id_generated_and_echoed():
    r = client.get("/ok")
    assert len(r.headers[REQUEST_ID_HEADER]) == 12
    r2 = client.get("/ok", headers={REQUEST_ID_HEADER: "abc-123"})
    assert r2.headers[REQUEST_ID_HEADER] == "abc-123"


def test_unsafe_request_id_replaced():
    r = client.get("/ok", headers={REQUEST_ID_HEADER: "bad id<script>"})
    assert r.headers[REQUEST_ID_HEADER] != "bad id<script>"
