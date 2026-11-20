"""Klasifikasi kegagalan panggilan AI menjadi kode stabil (DESIGN_GROUP_C.md §3, §7.3).

Kode ini masuk ke ``llm_calls.error_code`` dan ``metadata.issues`` chat. Pesan
exception asli tidak pernah dikirim ke klien; hanya ke log.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import openai

LLM_TIMEOUT = "LLM_TIMEOUT"
LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
LLM_BAD_RESPONSE = "LLM_BAD_RESPONSE"
LLM_REJECTED = "LLM_REJECTED"
LLM_AUTH = "LLM_AUTH"
LLM_ERROR = "LLM_ERROR"


def causes(exc: BaseException) -> Iterator[BaseException]:
    """Exception beserta rantai ``__cause__`` / ``__context__``-nya."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _bad_response_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [json.JSONDecodeError]
    try:
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        types.append(UnexpectedModelBehavior)
    except ImportError:  # pragma: no cover — pydantic-ai selalu terpasang
        pass
    return tuple(types)


_BAD_RESPONSE = _bad_response_types()


def classify_llm_error(exc: BaseException) -> str:
    """Kode stabil untuk kegagalan panggilan OpenAI (atau pembungkusnya)."""
    for e in causes(exc):
        # APITimeoutError adalah subclass APIConnectionError → cek lebih dulu.
        if isinstance(e, (openai.APITimeoutError, httpx.TimeoutException, TimeoutError)):
            return LLM_TIMEOUT
        if isinstance(e, openai.RateLimitError):
            return LLM_RATE_LIMITED
        if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return LLM_AUTH
        if isinstance(e, (openai.BadRequestError, openai.UnprocessableEntityError)):
            return LLM_REJECTED
        if isinstance(e, (openai.InternalServerError, openai.APIConnectionError, httpx.TransportError)):
            return LLM_UNAVAILABLE
        if isinstance(e, openai.APIStatusError) and e.status_code >= 500:
            return LLM_UNAVAILABLE
        if isinstance(e, _BAD_RESPONSE):
            return LLM_BAD_RESPONSE
    return LLM_ERROR
