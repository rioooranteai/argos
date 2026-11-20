"""Kontrak error Argos (DESIGN_GROUP_C.md §2).

Semua error yang sampai ke klien memakai bentuk yang sama::

    {"error": {"code": "...", "message": "...", "request_id": "...", "retryable": false}}

Detail teknis (pesan exception asli, stack trace) hanya masuk log.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import REQUEST_ID_HEADER, request_id_from

logger = logging.getLogger(__name__)


class ArgosError(Exception):
    """Basis semua error domain. Subclass menetapkan default code/status."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    retryable: bool = False
    default_message: str = "Terjadi kesalahan pada sistem."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(ArgosError):
    code = "VALIDATION_ERROR"
    http_status = 400
    default_message = "Permintaan tidak valid."


class AuthenticationError(ArgosError):
    code = "UNAUTHENTICATED"
    http_status = 401
    default_message = "Silakan login terlebih dahulu."


class PermissionDenied(ArgosError):
    code = "PERMISSION_DENIED"
    http_status = 403
    default_message = "Anda tidak memiliki akses."


class NotFoundError(ArgosError):
    code = "NOT_FOUND"
    http_status = 404
    default_message = "Data tidak ditemukan."


class ConflictError(ArgosError):
    code = "CONFLICT"
    http_status = 409
    default_message = "Permintaan bertentangan dengan kondisi data saat ini."


class PayloadTooLarge(ArgosError):
    code = "PAYLOAD_TOO_LARGE"
    http_status = 413
    default_message = "Ukuran data melebihi batas."


class UnsupportedMediaType(ArgosError):
    code = "UNSUPPORTED_MEDIA_TYPE"
    http_status = 415
    default_message = "Format file tidak didukung."


class UpstreamError(ArgosError):
    code = "UPSTREAM_UNAVAILABLE"
    http_status = 503
    retryable = True
    default_message = "Layanan AI sedang tidak tersedia. Coba lagi sebentar."


class UpstreamTimeout(ArgosError):
    code = "UPSTREAM_TIMEOUT"
    http_status = 504
    retryable = True
    default_message = "Proses terlalu lama dan dihentikan. Coba lagi."


class InternalError(ArgosError):
    code = "INTERNAL_ERROR"
    http_status = 500


def error_body(
    code: str,
    message: str,
    request_id: str | None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
        "retryable": retryable,
    }
    if details:
        body["details"] = details
    return {"error": body}


def _response(request: Request, status: int, body: dict[str, Any]) -> JSONResponse:
    rid = request_id_from(request)
    headers = {REQUEST_ID_HEADER: rid} if rid else None
    return JSONResponse(status_code=status, content=body, headers=headers)


async def _argos_error_handler(request: Request, exc: ArgosError) -> JSONResponse:
    rid = request_id_from(request)
    if exc.http_status >= 500:
        logger.error("ArgosError %s (%s): %s", exc.code, rid, exc.message, exc_info=exc)
    else:
        logger.info("ArgosError %s (%s): %s", exc.code, rid, exc.message)
    return _response(
        request,
        exc.http_status,
        error_body(exc.code, exc.message, rid, exc.retryable, exc.details),
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    rid = request_id_from(request)
    message = exc.detail if isinstance(exc.detail, str) else "Permintaan tidak dapat diproses."
    return _response(request, exc.status_code, error_body(f"HTTP_{exc.status_code}", message, rid))


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    rid = request_id_from(request)
    fields = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", "")} for err in exc.errors()
    ]
    return _response(
        request,
        422,
        error_body("VALIDATION_ERROR", "Data permintaan tidak valid.", rid, details={"fields": fields}),
    )


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = request_id_from(request)
    logger.exception("Unhandled error (%s)", rid, exc_info=exc)
    return _response(
        request,
        500,
        error_body(InternalError.code, InternalError.default_message, rid),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ArgosError, _argos_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler)
