"""Classify failed AI calls into stable codes.

The codes go into ``llm_calls.error_code`` and the chat ``metadata.issues``. The
original exception message is never sent to the client; it only goes to the log.
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
    """The exception and its ``__cause__`` / ``__context__`` chain."""
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
    except ImportError:  # pragma: no cover — pydantic-ai is always installed
        pass
    return tuple(types)


_BAD_RESPONSE = _bad_response_types()


def classify_llm_error(exc: BaseException) -> str:
    """Stable code for a failed OpenAI call (or a wrapper around it)."""
    for e in causes(exc):
        # APITimeoutError is a subclass of APIConnectionError → check it first.
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
