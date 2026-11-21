"""Rate limits per user per endpoint group (DESIGN_GROUP_D.md D9).

Sliding window: each key stores the request times within the last ``window``
seconds. Going over the limit → ``RateLimited`` (429 + ``Retry-After``).

Kept in process memory: enough because the app runs with 1 worker.
Counters are lost on restart; if there is ever more than 1 instance, move this to Redis.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Depends, Request

from app.core.config import app_config
from app.core.errors import RateLimited

logger = logging.getLogger(__name__)

_CLEANUP_EVERY = 1000  # hits; idle keys are dropped so memory does not grow


class RateLimiter:
    def __init__(
        self,
        limits: dict[str, int],
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = dict(limits)
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._since_cleanup = 0

    def check(self, group: str, key: str) -> None:
        """Record one request; raise ``RateLimited`` when the group limit is exceeded."""
        retry_after = self.hit(group, key)
        if retry_after is not None:
            logger.warning("Rate limit '%s' exceeded (key %s), retry in %s s.",
                           group, key, retry_after)
            raise RateLimited(
                f"Too many requests. Try again in {retry_after} seconds.",
                retry_after=retry_after,
            )

    def hit(self, group: str, key: str) -> int | None:
        """None when allowed (and recorded); otherwise the seconds until it is allowed again."""
        limit = self._limits[group]
        now = self._clock()
        with self._lock:
            bucket = self._hits.setdefault((group, key), deque())
            while bucket and bucket[0] <= now - self._window:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(1, math.ceil(bucket[0] + self._window - now))
            bucket.append(now)
            self._since_cleanup += 1
            if self._since_cleanup >= _CLEANUP_EVERY:
                self._cleanup(now)
        return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._since_cleanup = 0

    def tracked_keys(self) -> int:
        return len(self._hits)

    def _cleanup(self, now: float) -> None:
        stale = [k for k, b in self._hits.items() if not b or b[-1] <= now - self._window]
        for k in stale:
            del self._hits[k]
        self._since_cleanup = 0


limiter = RateLimiter(
    {
        "chat": app_config.RATE_LIMIT_CHAT,
        "voice": app_config.RATE_LIMIT_VOICE,
        "upload": app_config.RATE_LIMIT_UPLOAD,
        "login": app_config.RATE_LIMIT_LOGIN,
        "default": app_config.RATE_LIMIT_DEFAULT,
    },
    window_seconds=app_config.RATE_LIMIT_WINDOW_SECONDS,
)


def client_ip(request: Request) -> str:
    """Client IP (behind a proxy: from X-Forwarded-For when uvicorn trusts the proxy)."""
    return request.client.host if request.client else "unknown"


def rate_limit(group: str) -> Callable[..., None]:
    """FastAPI dependency: the `group` limit per signed-in user."""
    from app.core.dependencies import get_current_user  # avoid a circular import
    from app.services.user.model import CurrentUser

    def _check(user: CurrentUser = Depends(get_current_user)) -> None:
        limiter.check(group, user.id)

    _check.__name__ = f"rate_limit_{group}"
    return _check
